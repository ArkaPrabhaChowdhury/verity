package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/arkop/verity/backend/internal/orchestrator"
	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("run not found")

type SQLite struct{ db *sql.DB }

func Open(path string) (*SQLite, error) {
	db, err := sql.Open("sqlite", path)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(1)
	store := &SQLite{db: db}
	if err := store.migrate(context.Background()); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (s *SQLite) migrate(ctx context.Context) error {
	statements := []string{
		`PRAGMA foreign_keys=ON`,
		`PRAGMA journal_mode=WAL`,
		`PRAGMA busy_timeout=5000`,
		`CREATE TABLE IF NOT EXISTS runs (
			id TEXT PRIMARY KEY,
			question TEXT NOT NULL,
			status TEXT NOT NULL,
			record_json BLOB NOT NULL,
			created_at TEXT NOT NULL,
			updated_at TEXT NOT NULL
		)`,
		`CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC)`,
		`CREATE TABLE IF NOT EXISTS run_events (
			seq INTEGER PRIMARY KEY AUTOINCREMENT,
			run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
			type TEXT NOT NULL,
			data_json BLOB NOT NULL,
			created_at TEXT NOT NULL
		)`,
		`CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq)`,
	}
	for _, statement := range statements {
		if _, err := s.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("SQLite migration: %w", err)
		}
	}
	return nil
}

func (s *SQLite) Close() error { return s.db.Close() }

func (s *SQLite) CreateRun(ctx context.Context, run *orchestrator.Run) error {
	raw, err := json.Marshal(run)
	if err != nil {
		return err
	}
	now := time.Now().UTC().Format(time.RFC3339Nano)
	_, err = s.db.ExecContext(ctx, `INSERT INTO runs(id, question, status, record_json, created_at, updated_at) VALUES(?, ?, ?, ?, ?, ?)`, run.ID, run.Question, run.Status, raw, run.CreatedAt.Format(time.RFC3339Nano), now)
	return err
}

func (s *SQLite) SaveRun(ctx context.Context, run *orchestrator.Run) error {
	raw, err := json.Marshal(run)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `UPDATE runs SET question=?, status=?, record_json=?, updated_at=? WHERE id=?`, run.Question, run.Status, raw, time.Now().UTC().Format(time.RFC3339Nano), run.ID)
	return err
}

func (s *SQLite) GetRun(ctx context.Context, id string) (*orchestrator.Run, error) {
	var raw []byte
	if err := s.db.QueryRowContext(ctx, `SELECT record_json FROM runs WHERE id=?`, id).Scan(&raw); err != nil {
		if errors.Is(err, sql.ErrNoRows) {
			return nil, ErrNotFound
		}
		return nil, err
	}
	var run orchestrator.Run
	if err := json.Unmarshal(raw, &run); err != nil {
		return nil, err
	}
	return &run, nil
}

func (s *SQLite) ListRuns(ctx context.Context, limit int) ([]orchestrator.Run, error) {
	if limit < 1 || limit > 100 {
		limit = 20
	}
	rows, err := s.db.QueryContext(ctx, `SELECT record_json FROM runs ORDER BY created_at DESC LIMIT ?`, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	runs := make([]orchestrator.Run, 0)
	for rows.Next() {
		var raw []byte
		if err := rows.Scan(&raw); err != nil {
			return nil, err
		}
		var run orchestrator.Run
		if err := json.Unmarshal(raw, &run); err != nil {
			return nil, err
		}
		runs = append(runs, run)
	}
	return runs, rows.Err()
}

func (s *SQLite) AppendEvent(ctx context.Context, event *orchestrator.Event) error {
	raw, err := json.Marshal(event.Data)
	if err != nil {
		return err
	}
	result, err := s.db.ExecContext(ctx, `INSERT INTO run_events(run_id, type, data_json, created_at) VALUES(?, ?, ?, ?)`, event.RunID, event.Type, raw, event.CreatedAt.Format(time.RFC3339Nano))
	if err != nil {
		return err
	}
	event.Seq, _ = result.LastInsertId()
	return nil
}

func (s *SQLite) ListEvents(ctx context.Context, runID string) ([]orchestrator.Event, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT seq, type, data_json, created_at FROM run_events WHERE run_id=? ORDER BY seq`, runID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	events := make([]orchestrator.Event, 0)
	for rows.Next() {
		var event orchestrator.Event
		var raw []byte
		var created string
		if err := rows.Scan(&event.Seq, &event.Type, &raw, &created); err != nil {
			return nil, err
		}
		event.RunID = runID
		_ = json.Unmarshal(raw, &event.Data)
		event.CreatedAt, _ = time.Parse(time.RFC3339Nano, created)
		events = append(events, event)
	}
	return events, rows.Err()
}

func (s *SQLite) DeleteRun(ctx context.Context, id string) error {
	result, err := s.db.ExecContext(ctx, `DELETE FROM runs WHERE id=?`, id)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err == nil && count == 0 {
		return ErrNotFound
	}
	return err
}
