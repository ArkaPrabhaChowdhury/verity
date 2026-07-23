package store

import (
	"context"
	"path/filepath"
	"testing"
	"time"

	"github.com/arkop/verity/backend/internal/orchestrator"
)

func TestRunAndEventRoundTrip(t *testing.T) {
	repository, err := Open(filepath.Join(t.TempDir(), "verity.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	run := &orchestrator.Run{ID: "run-1", Question: "A sufficiently long question?", Status: orchestrator.RunQueued, CreatedAt: time.Now().UTC(), Metadata: orchestrator.RunMetadata{StageLatencyMS: map[string]int64{}}}
	if err := repository.CreateRun(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	event := &orchestrator.Event{RunID: run.ID, Type: "plan_created", Data: map[string]string{"ok": "yes"}, CreatedAt: time.Now().UTC()}
	if err := repository.AppendEvent(context.Background(), event); err != nil {
		t.Fatal(err)
	}
	loaded, err := repository.GetRun(context.Background(), run.ID)
	if err != nil || loaded.Question != run.Question {
		t.Fatalf("loaded run = %#v, err = %v", loaded, err)
	}
	events, err := repository.ListEvents(context.Background(), run.ID)
	if err != nil || len(events) != 1 || events[0].Seq == 0 {
		t.Fatalf("events = %#v, err = %v", events, err)
	}
}

func TestDeleteRunCascadesEvents(t *testing.T) {
	repository, err := Open(filepath.Join(t.TempDir(), "verity.db"))
	if err != nil {
		t.Fatal(err)
	}
	defer repository.Close()
	run := &orchestrator.Run{ID: "delete-me", Question: "Which run should be deleted from the test store?", Status: orchestrator.RunCompleted, CreatedAt: time.Now().UTC()}
	if err := repository.CreateRun(context.Background(), run); err != nil {
		t.Fatal(err)
	}
	if err := repository.AppendEvent(context.Background(), &orchestrator.Event{RunID: run.ID, Type: "report_completed", Data: map[string]string{"ok": "yes"}, CreatedAt: time.Now().UTC()}); err != nil {
		t.Fatal(err)
	}
	if err := repository.DeleteRun(context.Background(), run.ID); err != nil {
		t.Fatal(err)
	}
	if _, err := repository.GetRun(context.Background(), run.ID); err != ErrNotFound {
		t.Fatalf("GetRun error = %v", err)
	}
	events, err := repository.ListEvents(context.Background(), run.ID)
	if err != nil || len(events) != 0 {
		t.Fatalf("events = %#v, err = %v", events, err)
	}
}
