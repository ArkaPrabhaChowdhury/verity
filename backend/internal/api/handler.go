package api

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/arkop/verity/backend/internal/orchestrator"
	"github.com/arkop/verity/backend/internal/store"
)

type Handler struct {
	store          store.Repository
	engine         *orchestrator.Engine
	broker         *Broker
	allowedOrigins map[string]struct{}
	mu             sync.Mutex
	cancels        map[string]context.CancelFunc
	runSlots       chan struct{}
	apiToken       string
	createTimes    map[string][]time.Time
}

func NewHandler(repository store.Repository, engine *orchestrator.Engine, broker *Broker, allowedOrigins []string) http.Handler {
	maxActive, _ := strconv.Atoi(strings.TrimSpace(os.Getenv("VERITY_MAX_ACTIVE_RUNS")))
	if maxActive < 1 {
		maxActive = 2
	}
	h := &Handler{store: repository, engine: engine, broker: broker, allowedOrigins: make(map[string]struct{}), cancels: make(map[string]context.CancelFunc), runSlots: make(chan struct{}, maxActive), apiToken: strings.TrimSpace(os.Getenv("VERITY_API_TOKEN")), createTimes: make(map[string][]time.Time)}
	for _, origin := range allowedOrigins {
		origin = strings.TrimSpace(origin)
		if origin != "" {
			h.allowedOrigins[origin] = struct{}{}
		}
	}
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", h.health)
	mux.HandleFunc("GET /api/status", h.status)
	mux.HandleFunc("POST /api/runs", h.createRun)
	mux.HandleFunc("GET /api/runs", h.listRuns)
	mux.HandleFunc("GET /api/runs/{run_id}", h.getRun)
	mux.HandleFunc("GET /api/runs/{run_id}/events", h.getRunEvents)
	mux.HandleFunc("GET /api/runs/{run_id}/stream", h.streamRun)
	mux.HandleFunc("POST /api/runs/{run_id}/cancel", h.cancelRun)
	mux.HandleFunc("POST /api/runs/{run_id}/retry", h.retryRun)
	mux.HandleFunc("DELETE /api/runs/{run_id}", h.deleteRun)
	return h.cors(h.authenticate(mux))
}

func (h *Handler) health(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
}

func (h *Handler) status(w http.ResponseWriter, _ *http.Request) {
	h.mu.Lock()
	tracked := len(h.cancels)
	h.mu.Unlock()
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "active_runs": len(h.runSlots), "tracked_runs": tracked, "max_active_runs": cap(h.runSlots), "authentication_enabled": h.apiToken != ""})
}

func (h *Handler) createRun(w http.ResponseWriter, r *http.Request) {
	if !h.allowCreate(r) {
		writeError(w, http.StatusTooManyRequests, "research run rate limit exceeded; retry in a minute")
		return
	}
	var body struct {
		Question      string `json:"question"`
		ReplanEnabled *bool  `json:"replan_enabled,omitempty"`
	}
	decoder := json.NewDecoder(http.MaxBytesReader(w, r.Body, 64<<10))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "invalid JSON body")
		return
	}
	body.Question = strings.TrimSpace(body.Question)
	if len(body.Question) < 8 || len(body.Question) > 4000 {
		writeError(w, http.StatusBadRequest, "question must be between 8 and 4000 characters")
		return
	}
	replanEnabled := true
	if body.ReplanEnabled != nil {
		replanEnabled = *body.ReplanEnabled
	}
	run := &orchestrator.Run{ID: newID(), Question: body.Question, Status: orchestrator.RunQueued, CreatedAt: time.Now().UTC(), Metadata: orchestrator.RunMetadata{StageLatencyMS: make(map[string]int64)}, Options: orchestrator.RunOptions{ReplanEnabled: replanEnabled}}
	if err := h.store.CreateRun(r.Context(), run); err != nil {
		writeError(w, http.StatusInternalServerError, "could not create run")
		return
	}
	h.startRun(run)
	writeJSON(w, http.StatusAccepted, map[string]string{"run_id": run.ID})
}

