from pathlib import Path

import pytest

from verity.models import Event, Run
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

