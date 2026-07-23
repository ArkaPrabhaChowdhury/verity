package search

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func TestSearXNGSearch(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/search" {
			t.Fatalf("path = %q", r.URL.Path)
		}
		if r.URL.Query().Get("q") != "multi hop question" || r.URL.Query().Get("format") != "json" {
			t.Fatalf("query = %q", r.URL.RawQuery)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"results":[{"title":" One ","url":"https://example.com/one","content":" First result "},{"title":"Duplicate","url":"https://example.com/one","content":"duplicate"},{"title":"Bad","url":"javascript:alert(1)","content":"bad"},{"title":"Two","url":"https://example.org/two","content":"Second result"}]}`))
	}))
	defer server.Close()

	provider := NewSearXNG(server.URL, time.Second)
	results, err := provider.Search(context.Background(), "multi hop question", 2)
	if err != nil {
		t.Fatal(err)
	}
	if len(results) != 2 {
		t.Fatalf("len(results) = %d", len(results))
	}
	if results[0].Title != "One" || results[0].Description != "First result" {
		t.Fatalf("first result = %#v", results[0])
	}
}

func TestSearXNGSearchHTTPError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTooManyRequests)
	}))
	defer server.Close()

	_, err := NewSearXNG(server.URL, time.Second).Search(context.Background(), "question", 5)
	httpErr, ok := err.(*HTTPError)
	if !ok || !httpErr.Transient() {
		t.Fatalf("error = %#v", err)
	}
}