func (h *Handler) startRun(run *orchestrator.Run) {
	ctx, cancel := context.WithCancel(context.Background())
	h.mu.Lock()
	h.cancels[run.ID] = cancel
	h.mu.Unlock()
	go func() {
		defer func() {
			h.mu.Lock()
			delete(h.cancels, run.ID)
			h.mu.Unlock()
		}()
		select {
		case h.runSlots <- struct{}{}:
			defer func() { <-h.runSlots }()
		case <-ctx.Done():
			h.markQueuedCancelled(run.ID)
			return
		}
		if h.engine != nil {
			h.engine.Run(ctx, run)
		}
	}()
}

func (h *Handler) markQueuedCancelled(runID string) {
	run, err := h.store.GetRun(context.Background(), runID)
	if err != nil || run.Status != orchestrator.RunQueued {
		return
	}
	now := time.Now().UTC()
	run.Status = orchestrator.RunCancelled
	run.Error = "Research run cancelled before execution."
	run.CompletedAt = &now
	_ = h.store.SaveRun(context.Background(), run)
	event := orchestrator.Event{RunID: runID, Type: "run_cancelled", Data: map[string]string{"error": run.Error}, CreatedAt: now}
	_ = h.store.AppendEvent(context.Background(), &event)
	h.broker.Publish(event)
}

func (h *Handler) getRun(w http.ResponseWriter, r *http.Request) {
	run, err := h.store.GetRun(r.Context(), r.PathValue("run_id"))
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "run not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not load run")
		return
	}
	writeJSON(w, http.StatusOK, run)
}

func (h *Handler) listRuns(w http.ResponseWriter, r *http.Request) {
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	runs, err := h.store.ListRuns(r.Context(), limit)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not list runs")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"runs": runs})
}

func (h *Handler) getRunEvents(w http.ResponseWriter, r *http.Request) {
	events, err := h.store.ListEvents(r.Context(), r.PathValue("run_id"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not load run events")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"events": events})
}

func (h *Handler) cancelRun(w http.ResponseWriter, r *http.Request) {
	runID := r.PathValue("run_id")
	run, err := h.store.GetRun(r.Context(), runID)
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "run not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not load run")
		return
	}
	if run.Status != orchestrator.RunQueued && run.Status != orchestrator.RunRunning {
		writeError(w, http.StatusConflict, "only queued or running research can be cancelled")
		return
	}
	h.mu.Lock()
	cancel := h.cancels[runID]
	h.mu.Unlock()
	if cancel != nil {
		cancel()
	}
	writeJSON(w, http.StatusAccepted, map[string]string{"status": "cancelling"})
}

func (h *Handler) retryRun(w http.ResponseWriter, r *http.Request) {
	original, err := h.store.GetRun(r.Context(), r.PathValue("run_id"))
	if errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "run not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "could not load run")
		return
	}
	run := &orchestrator.Run{ID: newID(), Question: original.Question, Status: orchestrator.RunQueued, CreatedAt: time.Now().UTC(), Metadata: orchestrator.RunMetadata{StageLatencyMS: make(map[string]int64)}, Options: original.Options}
	if err := h.store.CreateRun(r.Context(), run); err != nil {
		writeError(w, http.StatusInternalServerError, "could not retry run")
		return
	}
	h.startRun(run)
	writeJSON(w, http.StatusAccepted, map[string]string{"run_id": run.ID})
}

