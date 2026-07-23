package llm

import (
	"context"
	"errors"
	"testing"
)

type providerFunc func(context.Context, CompletionRequest) (CompletionResponse, error)

func (fn providerFunc) Complete(ctx context.Context, req CompletionRequest) (CompletionResponse, error) {
	return fn(ctx, req)
}

func TestFallbackPreservesPrimaryErrorWhenSecondaryIsUnconfigured(t *testing.T) {
	primaryErr := &HTTPError{StatusCode: 429, Body: "rate limited"}
	provider := Fallback{
		Primary: providerFunc(func(context.Context, CompletionRequest) (CompletionResponse, error) {
			return CompletionResponse{}, primaryErr
		}),
		Secondary: Unavailable{},
	}

	_, err := provider.Complete(context.Background(), CompletionRequest{})
	if !errors.Is(err, primaryErr) {
		t.Fatalf("error = %v, want primary error", err)
	}
}

func TestFallbackUsesConfiguredSecondary(t *testing.T) {
	provider := Fallback{
		Primary: providerFunc(func(context.Context, CompletionRequest) (CompletionResponse, error) {
			return CompletionResponse{}, &HTTPError{StatusCode: 429}
		}),
		Secondary: providerFunc(func(context.Context, CompletionRequest) (CompletionResponse, error) {
			return CompletionResponse{Content: "fallback", Provider: "secondary"}, nil
		}),
	}

	response, err := provider.Complete(context.Background(), CompletionRequest{})
	if err != nil {
		t.Fatal(err)
	}
	if response.Provider != "secondary" {
		t.Fatalf("provider = %q", response.Provider)
	}
}
