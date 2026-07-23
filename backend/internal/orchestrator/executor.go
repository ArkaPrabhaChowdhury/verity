package orchestrator

import (
	"context"
	"fmt"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/arkop/verity/backend/internal/extraction"
	"github.com/arkop/verity/backend/internal/providers/llm"
	"github.com/arkop/verity/backend/internal/providers/search"
)

type pageFetcher interface {
	Fetch(ctx context.Context, rawURL string) (extraction.Document, error)
}

type Executor struct {
	LLM                llm.Provider
	Search             search.Provider
	Extractor          pageFetcher
	Concurrency        int
	TaskTimeout        time.Duration
	MaxResults         int
	SearchCostPerQuery float64
	Cache              *EvidenceCache
}

func (e Executor) Execute(ctx context.Context, runID string, plan Plan, recorder usageRecorder, onFinding func(Finding), emit func(string, any)) []Finding {
	workers := e.Concurrency
	if workers <= 0 {
		workers = 4
	}
	results := make([]Finding, len(plan.SubQuestions))
	jobs := make(chan int)
	var wg sync.WaitGroup
	for worker := 0; worker < workers; worker++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for index := range jobs {
				sub := plan.SubQuestions[index]
				emit("subquestion_started", sub)
				results[index] = e.executeOne(ctx, sub, recorder)
				if onFinding != nil {
					onFinding(results[index])
				}
				if results[index].Status == FindingFailed {
					emit("subquestion_failed", results[index])
				} else {
					emit("subquestion_completed", results[index])
				}
			}
		}()
	}
	for index := range plan.SubQuestions {
		select {
		case <-ctx.Done():
			results[index] = Finding{SubQuestionID: plan.SubQuestions[index].ID, Question: plan.SubQuestions[index].Question, Status: FindingFailed, Error: ctx.Err().Error(), Round: plan.Round}
		case jobs <- index:
		}
	}
	close(jobs)
	wg.Wait()
	return results
}

