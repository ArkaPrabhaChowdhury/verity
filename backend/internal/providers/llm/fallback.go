package llm

import (
	"context"
	"errors"
	"fmt"
)

type Fallback struct {
	Primary   Provider
	Secondary Provider
}

func (f Fallback) Complete(ctx context.Context, req CompletionRequest) (CompletionResponse, error) {
	primary := f.Primary
	if primary == nil {
		primary = Unavailable{}
	}
	resp, err := primary.Complete(ctx, req)
	if err == nil {
		return resp, nil
	}
	if !shouldFallback(err) || f.Secondary == nil {
		return CompletionResponse{}, err
	}
	secondaryResp, secondaryErr := f.Secondary.Complete(ctx, req)
	if secondaryErr == nil {
		return secondaryResp, nil
	}
	if errors.Is(secondaryErr, ErrNotConfigured) {
		return CompletionResponse{}, err
	}
	return CompletionResponse{}, fmt.Errorf("primary provider failed: %v; fallback provider failed: %w", err, secondaryErr)
}

func shouldFallback(err error) bool {
	if errors.Is(err, ErrNotConfigured) {
		return true
	}
	var httpErr *HTTPError
	return errors.As(err, &httpErr) && (httpErr.StatusCode == 429 || httpErr.StatusCode >= 500)
}
