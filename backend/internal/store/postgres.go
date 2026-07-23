package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/arkop/verity/backend/internal/orchestrator"
	_ "github.com/jackc/pgx/v5/stdlib"
)

type Postgres struct{ db *sql.DB }

func OpenPostgres(ctx context.Context, dsn string) (*Postgres, error) {
	db, err := sql.Open("pgx", dsn)
	if err != nil {
		return nil, err
	}
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(3)
	store := &Postgres{db: db}
	if err := store.migrate(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return store, nil
}

func (s *Postgres) migrate(ctx context.Context) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, question TEXT NOT NULL, status TEXT NOT NULL, record_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL, updated_at TIMESTAMPTZ NOT NULL)`,
		`CREATE INDEX IF NOT EXISTS idx_runs_created_at ON runs(created_at DESC)`,
		`CREATE TABLE IF NOT EXISTS run_events (seq BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE, type TEXT NOT NULL, data_json JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL)`,
		`CREATE INDEX IF NOT EXISTS idx_run_events_run_seq ON run_events(run_id, seq)`,
	}
	for _, statement := range statements {
		if _, err := s.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("Postgres migration: %w", err)
		}
	}
	return nil
}
func (s *Postgres) Close() error { return s.db.Close() }
func (s *Postgres) CreateRun(ctx context.Context, run *orchestrator.Run) error {
	raw, err := json.Marshal(run)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO runs(id, question, status, record_json, created_at, updated_at) VALUES($1,$2,$3,$4,$5,$6)`, run.ID, run.Question, run.Status, raw, run.CreatedAt, time.Now().UTC())
	return err
}
func (s *Postgres) SaveRun(ctx context.Context, run *orchestrator.Run) error {
	raw, err := json.Marshal(run)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `UPDATE runs SET question=$1,status=$2,record_json=$3,updated_at=$4 WHERE id=$5`, run.Question, run.Status, raw, time.Now().UTC(), run.ID)
	return err
}
func (s *Postgres) GetRun(ctx context.Context, id string) (*orchestrator.Run, error) {
	var raw []byte
	if err := s.db.QueryRowContext(ctx, `SELECT record_json FROM runs WHERE id=$1`, id).Scan(&raw); err != nil {
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
func (s *Postgres) ListRuns(ctx context.Context, limit int) ([]orchestrator.Run, error) {
	if limit < 1 || limit > 100 {
		limit = 20
	}
	rows, err := s.db.QueryContext(ctx, `SELECT record_json FROM runs ORDER BY created_at DESC LIMIT $1`, limit)
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
func (s *Postgres) AppendEvent(ctx context.Context, event *orchestrator.Event) error {
	raw, err := json.Marshal(event.Data)
	if err != nil {
		return err
	}
	return s.db.QueryRowContext(ctx, `INSERT INTO run_events(run_id,type,data_json,created_at) VALUES($1,$2,$3,$4) RETURNING seq`, event.RunID, event.Type, raw, event.CreatedAt).Scan(&event.Seq)
}
func (s *Postgres) ListEvents(ctx context.Context, runID string) ([]orchestrator.Event, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT seq,type,data_json,created_at FROM run_events WHERE run_id=$1 ORDER BY seq`, runID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	events := make([]orchestrator.Event, 0)
	for rows.Next() {
		var event orchestrator.Event
		var raw []byte
		if err := rows.Scan(&event.Seq, &event.Type, &raw, &event.CreatedAt); err != nil {
			return nil, err
		}
		event.RunID = runID
		_ = json.Unmarshal(raw, &event.Data)
		events = append(events, event)
	}
	return events, rows.Err()
}
func (s *Postgres) DeleteRun(ctx context.Context, id string) error {
	result, err := s.db.ExecContext(ctx, `DELETE FROM runs WHERE id=$1`, id)
	if err != nil {
		return err
	}
	count, err := result.RowsAffected()
	if err == nil && count == 0 {
		return ErrNotFound
	}
	return err
}
