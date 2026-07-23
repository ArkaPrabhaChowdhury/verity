package orchestrator

import (
	"context"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/arkop/verity/backend/internal/extraction"
	"github.com/arkop/verity/backend/internal/providers/llm"
	"github.com/arkop/verity/backend/internal/providers/search"
)

type scriptedLLM struct {
	mu          sync.Mutex
	criticCalls int
}

func (s *scriptedLLM) Complete(_ context.Context, req llm.CompletionRequest) (llm.CompletionResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	content := ""
	switch {
	case strings.Contains(req.SystemPrompt, "corrective research planner"):
		content = `{"sub_questions":[{"question":"Which independent source resolves the remaining gap?","search_query":"independent source remaining evidence gap","rationale":"Resolve the critic gap."}]}`
	case strings.Contains(req.SystemPrompt, "research planner"):
		content = `{"sub_questions":[{"question":"What is fact one?","search_query":"fact one evidence","rationale":"Needed."},{"question":"What is fact two?","search_query":"fact two evidence","rationale":"Needed."},{"question":"What is fact three?","search_query":"fact three evidence","rationale":"Needed."}]}`
	case strings.Contains(req.SystemPrompt, "evidence critic"):
		s.criticCalls++
		coverage := `[{"sub_question_id":"q-r0-1","assessment":"thin","reason":"More evidence needed."},{"sub_question_id":"q-r0-2","assessment":"sufficient","reason":"Two sources."},{"sub_question_id":"q-r0-3","assessment":"sufficient","reason":"Two sources."}]`
		if strings.Contains(req.Prompt, "q-r1-1") {
			coverage = `[{"sub_question_id":"q-r0-1","assessment":"thin","reason":"More evidence needed."},{"sub_question_id":"q-r0-2","assessment":"sufficient","reason":"Two sources."},{"sub_question_id":"q-r0-3","assessment":"sufficient","reason":"Two sources."},{"sub_question_id":"q-r1-1","assessment":"thin","reason":"Still unresolved."}]`
		}
		content = `{"coverage_assessment":` + coverage + `,"contradictions":[],"decision":"RE_PLAN","notes_for_replan":"Find one more independent source."}`
	case strings.Contains(req.SystemPrompt, "evidence extractor"):
		content = `{"sources":[{"url":"https://example.com/one","summary":"Supported evidence (https://example.com/one)."},{"url":"https://example.com/two","summary":"Corroborating evidence (https://example.com/two)."}]}`
	case strings.Contains(req.SystemPrompt, "report writer"):
		content = "**Direct answer:** Direct answer with evidence [1].\n\n## References\n1. [Source](https://example.com/one)\n\n## Gaps & Caveats\nThe bounded second critique still found a gap."
	}
	return llm.CompletionResponse{Content: content, Provider: "fake", Model: "fake", Usage: llm.Usage{TotalTokens: 10}}, nil
}

type fakeSearch struct{}

func (fakeSearch) Search(context.Context, string, int) ([]search.Result, error) {
	return []search.Result{{Title: "One", URL: "https://example.com/one"}, {Title: "Two", URL: "https://example.com/two"}}, nil
}

type fakeFetcher struct{}

func (fakeFetcher) Fetch(_ context.Context, rawURL string) (extraction.Document, error) {
	return extraction.Document{URL: rawURL, Title: "Evidence", Text: strings.Repeat("Evidence text. ", 30)}, nil
}

type memoryRepository struct {
	mu     sync.Mutex
	events []Event
}

func (*memoryRepository) SaveRun(context.Context, *Run) error { return nil }
func (m *memoryRepository) AppendEvent(_ context.Context, event *Event) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	event.Seq = int64(len(m.events) + 1)
	m.events = append(m.events, *event)
	return nil
}

func TestEngineAllowsOnlyOneReplan(t *testing.T) {
	model := &scriptedLLM{}
	repository := &memoryRepository{}
	engine := Engine{
		Planner:    Planner{LLM: model},
		Executor:   Executor{LLM: model, Search: fakeSearch{}, Extractor: fakeFetcher{}, Concurrency: 4, TaskTimeout: time.Second, MaxResults: 2, SearchCostPerQuery: 0.005},
		Critic:     Critic{LLM: model},
		Writer:     Writer{LLM: model},
		Repository: repository,
	}
	run := &Run{ID: "test", Question: "What is the complete answer to this test question?", Status: RunQueued, CreatedAt: time.Now(), Metadata: RunMetadata{StageLatencyMS: map[string]int64{}}, Options: RunOptions{ReplanEnabled: true}}
	engine.Run(context.Background(), run)
	if run.Status != RunCompleted {
		t.Fatalf("run status = %s, error = %s", run.Status, run.Error)
	}
	if len(run.Plans) != 2 {
		t.Fatalf("expected exactly two plans, got %d", len(run.Plans))
	}
	if len(run.Critiques) != 2 || !run.Critiques[1].ForcedProceed {
		t.Fatalf("expected second critique to force proceed: %#v", run.Critiques)
	}
	replans := 0
	for _, event := range repository.events {
		if event.Type == "replan_started" {
			replans++
		}
	}
	if replans != 1 {
		t.Fatalf("expected one replan event, got %d", replans)
	}
	if !strings.Contains(run.Report, "## Gaps & Caveats") {
		t.Fatal("report omitted mandatory gaps section")
	}
}

type blockingFetcher struct{}

func (blockingFetcher) Fetch(ctx context.Context, _ string) (extraction.Document, error) {
	<-ctx.Done()
	return extraction.Document{}, ctx.Err()
}

func TestExecutorTaskTimeoutBecomesFailedFinding(t *testing.T) {
	executor := Executor{LLM: &scriptedLLM{}, Search: fakeSearch{}, Extractor: blockingFetcher{}, Concurrency: 1, TaskTimeout: 20 * time.Millisecond, MaxResults: 1}
	recorder := &runRecorder{}
	plan := Plan{SubQuestions: []SubQuestion{{ID: "q1", Question: "Timed question", Round: 0}}}
	findings := executor.Execute(context.Background(), "run", plan, recorder, nil, func(string, any) {})
	if len(findings) != 1 || findings[0].Status != FindingFailed {
		t.Fatalf("expected failed finding, got %#v", findings)
	}
}
