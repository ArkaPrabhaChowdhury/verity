package orchestrator

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/arkop/verity/backend/internal/extraction"
	"github.com/arkop/verity/backend/internal/providers/llm"
	"github.com/arkop/verity/backend/internal/providers/search"
)

type captureSearch struct {
	query   string
	results []search.Result
}

func (s *captureSearch) Search(_ context.Context, query string, _ int) ([]search.Result, error) {
	s.query = query
	return s.results, nil
}

type failedFetcher struct{}

func (failedFetcher) Fetch(context.Context, string) (extraction.Document, error) {
	return extraction.Document{}, errors.New("publisher blocked direct fetch")
}

type snippetLLM struct{}

func (snippetLLM) Complete(context.Context, llm.CompletionRequest) (llm.CompletionResponse, error) {
	return llm.CompletionResponse{
		Content:  `{"sources":[{"url":"https://example.com/report","summary":"The search excerpt contains directly relevant evidence."}]}`,
		Provider: "fake",
		Model:    "fake",
	}, nil
}

func TestExecutorUsesPlannedQueryAndBlockedPageSnippet(t *testing.T) {
	searcher := &captureSearch{results: []search.Result{{
		Title:       "AI valuation report",
		URL:         "https://example.com/report",
		Description: strings.Repeat("Relevant market valuation evidence. ", 3),
	}}}
	executor := Executor{LLM: snippetLLM{}, Search: searcher, Extractor: failedFetcher{}, TaskTimeout: time.Second, MaxResults: 1}
	sub := SubQuestion{ID: "q1", Question: "Which reports discuss AI valuations?", SearchQuery: "AI valuation analyst reports 2026"}

	finding := executor.executeOne(context.Background(), sub, &runRecorder{})

	if searcher.query != sub.SearchQuery {
		t.Fatalf("search query = %q, want %q", searcher.query, sub.SearchQuery)
	}
	if len(finding.Sources) != 1 || finding.Sources[0].URL != "https://example.com/report" {
		t.Fatalf("expected snippet evidence, got %#v", finding)
	}
	if finding.Status != FindingPartial {
		t.Fatalf("status = %s, want %s", finding.Status, FindingPartial)
	}
}

func TestExecutorExplainsFetchAndEvidenceFailuresSeparately(t *testing.T) {
	searcher := &captureSearch{results: []search.Result{{Title: "Blocked", URL: "https://example.com/report", Description: "short"}}}
	executor := Executor{LLM: snippetLLM{}, Search: searcher, Extractor: failedFetcher{}, TaskTimeout: time.Second, MaxResults: 1}

	finding := executor.executeOne(context.Background(), SubQuestion{ID: "q1", Question: "Question?"}, &runRecorder{})

	if finding.Status != FindingFailed {
		t.Fatalf("status = %s, want %s", finding.Status, FindingFailed)
	}
	if !strings.Contains(finding.Error, "1 direct fetches failed") || !strings.Contains(finding.Error, "0 fetched or snippet documents") {
		t.Fatalf("unexpected diagnostic: %q", finding.Error)
	}
}