func (h *Handler) deleteRun(w http.ResponseWriter, r *http.Request) {
	runID := r.PathValue("run_id")
	h.mu.Lock()
	if cancel := h.cancels[runID]; cancel != nil {
		cancel()
	}
	delete(h.cancels, runID)
	h.mu.Unlock()
	if err := h.store.DeleteRun(r.Context(), runID); errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "run not found")
		return
	} else if err != nil {
		writeError(w, http.StatusInternalServerError, "could not delete run")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *Handler) streamRun(w http.ResponseWriter, r *http.Request) {
	runID := r.PathValue("run_id")
	if _, err := h.store.GetRun(r.Context(), runID); errors.Is(err, store.ErrNotFound) {
		writeError(w, http.StatusNotFound, "run not found")
		return
	}
	flusher, ok := w.(http.Flusher)
	if !ok {
		writeError(w, http.StatusInternalServerError, "streaming unsupported")
		return
	}
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache, no-transform")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("X-Accel-Buffering", "no")
	live, unsubscribe := h.broker.Subscribe(runID)
	defer unsubscribe()
	past, err := h.store.ListEvents(r.Context(), runID)
	if err != nil {
		return
	}
	lastSeq := int64(0)
	terminalReplayed := false
	for _, event := range past {
		writeSSE(w, event)
		lastSeq = event.Seq
		if event.Type == "report_completed" || event.Type == "run_failed" || event.Type == "run_cancelled" {
			terminalReplayed = true
		}
	}
	flusher.Flush()
	if terminalReplayed {
		return
	}
	ticker := time.NewTicker(15 * time.Second)
	defer ticker.Stop()
	for {
		select {
		case <-r.Context().Done():
			return
		case <-ticker.C:
			fmt.Fprint(w, ": keep-alive\n\n")
			flusher.Flush()
		case event := <-live:
			if event.Seq <= lastSeq {
				continue
			}
			writeSSE(w, event)
			lastSeq = event.Seq
			flusher.Flush()
			if event.Type == "report_completed" || event.Type == "run_failed" || event.Type == "run_cancelled" {
				return
			}
		}
	}
}

func writeSSE(w http.ResponseWriter, event orchestrator.Event) {
	raw, _ := json.Marshal(event.Data)
	fmt.Fprintf(w, "id: %d\nevent: %s\ndata: %s\n\n", event.Seq, event.Type, raw)
}

func (h *Handler) cors(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		origin := r.Header.Get("Origin")
		if _, allowed := h.allowedOrigins[origin]; allowed {
			w.Header().Set("Access-Control-Allow-Origin", origin)
			w.Header().Set("Vary", "Origin")
			w.Header().Set("Access-Control-Allow-Headers", "Content-Type, Authorization")
			w.Header().Set("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
		}
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusNoContent)
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (h *Handler) authenticate(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if h.apiToken != "" && r.URL.Query().Get("access_token") != h.apiToken && r.Header.Get("Authorization") != "Bearer "+h.apiToken {
			writeError(w, http.StatusUnauthorized, "authentication required")
			return
		}
		next.ServeHTTP(w, r)
	})
}

func (h *Handler) allowCreate(r *http.Request) bool {
	key := r.RemoteAddr
	if forwarded := strings.TrimSpace(r.Header.Get("X-Forwarded-For")); forwarded != "" {
		key = strings.TrimSpace(strings.Split(forwarded, ",")[0])
	}
	cutoff := time.Now().Add(-time.Minute)
	h.mu.Lock()
	defer h.mu.Unlock()
	recent := h.createTimes[key][:0]
	for _, created := range h.createTimes[key] {
		if created.After(cutoff) {
			recent = append(recent, created)
		}
	}
	if len(recent) >= 10 {
		h.createTimes[key] = recent
		return false
	}
	h.createTimes[key] = append(recent, time.Now())
	return true
}

func newID() string {
	bytes := make([]byte, 12)
	if _, err := rand.Read(bytes); err != nil {
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return hex.EncodeToString(bytes)
}

func writeJSON(w http.ResponseWriter, status int, value any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(value)
}

func writeError(w http.ResponseWriter, status int, message string) {
	writeJSON(w, status, map[string]string{"error": message})
}
