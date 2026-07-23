package orchestrator

import (
	"context"
	"encoding/json"
	"fmt"
	"regexp"
	"strings"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type Writer struct{ LLM llm.Provider }

var reportURLPattern = regexp.MustCompile(`https?://[^\s)]+`)

func (w Writer) Write(ctx context.Context, question string, findings []Finding, critiques []CriticOutput, trust TrustAssessment, recorder usageRecorder) (string, error) {
	payload, _ := json.Marshal(map[string]any{"question": question, "findings": findings, "critic_reviews": critiques, "trust_assessment": trust})
	request := llm.CompletionRequest{SystemPrompt: prompt("writer_v1"), Prompt: string(payload), Temperature: 0.2, MaxTokens: 1800}
	response, err := complete(ctx, w.LLM, recorder, "writing", request)
	if err != nil {
		return "", err
	}
	report := strings.TrimSpace(response.Content)
	allowedURLs := make(map[string]struct{})
	for _, finding := range findings {
		for _, source := range finding.Sources {
			allowedURLs[source.URL] = struct{}{}
		}
	}
	if validationErr := validateReport(report, allowedURLs); validationErr != nil {
		request.Prompt = fmt.Sprintf("%s\n\nYour previous report was invalid: %v. Rewrite the full report and satisfy every required section and citation rule.", string(payload), validationErr)
		response, err = complete(ctx, w.LLM, recorder, "writing_validation_retry", request)
		if err != nil {
			return "", err
		}
		report = strings.TrimSpace(response.Content)
		if validationErr = validateReport(report, allowedURLs); validationErr != nil {
			return "", fmt.Errorf("writer output invalid after retry: %w", validationErr)
		}
	}
	return report, nil
}

func validateReport(report string, allowedURLs map[string]struct{}) error {
	if report == "" {
		return fmt.Errorf("report is empty")
	}
	for _, required := range []string{"**Direct answer:**", "## References", "## Gaps & Caveats"} {
		if !strings.Contains(report, required) {
			return fmt.Errorf("missing required report marker %q", required)
		}
	}
	if len(allowedURLs) > 0 && !strings.Contains(report, "[1]") {
		return fmt.Errorf("report has evidence but no numbered inline citation")
	}
	for _, rawURL := range reportURLPattern.FindAllString(report, -1) {
		cleanURL := strings.TrimRight(rawURL, ".,;:")
		if _, allowed := allowedURLs[cleanURL]; !allowed {
			return fmt.Errorf("report cites unknown URL %q", cleanURL)
		}
	}
	return nil
}
