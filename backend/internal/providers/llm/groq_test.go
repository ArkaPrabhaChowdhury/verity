package llm

import (
	"testing"
	"time"
)

func TestParseRetryAfterWholeSeconds(t *testing.T) {
	if got := parseRetryAfter("2"); got != 4*time.Second {
		t.Fatalf("delay = %v", got)
	}
}

func TestParseRetryAfterFractionalSeconds(t *testing.T) {
	if got := parseRetryAfter("0.22"); got != 2220*time.Millisecond {
		t.Fatalf("delay = %v", got)
	}
}

func TestParseGroqRetryDelayFromBody(t *testing.T) {
	body := `{"error":{"message":"Rate limit reached. Please try again in 1.7s."}}`
	if got := parseGroqRetryDelay("", body); got != 3700*time.Millisecond {
		t.Fatalf("delay = %v", got)
	}
}

func TestParseGroqRetryDelayWithMinutesFromBody(t *testing.T) {
	body := `{"error":{"message":"Rate limit reached. Please try again in 1m2.5s."}}`
	if got := parseGroqRetryDelay("", body); got != 64_500*time.Millisecond {
		t.Fatalf("delay = %v", got)
	}
}

func TestParseGroqRetryDelayPrefersHeader(t *testing.T) {
	if got := parseGroqRetryDelay("2", "Please try again in 9s."); got != 4*time.Second {
		t.Fatalf("delay = %v", got)
	}
}

func TestGroqTokenRates(t *testing.T) {
	input, output := groqTokenRates("openai/gpt-oss-20b")
	if input != 0.075 || output != 0.30 {
		t.Fatalf("rates = %v, %v", input, output)
	}
}

func TestGroqEstimatedCostUsesCompoundBreakdown(t *testing.T) {
	breakdown := []groqModelUsage{
		{Model: "llama-3.3-70b-versatile", Usage: groqUsage{PromptTokens: 1_000, CompletionTokens: 1_000}},
		{Model: "openai/gpt-oss-120b", Usage: groqUsage{PromptTokens: 1_000, CompletionTokens: 1_000}},
	}
	got := groqEstimatedCost("groq/compound-mini", groqUsage{}, breakdown)
	want := (0.59 + 0.79 + 0.15 + 0.60) / 1_000
	if got != want {
		t.Fatalf("cost = %v, want %v", got, want)
	}
}
