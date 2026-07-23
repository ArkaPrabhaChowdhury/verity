package search

import "fmt"

type HTTPError struct{ StatusCode int }

func (e *HTTPError) Error() string { return fmt.Sprintf("search HTTP %d", e.StatusCode) }
func (e *HTTPError) Transient() bool {
	return e.StatusCode == 408 || e.StatusCode == 429 || e.StatusCode >= 500
}
