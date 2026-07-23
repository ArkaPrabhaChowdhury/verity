package orchestrator

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type Engine struct {
	Planner    Planner
	Executor   Executor
	Critic     Critic
	Writer     Writer
	Repository Repository
	Events     EventSink
}

type runRecorder struct {
	mu            sync.Mutex
	llmCalls      []LLMCallMetadata
	searchQueries int
	searchCostUSD float64
}

func (r *runRecorder) RecordLLM(stage string, response llm.CompletionResponse, duration time.Duration) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.llmCalls = append(r.llmCalls, LLMCallMetadata{Stage: stage, Provider: response.Provider, Model: response.Model, PromptTokens: response.Usage.PromptTokens, CompletionTokens: response.Usage.CompletionTokens, TotalTokens: response.Usage.TotalTokens, EstimatedCostUSD: response.Usage.EstimatedCostUSD, DurationMS: duration.Milliseconds()})
}

func (r *runRecorder) RecordSearch(estimatedCostUSD float64) {
	r.mu.Lock()
	r.searchQueries++
	r.searchCostUSD += estimatedCostUSD
	r.mu.Unlock()
}

func (r *runRecorder) Apply(metadata *RunMetadata) {
	r.mu.Lock()
	defer r.mu.Unlock()
	metadata.LLMCalls = append([]LLMCallMetadata(nil), r.llmCalls...)
	metadata.SearchQueries = r.searchQueries
	metadata.TotalTokens = 0
	metadata.LLMEstimatedCostUSD = 0
	for _, call := range r.llmCalls {
		metadata.TotalTokens += call.TotalTokens
		metadata.LLMEstimatedCostUSD += call.EstimatedCostUSD
	}
	metadata.SearchEstimatedCostUSD = r.searchCostUSD
	metadata.EstimatedCostUSD = metadata.LLMEstimatedCostUSD + metadata.SearchEstimatedCostUSD
}

