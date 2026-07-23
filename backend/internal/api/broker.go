package api

import (
	"sync"

	"github.com/arkop/verity/backend/internal/orchestrator"
)

type Broker struct {
	mu          sync.RWMutex
	subscribers map[string]map[chan orchestrator.Event]struct{}
}

func NewBroker() *Broker {
	return &Broker{subscribers: make(map[string]map[chan orchestrator.Event]struct{})}
}

func (b *Broker) Publish(event orchestrator.Event) {
	b.mu.RLock()
	defer b.mu.RUnlock()
	for channel := range b.subscribers[event.RunID] {
		select {
		case channel <- event:
		default:
		}
	}
}

func (b *Broker) Subscribe(runID string) (<-chan orchestrator.Event, func()) {
	channel := make(chan orchestrator.Event, 64)
	b.mu.Lock()
	if b.subscribers[runID] == nil {
		b.subscribers[runID] = make(map[chan orchestrator.Event]struct{})
	}
	b.subscribers[runID][channel] = struct{}{}
	b.mu.Unlock()
	return channel, func() {
		b.mu.Lock()
		delete(b.subscribers[runID], channel)
		if len(b.subscribers[runID]) == 0 {
			delete(b.subscribers, runID)
		}
		b.mu.Unlock()
		close(channel)
	}
}
