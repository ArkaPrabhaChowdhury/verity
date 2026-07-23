package orchestrator

import (
	"context"
	"time"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type RunStatus string

const (
	RunQueued    RunStatus = "queued"
	RunRunning   RunStatus = "running"
	RunCompleted RunStatus = "completed"
	RunFailed    RunStatus = "failed"
	RunCancelled RunStatus = "cancelled"
)

type Plan struct {
	Round        int           `json:"round"`
	SubQuestions []SubQuestion `json:"sub_questions"`
}

type SubQuestion struct {
	ID          string `json:"id"`
	Question    string `json:"question"`
	SearchQuery string `json:"search_query,omitempty"`
	Rationale   string `json:"rationale"`
	Round       int    `json:"round"`
}

type FindingStatus string

const (
	FindingSuccess FindingStatus = "success"
	FindingPartial FindingStatus = "partial"
	FindingFailed  FindingStatus = "failed"
)

type SourceEvidence struct {
	Title        string    `json:"title"`
	URL          string    `json:"url"`
	Domain       string    `json:"domain"`
	Summary      string    `json:"summary"`
	Excerpt      string    `json:"excerpt"`
	SourceType   string    `json:"source_type"`
	QualityScore int       `json:"quality_score"`
	FetchedAt    time.Time `json:"fetched_at"`
}

type Finding struct {
	SubQuestionID string           `json:"sub_question_id"`
	Question      string           `json:"question"`
	Status        FindingStatus    `json:"status"`
	Sources       []SourceEvidence `json:"sources"`
	Error         string           `json:"error,omitempty"`
	DurationMS    int64            `json:"duration_ms"`
	Round         int              `json:"round"`
}

type CoverageAssessment struct {
	SubQuestionID string `json:"sub_question_id"`
	Assessment    string `json:"assessment"`
	Reason        string `json:"reason"`
}

type Contradiction struct {
	Claim       string   `json:"claim"`
	SourceURLs  []string `json:"source_urls"`
	Explanation string   `json:"explanation"`
}

type CriticOutput struct {
	Coverage       []CoverageAssessment `json:"coverage_assessment"`
	Contradictions []Contradiction      `json:"contradictions"`
	Decision       string               `json:"decision"`
	NotesForReplan string               `json:"notes_for_replan,omitempty"`
	ForcedProceed  bool                 `json:"forced_proceed,omitempty"`
}

type TrustAssessment struct {
	Status             string   `json:"status"`
	Score              int      `json:"score"`
	Summary            string   `json:"summary"`
	Reasons            []string `json:"reasons"`
	SuccessfulFindings int      `json:"successful_findings"`
	PartialFindings    int      `json:"partial_findings"`
	FailedFindings     int      `json:"failed_findings"`
	IndependentDomains int      `json:"independent_domains"`
	HasContradictions  bool     `json:"has_contradictions"`
}

type LLMCallMetadata struct {
	Stage            string  `json:"stage"`
	Provider         string  `json:"provider"`
	Model            string  `json:"model"`
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	EstimatedCostUSD float64 `json:"estimated_cost_usd"`
	DurationMS       int64   `json:"duration_ms"`
}

type RunMetadata struct {
	TotalLatencyMS         int64                 `json:"total_latency_ms"`
	StageLatencyMS         map[string]int64      `json:"stage_latency_ms"`
	LLMCalls               []LLMCallMetadata     `json:"llm_calls"`
	TotalTokens            int                   `json:"total_tokens"`
	LLMEstimatedCostUSD    float64               `json:"llm_estimated_cost_usd"`
	SearchEstimatedCostUSD float64               `json:"search_estimated_cost_usd"`
	EstimatedCostUSD       float64               `json:"estimated_cost_usd"`
	SearchQueries          int                   `json:"search_queries"`
	ReplanOccurred         bool                  `json:"replan_occurred"`
	Outcomes               map[FindingStatus]int `json:"outcomes"`
}

type Run struct {
	ID          string          `json:"id"`
	Question    string          `json:"question"`
	Status      RunStatus       `json:"status"`
	Plans       []Plan          `json:"plans"`
	Findings    []Finding       `json:"findings"`
	Critiques   []CriticOutput  `json:"critiques"`
	Trust       TrustAssessment `json:"trust"`
	Report      string          `json:"report"`
	Metadata    RunMetadata     `json:"metadata"`
	Error       string          `json:"error,omitempty"`
	CreatedAt   time.Time       `json:"created_at"`
	StartedAt   *time.Time      `json:"started_at,omitempty"`
	CompletedAt *time.Time      `json:"completed_at,omitempty"`
	Options     RunOptions      `json:"options"`
}

type RunOptions struct {
	ReplanEnabled bool `json:"replan_enabled"`
}

type Event struct {
	Seq       int64     `json:"seq"`
	RunID     string    `json:"run_id"`
	Type      string    `json:"type"`
	Data      any       `json:"data"`
	CreatedAt time.Time `json:"created_at"`
}

type Repository interface {
	SaveRun(ctx context.Context, run *Run) error
	AppendEvent(ctx context.Context, event *Event) error
}

type EventSink interface {
	Publish(event Event)
}

type usageRecorder interface {
	RecordLLM(stage string, response llm.CompletionResponse, duration time.Duration)
	RecordSearch(estimatedCostUSD float64)
}
