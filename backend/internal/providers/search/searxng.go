package search

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// SearXNG uses the instance's JSON search API. Verity's Docker Compose stack
// provides a private, keyless instance by default.
type SearXNG struct {
	baseURL string
	client  *http.Client
}

func NewSearXNG(baseURL string, timeout time.Duration) *SearXNG {
	return &SearXNG{
		baseURL: strings.TrimRight(strings.TrimSpace(baseURL), "/"),
		client:  &http.Client{Timeout: timeout},
	}
}

func (s *SearXNG) Search(ctx context.Context, query string, maxResults int) ([]Result, error) {
	if s.baseURL == "" {
		return nil, fmt.Errorf("SearXNG provider is not configured")
	}
	if maxResults < 1 {
		maxResults = 5
	}

	params := url.Values{}
	params.Set("q", query)
	params.Set("format", "json")
	params.Set("categories", "general")
	params.Set("language", "en")
	params.Set("safesearch", "1")
	endpoint := s.baseURL + "/search?" + params.Encode()
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("User-Agent", "Verity/1.0")

	resp, err := s.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &HTTPError{StatusCode: resp.StatusCode}
	}

	var decoded struct {
		Results []struct {
			Title   string `json:"title"`
			URL     string `json:"url"`
			Content string `json:"content"`
		} `json:"results"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&decoded); err != nil {
		return nil, fmt.Errorf("decode SearXNG response: %w", err)
	}

	results := make([]Result, 0, min(maxResults, len(decoded.Results)))
	seen := make(map[string]struct{}, len(decoded.Results))
	for _, item := range decoded.Results {
		itemURL := strings.TrimSpace(item.URL)
		if itemURL == "" {
			continue
		}
		parsed, err := url.Parse(itemURL)
		if err != nil || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
			continue
		}
		if _, exists := seen[itemURL]; exists {
			continue
		}
		seen[itemURL] = struct{}{}
		results = append(results, Result{
			Title:       strings.TrimSpace(item.Title),
			URL:         itemURL,
			Description: strings.TrimSpace(item.Content),
		})
		if len(results) == maxResults {
			break
		}
	}
	if len(results) == 0 {
		return nil, fmt.Errorf("SearXNG returned no usable results for %q (requested %d)", query, maxResults)
	}
	return results, nil
}
