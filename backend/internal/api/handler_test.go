package api

import (
	"context"
	"net/http"
	"net/http/httptest"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/arkop/verity/backend/internal/orchestrator"
	"github.com/arkop/verity/backend/internal/store"
)

func TestCompletedRunStreamReplaysAndCloses(t *testing.T) {
	repository, err := store.Open(filepath.Join(t.TempDir(), "verity.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	run := &orchestrator.Run{ID: "done", Question: "Which completed run is used for this test?", Status: orchestrator.RunCompleted, CreatedAt: time.Now().UTC(), Options: orchestrator.RunOptions{ReplanEnabled: true}}
	if err := repository.CreateRun(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	event := &orchestrator.Event{RunID: run.ID, Type: "report_completed", Data: map[string]string{"report": "done"}, CreatedAt: time.Now().UTC()}
	if err := repository.AppendEvent(context.Background(), event); err != nil {
		t.Fatal(err)
	}

	handler := NewHandler(repository, nil, NewBroker(), nil)
	request := httptest.NewRequest(http.MethodGet, "/api/runs/done/stream", nil)
	response := httptest.NewRecorder()
	handler.ServeHTTP(response, request)
	if response.Code != http.StatusOK {
		t.Fatalf("status = %d", response.Code)
	}
	if !strings.Contains(response.Body.String(), "event: report_completed") {
		t.Fatalf("stream body = %q", response.Body.String())
	}
}
