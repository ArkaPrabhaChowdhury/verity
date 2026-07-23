package orchestrator

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net"
	"strings"
	"time"

	"github.com/arkop/verity/backend/internal/providers/llm"
)

type transientError interface{ Transient() bool }
type retryDelayError interface{ RetryDelay() time.Duration }

func retryOnce[T any](ctx context.Context, fn func() (T, error)) (T, error) {
	return retryTransient(ctx, 2, fn)
}

func retryTransient[T any](ctx context.Context, maxAttempts int, fn func() (T, error)) (T, error) {
	if maxAttempts < 1 {
		maxAttempts = 1
	}
	var value T
	var err error
	for attempt := 1; attempt <= maxAttempts; attempt++ {
		value, err = fn()
		if err == nil || !isTransient(err) || attempt == maxAttempts {
			return value, err
		}
		delay := 500 * time.Millisecond
		var advised retryDelayError
		if errors.As(err, &advised) && advised.RetryDelay() > delay {
			delay = advised.RetryDelay()
		}
		timer := time.NewTimer(delay)
		select {
		case <-ctx.Done():
			timer.Stop()
			var zero T
			return zero, ctx.Err()
		case <-timer.C:
		}
	}
	return value, err
}

func isTransient(err error) bool {
	var marked transientError
	if errors.As(err, &marked) {
		return marked.Transient()
	}
	var netErr net.Error
	return errors.As(err, &netErr) && (netErr.Timeout() || netErr.Temporary())
}

func complete(ctx context.Context, provider llm.Provider, recorder usageRecorder, stage string, request llm.CompletionRequest) (llm.CompletionResponse, error) {
	return retryTransient(ctx, 4, func() (llm.CompletionResponse, error) {
		started := time.Now()
		response, err := provider.Complete(ctx, request)
		if err == nil {
			recorder.RecordLLM(stage, response, time.Since(started))
		}
		return response, err
	})
}

func structuredCompletion[T any](ctx context.Context, provider llm.Provider, recorder usageRecorder, stage string, systemPrompt, userPrompt string, validate func(T) error) (T, error) {
	var zero T
	request := llm.CompletionRequest{SystemPrompt: systemPrompt, Prompt: userPrompt, JSONMode: true, Temperature: 0.1, MaxTokens: structuredMaxTokens(stage)}
	response, err := complete(ctx, provider, recorder, stage, request)
	if err != nil {
		return zero, err
	}
	parse := func(content string) (T, error) {
		var value T
		content = stripCodeFence(content)
		if err := json.Unmarshal([]byte(content), &value); err != nil {
			return zero, err
		}
		if err := validate(value); err != nil {
			return zero, err
		}
		return value, nil
	}
	value, parseErr := parse(response.Content)
	if parseErr == nil {
		return value, nil
	}
	request.Prompt = fmt.Sprintf("%s\n\nYour previous response was invalid: %v. Return corrected JSON only.", userPrompt, parseErr)
	response, err = complete(ctx, provider, recorder, stage+"_json_retry", request)
	if err != nil {
		return zero, err
	}
	value, parseErr = parse(response.Content)
	if parseErr != nil {
		return zero, fmt.Errorf("structured response invalid after retry: %w", parseErr)
	}
	return value, nil
}

func structuredMaxTokens(stage string) int {
	switch stage {
	case "source_summarization":
		return 900
	case "critiquing":
		return 1_200
	default:
		return 1_000
	}
}

func stripCodeFence(value string) string {
	value = strings.TrimSpace(value)
	if strings.HasPrefix(value, "```") {
		value = strings.TrimPrefix(value, "```json")
		value = strings.TrimPrefix(value, "```")
		value = strings.TrimSuffix(value, "```")
	}
	return strings.TrimSpace(value)
}
