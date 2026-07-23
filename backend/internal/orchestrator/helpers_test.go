package orchestrator

import (
	"context"
	"errors"
	"testing"
	"time"
)

type delayedTransientError struct{ delay time.Duration }

func (e delayedTransientError) Error() string             { return "retry later" }
func (e delayedTransientError) Transient() bool           { return true }
func (e delayedTransientError) RetryDelay() time.Duration { return e.delay }

func TestRetryOnceHonorsProviderDelay(t *testing.T) {
	attempts := 0
	started := time.Now()
	value, err := retryOnce(context.Background(), func() (string, error) {
		attempts++
		if attempts == 1 {
			return "", delayedTransientError{delay: 20 * time.Millisecond}
		}
		return "ok", nil
	})
	if err != nil {
		t.Fatal(err)
	}
	if value != "ok" || attempts != 2 {
		t.Fatalf("value = %q, attempts = %d", value, attempts)
	}
	if elapsed := time.Since(started); elapsed < 20*time.Millisecond {
		t.Fatalf("retry occurred too soon: %v", elapsed)
	}
}

func TestRetryOnceStopsWhenContextExpiresBeforeDelay(t *testing.T) {
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Millisecond)
	defer cancel()
	_, err := retryOnce(ctx, func() (string, error) {
		return "", delayedTransientError{delay: time.Second}
	})
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("error = %v", err)
	}
}

func TestRetryTransientUsesConfiguredAttemptLimit(t *testing.T) {
	attempts := 0
	_, err := retryTransient(context.Background(), 4, func() (string, error) {
		attempts++
		return "", delayedTransientError{delay: time.Millisecond}
	})
	if err == nil {
		t.Fatal("expected transient error")
	}
	if attempts != 4 {
		t.Fatalf("attempts = %d", attempts)
	}
}
