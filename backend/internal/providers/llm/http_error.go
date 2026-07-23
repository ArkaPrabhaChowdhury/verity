package llm

import (
	"fmt"
	"time"
)

type HTTPError struct {
	StatusCode int
	Body       string
	RetryAfter time.Duration
}

func (e *HTTPError) Error() string {
	return fmt.Sprintf("provider HTTP %d: %s", e.StatusCode, e.Body)
}

func (e *HTTPError) Transient() bool {
	return e.StatusCode == 408 || e.StatusCode == 429 || e.StatusCode >= 500
}

func (e *HTTPError) RetryDelay() time.Duration { return e.RetryAfter }
