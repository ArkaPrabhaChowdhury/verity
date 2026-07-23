package main

import (
	"context"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/arkop/verity/backend/internal/api"
	"github.com/arkop/verity/backend/internal/extraction"
	"github.com/arkop/verity/backend/internal/orchestrator"
	"github.com/arkop/verity/backend/internal/providers/llm"
	"github.com/arkop/verity/backend/internal/providers/search"
	"github.com/arkop/verity/backend/internal/store"
)

func main() {
	dbPath := env("VERITY_DB_PATH", "./data/verity.db")
	if err := os.MkdirAll(filepath.Dir(dbPath), 0o755); err != nil {
		log.Fatal(err)
	}
	var repository store.Repository
	var err error
	if dsn := strings.TrimSpace(os.Getenv("VERITY_DATABASE_URL")); dsn != "" {
		repository, err = store.OpenPostgres(context.Background(), dsn)
	} else {
		repository, err = store.Open(dbPath)
	}
	if err != nil {
		log.Fatal(err)
	}
	defer repository.Close()

	groq := llm.NewGroq(os.Getenv("GROQ_API_KEY"), env("GROQ_MODEL", "llama-3.1-8b-instant"), 30*time.Second)
	gemini := llm.NewGemini(os.Getenv("GEMINI_API_KEY"), env("GEMINI_MODEL", "gemini-3.5-flash"), 30*time.Second)
	model := llm.Fallback{Primary: groq, Secondary: gemini}
	searchProvider, defaultSearchCost, err := configuredSearchProvider()
	if err != nil {
		log.Fatal(err)
	}
	pageExtractor := extraction.New(8*time.Second, 800)
	concurrency, _ := strconv.Atoi(env("VERITY_CONCURRENCY", "1"))
	searchCostPerQuery, err := strconv.ParseFloat(env("VERITY_SEARCH_COST_PER_QUERY", defaultSearchCost), 64)
	if err != nil {
		log.Fatalf("invalid VERITY_SEARCH_COST_PER_QUERY: %v", err)
	}

	broker := api.NewBroker()
	engine := &orchestrator.Engine{
		Planner:    orchestrator.Planner{LLM: model},
		Executor:   orchestrator.Executor{LLM: model, Search: searchProvider, Extractor: pageExtractor, Concurrency: concurrency, TaskTimeout: 60 * time.Second, MaxResults: 4, SearchCostPerQuery: searchCostPerQuery, Cache: orchestrator.NewEvidenceCache(30 * time.Minute)},
		Critic:     orchestrator.Critic{LLM: model},
		Writer:     orchestrator.Writer{LLM: model},
		Repository: repository,
		Events:     broker,
	}
	handler := api.NewHandler(repository, engine, broker, strings.Split(env("VERITY_ALLOWED_ORIGINS", "http://localhost:3000"), ","))
	server := &http.Server{Addr: env("VERITY_ADDR", ":8080"), Handler: handler, ReadHeaderTimeout: 5 * time.Second, IdleTimeout: 60 * time.Second}

	go func() {
		log.Printf("Verity API listening on %s", server.Addr)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	_ = server.Shutdown(ctx)
}

func env(name, fallback string) string {
	if value := strings.TrimSpace(os.Getenv(name)); value != "" {
		return value
	}
	return fallback
}

func configuredSearchProvider() (search.Provider, string, error) {
	switch strings.ToLower(env("VERITY_SEARCH_PROVIDER", "searxng")) {
	case "searxng":
		return search.NewSearXNG(env("SEARXNG_URL", "http://localhost:8888"), 10*time.Second), "0", nil
	case "brave":
		return search.NewBrave(os.Getenv("BRAVE_SEARCH_API_KEY"), 10*time.Second), "0.005", nil
	default:
		return nil, "", fmt.Errorf("unsupported VERITY_SEARCH_PROVIDER; use searxng or brave")
	}
}
