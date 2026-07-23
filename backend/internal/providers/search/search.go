package search

import "context"

type Result struct {
	Title       string `json:"title"`
	URL         string `json:"url"`
	Description string `json:"description"`
}

type Provider interface {
	Search(ctx context.Context, query string, maxResults int) ([]Result, error)
}