func (e *Engine) Run(ctx context.Context, run *Run) {
	started := time.Now()
	now := started.UTC()
	run.Status = RunRunning
	run.StartedAt = &now
	if run.Metadata.StageLatencyMS == nil {
		run.Metadata.StageLatencyMS = make(map[string]int64)
	}
	recorder := &runRecorder{}
	var runMu sync.Mutex
	e.save(ctx, run)

	fail := func(stage string, err error) {
		completed := time.Now().UTC()
		if ctx.Err() != nil {
			run.Status = RunCancelled
			run.Error = "Research run cancelled."
		} else {
			run.Status = RunFailed
			run.Error = fmt.Sprintf("%s: %v", stage, err)
		}
		run.CompletedAt = &completed
		run.Metadata.TotalLatencyMS = time.Since(started).Milliseconds()
		recorder.Apply(&run.Metadata)
		e.save(context.Background(), run)
		eventType := "run_failed"
		if run.Status == RunCancelled {
			eventType = "run_cancelled"
		}
		e.emit(context.Background(), run.ID, eventType, map[string]string{"stage": stage, "error": run.Error})
	}
	defer func() {
		if recovered := recover(); recovered != nil {
			fail("panic recovery", fmt.Errorf("unexpected panic: %v", recovered))
		}
	}()

	stageStart := time.Now()
	plan, err := e.Planner.Create(ctx, run.Question, 0, "", nil, recorder)
	run.Metadata.StageLatencyMS["planning"] += time.Since(stageStart).Milliseconds()
	if err != nil {
		fail("planning", err)
		return
	}
	run.Plans = append(run.Plans, plan)
	e.emit(ctx, run.ID, "plan_created", plan)
	e.save(ctx, run)

	stageStart = time.Now()
	e.Executor.Execute(ctx, run.ID, plan, recorder, func(finding Finding) {
		runMu.Lock()
		run.Findings = append(run.Findings, finding)
		e.save(ctx, run)
		runMu.Unlock()
	}, func(eventType string, data any) { e.emit(ctx, run.ID, eventType, data) })
	run.Metadata.StageLatencyMS["executing"] += time.Since(stageStart).Milliseconds()
	e.save(ctx, run)

	stageStart = time.Now()
	critique, err := e.Critic.Review(ctx, run.Question, run.Plans, run.Findings, recorder)
	run.Metadata.StageLatencyMS["critiquing"] += time.Since(stageStart).Milliseconds()
	if err != nil {
		fail("critiquing", err)
		return
	}
	critique.Decision = strings.ToUpper(critique.Decision)
	enforceCriticDecision(&critique, run.Findings)
	if critique.Decision == "RE_PLAN" && !run.Options.ReplanEnabled {
		critique.ForcedProceed = true
		critique.Decision = "PROCEED"
		critique.NotesForReplan = strings.TrimSpace(critique.NotesForReplan + " Re-plan disabled for this evaluation variant; proceeding with the identified gaps.")
	}
	run.Critiques = append(run.Critiques, critique)
	e.emit(ctx, run.ID, "critic_decision", critique)
	e.save(ctx, run)

	if critique.Decision == "RE_PLAN" {
		run.Metadata.ReplanOccurred = true
		e.emit(ctx, run.ID, "replan_started", map[string]any{"round": 1, "notes": critique.NotesForReplan})

		stageStart = time.Now()
		replan, replanErr := e.Planner.Create(ctx, run.Question, 1, critique.NotesForReplan, run.Findings, recorder)
		run.Metadata.StageLatencyMS["planning"] += time.Since(stageStart).Milliseconds()
		if replanErr != nil {
			fail("replanning", replanErr)
			return
		}
		run.Plans = append(run.Plans, replan)
		e.emit(ctx, run.ID, "plan_created", replan)

		stageStart = time.Now()
		e.Executor.Execute(ctx, run.ID, replan, recorder, func(finding Finding) {
			runMu.Lock()
			run.Findings = append(run.Findings, finding)
			e.save(ctx, run)
			runMu.Unlock()
		}, func(eventType string, data any) { e.emit(ctx, run.ID, eventType, data) })
		run.Metadata.StageLatencyMS["executing"] += time.Since(stageStart).Milliseconds()
		e.save(ctx, run)

		stageStart = time.Now()
		secondCritique, criticErr := e.Critic.Review(ctx, run.Question, run.Plans, run.Findings, recorder)
		run.Metadata.StageLatencyMS["critiquing"] += time.Since(stageStart).Milliseconds()
		if criticErr != nil {
			fail("second critique", criticErr)
			return
		}
		secondCritique.Decision = strings.ToUpper(secondCritique.Decision)
		enforceCriticDecision(&secondCritique, run.Findings)
		if secondCritique.Decision == "RE_PLAN" {
			secondCritique.ForcedProceed = true
			secondCritique.Decision = "PROCEED"
			secondCritique.NotesForReplan = strings.TrimSpace(secondCritique.NotesForReplan + " Maximum one re-plan cycle reached; proceeding with unresolved gaps.")
		}
		run.Critiques = append(run.Critiques, secondCritique)
		e.emit(ctx, run.ID, "critic_decision", secondCritique)
		e.save(ctx, run)
	}

	stageStart = time.Now()
	run.Trust = assessTrust(run.Findings, run.Critiques)
	e.emit(ctx, run.ID, "trust_assessed", run.Trust)
	report, err := e.Writer.Write(ctx, run.Question, run.Findings, run.Critiques, run.Trust, recorder)
	run.Metadata.StageLatencyMS["writing"] += time.Since(stageStart).Milliseconds()
	if err != nil {
		fail("writing", err)
		return
	}
	run.Report = report
	run.Status = RunCompleted
	completed := time.Now().UTC()
	run.CompletedAt = &completed
	run.Metadata.TotalLatencyMS = time.Since(started).Milliseconds()
	run.Metadata.Outcomes = map[FindingStatus]int{FindingSuccess: 0, FindingPartial: 0, FindingFailed: 0}
	for _, finding := range run.Findings {
		run.Metadata.Outcomes[finding.Status]++
	}
	recorder.Apply(&run.Metadata)
	e.save(ctx, run)
	e.emit(ctx, run.ID, "report_completed", map[string]any{"report": report, "metadata": run.Metadata})
}

func (e *Engine) save(ctx context.Context, run *Run) {
	if e.Repository != nil {
		_ = e.Repository.SaveRun(ctx, run)
	}
}

func (e *Engine) emit(ctx context.Context, runID, eventType string, data any) {
	event := Event{RunID: runID, Type: eventType, Data: data, CreatedAt: time.Now().UTC()}
	if e.Repository != nil {
		_ = e.Repository.AppendEvent(ctx, &event)
	}
	if e.Events != nil {
		e.Events.Publish(event)
	}
}
