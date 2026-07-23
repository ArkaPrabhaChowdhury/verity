package llm

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

type Gemini struct {
	apiKey string
	model  string
	client *http.Client
}

func NewGemini(apiKey, model string, timeout time.Duration) *Gemini {
	if model == "" {
		model = "gemini-3.5-flash"
	}
	return &Gemini{apiKey: apiKey, model: model, client: &http.Client{Timeout: timeout}}
}

func (g *Gemini) Complete(ctx context.Context, req CompletionRequest) (CompletionResponse, error) {
	if g.apiKey == "" {
		return CompletionResponse{}, ErrNotConfigured
	}
	endpoint := fmt.Sprintf("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent?key=%s", url.PathEscape(g.model), url.QueryEscape(g.apiKey))
	config := map[string]any{"temperature": req.Temperature}
	if req.MaxTokens > 0 {
		config["maxOutputTokens"] = req.MaxTokens
	}
	if req.JSONMode {
		config["responseMimeType"] = "application/json"
	}
	body := map[string]any{
		"systemInstruction": map[string]any{"parts": []map[string]string{{"text": req.SystemPrompt}}},
		"contents":          []map[string]any{{"role": "user", "parts": []map[string]string{{"text": req.Prompt}}}},
		"generationConfig":  config,
	}
	payload, _ := json.Marshal(body)
	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, endpoint, bytes.NewReader(payload))
	if err != nil {
		return CompletionResponse{}, err
	}
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
		return CompletionResponse{}, &HTTPError{StatusCode: resp.StatusCode, Body: strings.TrimSpace(string(raw))}
	}
	var decoded struct {
		Candidates []struct {
			Content struct {
				Parts []struct {
					Text string `json:"text"`
				} `json:"parts"`
			} `json:"content"`
		} `json:"candidates"`
		Usage struct {
			PromptTokens     int `json:"promptTokenCount"`
			CompletionTokens int `json:"candidatesTokenCount"`
			TotalTokens      int `json:"totalTokenCount"`
		} `json:"usageMetadata"`
	}
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return CompletionResponse{}, fmt.Errorf("decode Gemini response: %w", err)
	}
	if len(decoded.Candidates) == 0 || len(decoded.Candidates[0].Content.Parts) == 0 {
		return CompletionResponse{}, fmt.Errorf("Gemini returned no content")
	}
	inputRate, outputRate := geminiPaidRates(g.model)
	cost := float64(decoded.Usage.PromptTokens)*inputRate/1_000_000 + float64(decoded.Usage.CompletionTokens)*outputRate/1_000_000
	return CompletionResponse{Content: decoded.Candidates[0].Content.Parts[0].Text, Provider: "gemini", Model: g.model, Usage: Usage{PromptTokens: decoded.Usage.PromptTokens, CompletionTokens: decoded.Usage.CompletionTokens, TotalTokens: decoded.Usage.TotalTokens, EstimatedCostUSD: cost}}, nil
}

func geminiPaidRates(model string) (input, output float64) {
	switch model {
	case "gemini-3.5-flash":
		return 2.70, 16.20
	case "gemini-3.1-flash-lite":
		return 0.25, 1.50
	case "gemini-2.5-flash":
		return 0.30, 2.50
	default:
		// Unknown custom models retain the former Flash estimate and should be
		// updated in DECISIONS.md before publishing benchmark cost results.
		return 0.10, 0.40
	}
}
