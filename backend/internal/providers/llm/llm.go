package llm

import (
	"context"
	"errors"
)

var ErrNotConfigured = errors.New("LLM provider is not configured")

type CompletionRequest struct {
	SystemPrompt string
	Prompt       string
	JSONMode     bool
	Temperature  float64
	MaxTokens    int
}

type Usage struct {
	PromptTokens     int     `json:"prompt_tokens"`
	CompletionTokens int     `json:"completion_tokens"`
	TotalTokens      int     `json:"total_tokens"`
	EstimatedCostUSD float64 `json:"estimated_cost_usd"`
}

type CompletionResponse struct {
	Content  string `json:"content"`
	Provider string `json:"provider"`
	Model    string `json:"model"`
	Usage    Usage  `json:"usage"`
}

type Provider interface {
	Complete(ctx context.Context, req CompletionRequest) (CompletionResponse, error)
}

type Unavailable struct{}

func (Unavailable) Complete(context.Context, CompletionRequest) (CompletionResponse, error) {
	return CompletionResponse{}, ErrNotConfigured
}
