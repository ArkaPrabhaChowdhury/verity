package search

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
)

type Brave struct {
	apiKey string
	client *http.Client
}

func NewBrave(apiKey string, timeout time.Duration) *Brave {
	return &Brave{apiKey: apiKey, client: &http.Client{Timeout: timeout}}
}

func (b *Brave) Search(ctx context.Context, query string, maxResults int) ([]Result, error) {
	if b.apiKey == "" {
		return nil, fmt.Errorf("Brave Search provider is not configured")
	}
	if maxResults < 1 {
		maxResults = 5
	}
	endpoint := "https://api.search.brave.com/res/v1/web/search?q=" + url.QueryEscape(query) + "&count=" + strconv.Itoa(maxResults)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, endpoint, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("Accept", "application/json")
	req.Header.Set("X-Subscription-Token", b.apiKey)
	resp, err := b.client.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return nil, &HTTPError{StatusCode: resp.StatusCode}
	}
	var decoded struct {
		Web struct {
			Results []struct {
				Title       string `json:"title"`
				URL         string `json:"url"`
				Description string `json:"description"`
			} `json:"results"`
		} `json:"web"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&decoded); err != nil {
		return nil, fmt.Errorf("decode Brave response: %w", err)
	}
	results := make([]Result, 0, len(decoded.Web.Results))
	for _, item := range decoded.Web.Results {
		results = append(results, Result{Title: strings.TrimSpace(item.Title), URL: item.URL, Description: strings.TrimSpace(item.Description)})
	}
	return results, nil
}
