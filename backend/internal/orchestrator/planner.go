package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type Planner struct{ LLM llm.Provider }

type plannerResponse struct {
	SubQuestions []struct {
		Question    string `json:"question"`
		SearchQuery string `json:"search_query"`
		Rationale   string `json:"rationale"`
	} `json:"sub_questions"`
}

func (p Planner) Create(ctx context.Context, question string, round int, criticNotes string, priorFindings []Finding, recorder usageRecorder) (Plan, error) {
	system := prompt("planner_v1")
	user := "Original question:\n" + question
	maxQuestions := 6
	minQuestions := 3
	if round > 0 {
		system = prompt("replanner_v1")
		maxQuestions = 3
		minQuestions = 1
		prior, _ := json.Marshal(priorFindings)
		user = fmt.Sprintf("Original question:\n%s\n\nCritic notes:\n%s\n\nPrior findings:\n%s", question, criticNotes, prior)
	}
	response, err := structuredCompletion(ctx, p.LLM, recorder, "planning", system, user, func(value plannerResponse) error {
		if len(value.SubQuestions) < minQuestions || len(value.SubQuestions) > maxQuestions {
			return fmt.Errorf("expected %d-%d sub-questions, got %d", minQuestions, maxQuestions, len(value.SubQuestions))
		}
		seen := make(map[string]struct{})
		for _, item := range value.SubQuestions {
			if strings.TrimSpace(item.Question) == "" || strings.TrimSpace(item.SearchQuery) == "" || strings.TrimSpace(item.Rationale) == "" {
				return fmt.Errorf("question, search_query, and rationale are required")
			}
			if len([]rune(item.SearchQuery)) > 180 {
				return fmt.Errorf("search_query is too long for %q", item.Question)
			}
			normalized := strings.ToLower(strings.TrimSpace(item.Question))
			if _, duplicate := seen[normalized]; duplicate {
				return fmt.Errorf("duplicate sub-question %q", item.Question)
			}
			seen[normalized] = struct{}{}
			for _, finding := range priorFindings {
				if normalized == strings.ToLower(strings.TrimSpace(finding.Question)) {
					return fmt.Errorf("supplemental plan repeats prior question %q", item.Question)
				}
			}
		}
		return nil
	})
	if err != nil {
		return Plan{}, err
	}
	plan := Plan{Round: round, SubQuestions: make([]SubQuestion, 0, len(response.SubQuestions))}
	for i, item := range response.SubQuestions {
		plan.SubQuestions = append(plan.SubQuestions, SubQuestion{
			ID:          fmt.Sprintf("q-r%d-%d", round, i+1),
			Question:    strings.TrimSpace(item.Question),
			SearchQuery: strings.TrimSpace(item.SearchQuery),
			Rationale:   strings.TrimSpace(item.Rationale),
			Round:       round,
		})
	}
	return plan, nil
}
