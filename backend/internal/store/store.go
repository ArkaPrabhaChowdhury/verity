package store

import (
	"context"

	"github.com/arkop/verity/backend/internal/orchestrator"
)

type Repository interface {
	CreateRun(context.Context, *orchestrator.Run) error
	SaveRun(context.Context, *orchestrator.Run) error
	GetRun(context.Context, string) (*orchestrator.Run, error)
	ListRuns(context.Context, int) ([]orchestrator.Run, error)
	AppendEvent(context.Context, *orchestrator.Event) error
	ListEvents(context.Context, string) ([]orchestrator.Event, error)
	DeleteRun(context.Context, string) error
	Close() error
}
