package orchestrator

import (
	"fmt"
	"net/url"
	"strings"
)

const (
	TrustVerified     = "verified"
	TrustQualified    = "qualified"
	TrustInconclusive = "inconclusive"
)

func assessTrust(findings []Finding, critiques []CriticOutput) TrustAssessment {
	assessment := TrustAssessment{Status: TrustVerified, Score: 100}
	domains := make(map[string]struct{})
	for _, finding := range findings {
		switch finding.Status {
		case FindingSuccess:
			assessment.SuccessfulFindings++
		case FindingPartial:
			assessment.PartialFindings++
		case FindingFailed:
			assessment.FailedFindings++
		}
		for _, source := range finding.Sources {
			domain := source.Domain
			if domain == "" {
				if parsed, err := url.Parse(source.URL); err == nil {
					domain = parsed.Hostname()
				}
			}
			if domain != "" {
				domains[strings.TrimPrefix(domain, "www.")] = struct{}{}
			}
		}
	}
	assessment.IndependentDomains = len(domains)
	for _, critique := range critiques {
		if len(critique.Contradictions) > 0 {
			assessment.HasContradictions = true
		}
	}

	total := len(findings)
	if total == 0 || assessment.FailedFindings > 0 || assessment.SuccessfulFindings == 0 {
		assessment.Status = TrustInconclusive
		assessment.Score = 25
		assessment.Reasons = append(assessment.Reasons, "No fully successful evidence path supports a confident answer.")
	} else if assessment.PartialFindings > 0 {
		assessment.Status = TrustQualified
		assessment.Score -= min(45, assessment.PartialFindings*10)
		assessment.Reasons = append(assessment.Reasons, fmt.Sprintf("%d of %d research paths have incomplete evidence.", assessment.PartialFindings, total))
	}
	if assessment.FailedFindings > 0 {
		assessment.Score -= min(30, assessment.FailedFindings*15)
		assessment.Reasons = append(assessment.Reasons, fmt.Sprintf("%d research paths failed.", assessment.FailedFindings))
	}
	if assessment.IndependentDomains < 2 {
		assessment.Status = TrustInconclusive
		assessment.Score = min(assessment.Score, 30)
		assessment.Reasons = append(assessment.Reasons, "Fewer than two independent source domains were available.")
	}
	if assessment.HasContradictions {
		if assessment.Status == TrustVerified {
			assessment.Status = TrustQualified
		}
		assessment.Score -= 15
		assessment.Reasons = append(assessment.Reasons, "The critic found unresolved contradictory evidence.")
	}
	for _, critique := range critiques {
		if critique.ForcedProceed {
			assessment.Status = TrustInconclusive
			assessment.Score = min(assessment.Score, 35)
			assessment.Reasons = append(assessment.Reasons, "The run reached its re-plan limit with unresolved gaps.")
			break
		}
	}
	if assessment.Score < 0 {
		assessment.Score = 0
	}
	switch assessment.Status {
	case TrustVerified:
		assessment.Summary = "Evidence coverage passed Verity's deterministic trust gate."
	case TrustQualified:
		assessment.Summary = "The answer is usable with material qualifications."
	default:
		assessment.Summary = "Evidence is insufficient for a confident direct answer."
	}
	return assessment
}

func enforceCriticDecision(output *CriticOutput, findings []Finding) {
	missingOrThin := false
	for _, coverage := range output.Coverage {
		if coverage.Assessment != "sufficient" {
			missingOrThin = true
			break
		}
	}
	hasSuccess := false
	hasFailure := false
	for _, finding := range findings {
		hasSuccess = hasSuccess || finding.Status == FindingSuccess
		hasFailure = hasFailure || finding.Status == FindingFailed
	}
	if output.Decision == "PROCEED" && (missingOrThin || !hasSuccess || hasFailure) {
		output.Decision = "RE_PLAN"
		output.NotesForReplan = strings.TrimSpace(output.NotesForReplan + " Deterministic trust gate requires resolving thin, missing, failed, or entirely partial evidence before a confident answer.")
	}
}
