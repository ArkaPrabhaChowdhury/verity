package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"strings"
	"time"
)

const groqEndpoint = "https://api.groq.com/openai/v1/chat/completions"
const retryAfterSafetyMargin = 2 * time.Second

var retryInPattern = regexp.MustCompile(`(?i)try again in\s+([0-9]+(?:\.[0-9]+)?(?:ms|h|m|s)(?:[0-9]+(?:\.[0-9]+)?(?:ms|h|m|s))*)`)

type groqUsage struct {
	PromptTokens     int `json:"prompt_tokens"`
	CompletionTokens int `json:"completion_tokens"`
	TotalTokens      int `json:"total_tokens"`
}

type groqModelUsage struct {
	Model string    `json:"model"`
	Usage groqUsage `json:"usage"`
}

type Groq struct {
	apiKey string
	model  string
	client *http.Client
}

func NewGroq(apiKey, model string, timeout time.Duration) *Groq {
	if model == "" {
		model = "llama-3.1-8b-instant"
	}
	return &Groq{apiKey: apiKey, model: model, client: &http.Client{Timeout: timeout}}
}

func (g *Groq) Complete(ctx context.Context, req CompletionRequest) (CompletionResponse, error) {
	if g.apiKey == "" {
		return CompletionResponse{}, ErrNotConfigured
	}
	messages := []map[string]string{{"role": "system", "content": req.SystemPrompt}, {"role": "user", "content": req.Prompt}}
	body := map[string]any{"model": g.model, "messages": messages, "temperature": req.Temperature, "tool_choice": "none"}
	if req.MaxTokens > 0 {
		body["max_tokens"] = req.MaxTokens
	}
	if req.JSONMode {
		body["response_format"] = map[string]string{"type": "json_object"}
	}
	payload, _ := json.Marshal(body)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, groqEndpoint, bytes.NewReader(payload))
	if err != nil {
		return CompletionResponse{}, err
	}
	httpReq.Header.Set("Authorization", "Bearer "+g.apiKey)
	httpReq.Header.Set("Content-Type", "application/json")
	resp, err := g.client.Do(httpReq)
	if err != nil {
		return CompletionResponse{}, err
	}
	defer resp.Body.Close()
	raw, err := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if err != nil {
		return CompletionResponse{}, err
	}
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		body := strings.TrimSpace(string(raw))
		return CompletionResponse{}, &HTTPError{StatusCode: resp.StatusCode, Body: body, RetryAfter: parseGroqRetryDelay(resp.Header.Get("Retry-After"), body)}
	}
	var decoded struct {
		Choices []struct {
			Message struct {
				Content string `json:"content"`
			} `json:"message"`
		} `json:"choices"`
		Usage          groqUsage `json:"usage"`
		UsageBreakdown struct {
			Models []groqModelUsage `json:"models"`
		} `json:"usage_breakdown"`
	}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return CompletionResponse{}, fmt.Errorf("decode Groq response: %w", err)
	}
	if len(decoded.Choices) == 0 {
		return CompletionResponse{}, fmt.Errorf("Groq returned no choices")
	}
	cost := groqEstimatedCost(g.model, decoded.Usage, decoded.UsageBreakdown.Models)
	return CompletionResponse{Content: decoded.Choices[0].Message.Content, Provider: "groq", Model: g.model, Usage: Usage{PromptTokens: decoded.Usage.PromptTokens, CompletionTokens: decoded.Usage.CompletionTokens, TotalTokens: decoded.Usage.TotalTokens, EstimatedCostUSD: cost}}, nil
}

func groqEstimatedCost(model string, usage groqUsage, breakdown []groqModelUsage) float64 {
	if len(breakdown) == 0 {
		inputRate, outputRate := groqTokenRates(model)
		return float64(usage.PromptTokens)*inputRate/1_000_000 + float64(usage.CompletionTokens)*outputRate/1_000_000
	}
	var cost float64
	for _, item := range breakdown {
		inputRate, outputRate := groqTokenRates(item.Model)
		cost += float64(item.Usage.PromptTokens)*inputRate/1_000_000 + float64(item.Usage.CompletionTokens)*outputRate/1_000_000
	}
	return cost
}

func parseGroqRetryDelay(header, body string) time.Duration {
	if delay := parseRetryAfter(header); delay > 0 {
		return delay
	}
	match := retryInPattern.FindStringSubmatch(body)
	if len(match) != 2 {
		return 0
	}
	delay, err := time.ParseDuration(strings.ToLower(match[1]))
	if err != nil || delay < 0 {
		return 0
	}
	return delay + retryAfterSafetyMargin
}

func groqTokenRates(model string) (input, output float64) {
	switch model {
	case "openai/gpt-oss-20b":
		return 0.075, 0.30
	case "openai/gpt-oss-120b":
		return 0.15, 0.60
	case "llama-3.1-8b-instant":
		return 0.05, 0.08
	default:
		return 0.59, 0.79
	}
}

func parseRetryAfter(value string) time.Duration {
	value = strings.TrimSpace(value)
	if value == "" {
		return 0
	}
	if seconds, err := strconv.Atoi(value); err == nil && seconds >= 0 {
		return time.Duration(seconds)*time.Second + retryAfterSafetyMargin
	}
	if seconds, err := strconv.ParseFloat(value, 64); err == nil && seconds >= 0 {
		return time.Duration(seconds*float64(time.Second)) + retryAfterSafetyMargin
	}
	if retryAt, err := http.ParseTime(value); err == nil {
		if delay := time.Until(retryAt); delay > 0 {
			return delay
		}
	}
	return 0
}
