package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type Critic struct{ LLM llm.Provider }

func (c Critic) Review(ctx context.Context, question string, plans []Plan, findings []Finding, recorder usageRecorder) (CriticOutput, error) {
	payload, _ := json.Marshal(map[string]any{"question": question, "plans": plans, "findings": findings})
	expectedIDs := make(map[string]struct{})
	allowedURLs := make(map[string]struct{})
	for _, plan := range plans {
		for _, subQuestion := range plan.SubQuestions {
			expectedIDs[subQuestion.ID] = struct{}{}
		}
	}
	for _, finding := range findings {
		for _, source := range finding.Sources {
			allowedURLs[source.URL] = struct{}{}
		}
	}
	return structuredCompletion(ctx, c.LLM, recorder, "critiquing", prompt("critic_v1"), string(payload), func(value CriticOutput) error {
		value.Decision = strings.ToUpper(value.Decision)
		if value.Decision != "PROCEED" && value.Decision != "RE_PLAN" {
			return fmt.Errorf("invalid decision %q", value.Decision)
		}
		if value.Decision == "RE_PLAN" && strings.TrimSpace(value.NotesForReplan) == "" {
			return fmt.Errorf("notes_for_replan required for RE_PLAN")
		}
		seen := make(map[string]struct{})
		for _, item := range value.Coverage {
			if _, expected := expectedIDs[item.SubQuestionID]; !expected {
				return fmt.Errorf("coverage references unknown sub-question %q", item.SubQuestionID)
			}
			if _, duplicate := seen[item.SubQuestionID]; duplicate {
				return fmt.Errorf("duplicate coverage for %q", item.SubQuestionID)
			}
			seen[item.SubQuestionID] = struct{}{}
			if item.Assessment != "sufficient" && item.Assessment != "thin" && item.Assessment != "missing" {
				return fmt.Errorf("invalid coverage assessment %q", item.Assessment)
			}
		}
		if len(seen) != len(expectedIDs) {
			return fmt.Errorf("coverage assessed %d of %d planned questions", len(seen), len(expectedIDs))
		}
		for _, contradiction := range value.Contradictions {
			if len(contradiction.SourceURLs) < 2 {
				return fmt.Errorf("contradiction %q requires at least two source URLs", contradiction.Claim)
			}
			for _, sourceURL := range contradiction.SourceURLs {
				if _, allowed := allowedURLs[sourceURL]; !allowed {
					return fmt.Errorf("contradiction references unknown URL %q", sourceURL)
				}
			}
		}
		return nil
	})
}