func (e Executor) executeOne(parent context.Context, sub SubQuestion, recorder usageRecorder) Finding {
	started := time.Now()
	timeout := e.TaskTimeout
	if timeout <= 0 {
		timeout = 60 * time.Second
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	maxResults := e.MaxResults
	if maxResults <= 0 {
		maxResults = 5
	}
	query := effectiveSearchQuery(sub)
	cacheKey := fmt.Sprintf("%s|%d", query, maxResults)
	results, err := retryOnce(ctx, func() ([]search.Result, error) {
		if cached, ok := e.Cache.Search(cacheKey); ok {
			return cached, nil
		}
		recorder.RecordSearch(e.SearchCostPerQuery)
		found, searchErr := e.Search.Search(ctx, query, maxResults)
		if searchErr == nil {
			e.Cache.StoreSearch(cacheKey, found)
		}
		return found, searchErr
	})
	if err != nil {
		return Finding{SubQuestionID: sub.ID, Question: sub.Question, Status: FindingFailed, Error: err.Error(), DurationMS: time.Since(started).Milliseconds(), Round: sub.Round}
	}
	if len(results) == 0 {
		return Finding{SubQuestionID: sub.ID, Question: sub.Question, Status: FindingFailed, Error: "search returned no results", DurationMS: time.Since(started).Milliseconds(), Round: sub.Round}
	}

	type pageResult struct {
		document    extraction.Document
		title       string
		fetchFailed bool
		err         error
	}
	pageResults := make(chan pageResult, len(results))
	var wg sync.WaitGroup
	for _, item := range results {
		item := item
		wg.Add(1)
		go func() {
			defer wg.Done()
			doc, fetchErr := retryOnce(ctx, func() (extraction.Document, error) {
				if cached, ok := e.Cache.Document(item.URL); ok {
					return cached, nil
				}
				fetched, err := e.Extractor.Fetch(ctx, item.URL)
				if err == nil {
					e.Cache.StoreDocument(item.URL, fetched)
				}
				return fetched, err
			})
			if fetchErr != nil {
				snippet := strings.TrimSpace(item.Description)
				if len([]rune(snippet)) >= 60 {
					pageResults <- pageResult{
						document:    extraction.Document{URL: item.URL, Title: item.Title, Text: "Search result excerpt: " + snippet},
						title:       item.Title,
						fetchFailed: true,
					}
					return
				}
				pageResults <- pageResult{fetchFailed: true, err: fetchErr}
				return
			}
			if snippet := strings.TrimSpace(item.Description); snippet != "" {
				doc.Text = "Search result excerpt: " + snippet + "\n\nFetched page content:\n" + doc.Text
			}
			pageResults <- pageResult{document: doc, title: firstNonEmpty(doc.Title, item.Title)}
		}()
	}
	go func() { wg.Wait(); close(pageResults) }()

	finding := Finding{SubQuestionID: sub.ID, Question: sub.Question, Round: sub.Round}
	directFetchFailures := 0
	documents := make([]extraction.Document, 0, len(results))
	titles := make(map[string]string)
	for result := range pageResults {
		if result.fetchFailed {
			directFetchFailures++
		}
		if result.err != nil {
			continue
		}
		documents = append(documents, result.document)
		titles[result.document.URL] = result.title
	}
	if len(documents) > 0 {
		evidence, summaryErr := e.summarizeSources(ctx, sub, documents, titles, recorder)
		if summaryErr != nil {
			finding.Status = FindingFailed
			finding.Error = summaryErr.Error()
			finding.DurationMS = time.Since(started).Milliseconds()
			return finding
		}
		finding.Sources = evidence
	}
	rejectedDocuments := len(documents) - len(finding.Sources)
	finding.DurationMS = time.Since(started).Milliseconds()
	if len(finding.Sources) == 0 {
		finding.Status = FindingFailed
		if ctx.Err() != nil {
			finding.Error = ctx.Err().Error()
		} else {
			finding.Error = fmt.Sprintf("no usable evidence: %d direct fetches failed; %d fetched or snippet documents were irrelevant or unsupported", directFetchFailures, rejectedDocuments)
		}
	} else if len(finding.Sources) < 2 || directFetchFailures > 0 || rejectedDocuments > 0 {
		finding.Status = FindingPartial
		finding.Error = fmt.Sprintf("%d of %d sources produced usable evidence; %d direct fetches used snippets or failed", len(finding.Sources), len(results), directFetchFailures)
	} else {
		finding.Status = FindingSuccess
	}
	return finding
}

func effectiveSearchQuery(sub SubQuestion) string {
	if query := strings.TrimSpace(sub.SearchQuery); query != "" {
		return query
	}
	return strings.TrimSpace(strings.TrimSuffix(sub.Question, "?"))
}

type sourceSummaryResponse struct {
	Sources []struct {
		URL     string `json:"url"`
		Summary string `json:"summary"`
	} `json:"sources"`
}

func (e Executor) summarizeSources(ctx context.Context, sub SubQuestion, documents []extraction.Document, titles map[string]string, recorder usageRecorder) ([]SourceEvidence, error) {
	var promptBuilder strings.Builder
	fmt.Fprintf(&promptBuilder, "Sub-question:\n%s\n\nPages:\n", sub.Question)
	allowed := make(map[string]struct{}, len(documents))
	documentsByURL := make(map[string]extraction.Document, len(documents))
	for index, document := range documents {
		allowed[document.URL] = struct{}{}
		documentsByURL[document.URL] = document
		fmt.Fprintf(&promptBuilder, "\n--- PAGE %d ---\nURL: %s\nTitle: %s\nText:\n%s\n", index+1, document.URL, document.Title, document.Text)
	}
	response, err := structuredCompletion(ctx, e.LLM, recorder, "source_summarization", prompt("source_summary_v1"), promptBuilder.String(), func(value sourceSummaryResponse) error {
		for _, source := range value.Sources {
			if _, ok := allowed[source.URL]; !ok {
				return fmt.Errorf("summary returned unknown source URL %q", source.URL)
			}
			if strings.TrimSpace(source.Summary) == "" {
				return fmt.Errorf("summary is empty for %s", source.URL)
			}
		}
		return nil
	})
	if err != nil {
		return nil, err
	}
	evidence := make([]SourceEvidence, 0, len(response.Sources))
	seen := make(map[string]struct{})
	for _, source := range response.Sources {
		if _, duplicate := seen[source.URL]; duplicate {
			continue
		}
		seen[source.URL] = struct{}{}
		document := documentsByURL[source.URL]
		domain := sourceDomain(source.URL)
		sourceType, quality := classifySource(domain)
		evidence = append(evidence, SourceEvidence{
			Title:        firstNonEmpty(titles[source.URL], source.URL),
			URL:          source.URL,
			Domain:       domain,
			Summary:      strings.TrimSpace(source.Summary),
			Excerpt:      compactExcerpt(document.Text, 360),
			SourceType:   sourceType,
			QualityScore: quality,
			FetchedAt:    time.Now().UTC(),
		})
	}
	return evidence, nil
}

func sourceDomain(rawURL string) string {
	parsed, err := url.Parse(rawURL)
	if err != nil {
		return "unknown"
	}
	return strings.TrimPrefix(strings.ToLower(parsed.Hostname()), "www.")
}

func classifySource(domain string) (string, int) {
	switch {
	case strings.HasSuffix(domain, ".gov"), strings.HasSuffix(domain, ".gov.uk"), strings.HasSuffix(domain, ".europa.eu"):
		return "government", 95
	case strings.HasSuffix(domain, ".edu"), strings.Contains(domain, "nature.com"), strings.Contains(domain, "sciencedirect.com"):
		return "research", 90
	case strings.Contains(domain, "reuters.com"), strings.Contains(domain, "apnews.com"), strings.Contains(domain, "bbc."):
		return "news", 80
	case strings.Contains(domain, "wikipedia.org"), strings.Contains(domain, "medium.com"), strings.Contains(domain, "blog"):
		return "secondary", 55
	default:
		return "web", 65
	}
}

func compactExcerpt(value string, limit int) string {
	value = strings.Join(strings.Fields(value), " ")
	runes := []rune(value)
	if len(runes) <= limit {
		return value
	}
	return strings.TrimSpace(string(runes[:limit])) + "…"
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		if strings.TrimSpace(value) != "" {
			return strings.TrimSpace(value)
		}
	}
	return "Untitled source"
}
