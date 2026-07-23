package orchestrator

import (
	"sync"
	"time"

	"github.com/arkop/verity/backend/internal/extraction"
	"github.com/arkop/verity/backend/internal/providers/search"
)

type cachedSearch struct {
	results   []search.Result
	expiresAt time.Time
}

type cachedDocument struct {
	document  extraction.Document
	expiresAt time.Time
}

type EvidenceCache struct {
	mu        sync.RWMutex
	ttl       time.Duration
	searches  map[string]cachedSearch
	documents map[string]cachedDocument
}

func NewEvidenceCache(ttl time.Duration) *EvidenceCache {
	if ttl <= 0 {
		ttl = 30 * time.Minute
	}
	return &EvidenceCache{ttl: ttl, searches: make(map[string]cachedSearch), documents: make(map[string]cachedDocument)}
}

func (c *EvidenceCache) Search(key string) ([]search.Result, bool) {
	if c == nil {
		return nil, false
	}
	c.mu.RLock()
	item, ok := c.searches[key]
	c.mu.RUnlock()
	if !ok || time.Now().After(item.expiresAt) {
		return nil, false
	}
	return append([]search.Result(nil), item.results...), true
}

func (c *EvidenceCache) StoreSearch(key string, results []search.Result) {
	if c == nil {
		return
	}
	c.mu.Lock()
	c.searches[key] = cachedSearch{results: append([]search.Result(nil), results...), expiresAt: time.Now().Add(c.ttl)}
	c.mu.Unlock()
}

func (c *EvidenceCache) Document(url string) (extraction.Document, bool) {
	if c == nil {
		return extraction.Document{}, false
	}
	c.mu.RLock()
	item, ok := c.documents[url]
	c.mu.RUnlock()
	if !ok || time.Now().After(item.expiresAt) {
		return extraction.Document{}, false
	}
	return item.document, true
}

func (c *EvidenceCache) StoreDocument(url string, document extraction.Document) {
	if c == nil {
		return
	}
	c.mu.Lock()
	c.documents[url] = cachedDocument{document: document, expiresAt: time.Now().Add(c.ttl)}
	c.mu.Unlock()
}
