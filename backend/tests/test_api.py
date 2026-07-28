from fastapi.testclient import TestClient

from verity.app import app


def test_health_and_empty_run_list(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VERITY_DATABASE_URL", raising=False)
    monkeypatch.setenv("VERITY_DB_PATH", str(tmp_path / "api.db"))
    with TestClient(app) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get("/api/runs").json() == {"runs": []}


def test_rejects_short_and_unknown_request_fields(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("VERITY_DATABASE_URL", raising=False)
    monkeypatch.setenv("VERITY_DB_PATH", str(tmp_path / "validation.db"))
    with TestClient(app) as client:
        assert client.post("/api/runs", json={"question": "short"}).status_code == 422
        assert (
            client.post(
                "/api/runs",
                json={
                    "question": "This is a valid research question.",
                    "unexpected": True,
                },
            ).status_code
            == 422
        )
