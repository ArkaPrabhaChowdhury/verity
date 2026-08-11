from datetime import timedelta
from pathlib import Path

import pytest

from verity.models import Event, Run, utc_now
from verity.store import RunNotFound, SQLiteRepository


@pytest.fixture
async def repository(tmp_path: Path):
    store = SQLiteRepository(str(tmp_path / "verity.db"))
    await store.connect()
    yield store
    await store.close()


async def test_run_and_event_round_trip(repository: SQLiteRepository) -> None:
    run = Run(id="run-1", question="What is the verified answer?")
    await repository.create_run(run)
    event = Event(run_id=run.id, type="plan_created", data={"round": 0})
    await repository.append_event(event)

    loaded = await repository.get_run(run.id)
    events = await repository.list_events(run.id)

    assert loaded.question == run.question
    assert event.seq > 0
    assert events[0].data == {"round": 0}


async def test_delete_cascades_events(repository: SQLiteRepository) -> None:
    run = Run(id="run-2", question="What evidence supports this?")
    await repository.create_run(run)
    await repository.append_event(Event(run_id=run.id, type="started", data={}))
    await repository.delete_run(run.id)

    with pytest.raises(RunNotFound):
        await repository.get_run(run.id)
    assert await repository.list_events(run.id) == []


async def test_list_runs_is_newest_first(repository: SQLiteRepository) -> None:
    await repository.create_run(Run(id="first", question="First valid question?"))
    await repository.create_run(Run(id="second", question="Second valid question?"))
    runs = await repository.list_runs(20)
    assert [run.id for run in runs] == ["second", "first"]


async def test_idempotency_is_workspace_scoped(repository: SQLiteRepository) -> None:
    await repository.create_run(
        Run(
            id="same",
            question="A valid question?",
            workspace_id="one",
            idempotency_key="k",
        )
    )
    assert (await repository.find_idempotent_run("one", "k")).id == "same"
    assert await repository.find_idempotent_run("two", "k") is None


async def test_expired_lease_is_requeued(repository: SQLiteRepository) -> None:
    run = Run(
        id="leased",
        question="A valid question?",
        status="running",
        lease_expires_at=utc_now() - timedelta(seconds=1),
    )
    await repository.create_run(run)
    assert await repository.recover_expired_runs() == 1
    assert (await repository.get_run(run.id)).status == "queued"

