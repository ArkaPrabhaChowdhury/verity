package orchestrator

import "testing"

func TestTrustAssessmentIsInconclusiveWithoutSuccessfulFinding(t *testing.T) {
	findings := []Finding{{Status: FindingPartial, Sources: []SourceEvidence{{URL: "https://one.example/a", Domain: "one.example"}, {URL: "https://two.example/b", Domain: "two.example"}}}}
	trust := assessTrust(findings, nil)
	if trust.Status != TrustInconclusive {
		t.Fatalf("status = %q, want %q", trust.Status, TrustInconclusive)
	}
}

func TestDeterministicGateOverridesProceedWithThinCoverage(t *testing.T) {
	critique := CriticOutput{Decision: "PROCEED", Coverage: []CoverageAssessment{{SubQuestionID: "q1", Assessment: "thin"}}}
	enforceCriticDecision(&critique, []Finding{{Status: FindingSuccess}})
	if critique.Decision != "RE_PLAN" {
		t.Fatalf("decision = %q, want RE_PLAN", critique.Decision)
	}
}

func TestTrustAssessmentVerifiesIndependentSuccessfulEvidence(t *testing.T) {
	findings := []Finding{{Status: FindingSuccess, Sources: []SourceEvidence{{URL: "https://one.example/a", Domain: "one.example"}, {URL: "https://two.example/b", Domain: "two.example"}}}}
	trust := assessTrust(findings, nil)
	if trust.Status != TrustVerified || trust.Score != 100 {
		t.Fatalf("trust = %#v", trust)
	}
}
