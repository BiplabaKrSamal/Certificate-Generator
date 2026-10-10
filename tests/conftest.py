import pytest
from fastapi.testclient import TestClient

from certgen import api
from certgen.config import Settings
from certgen.main import create_app


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        max_recipients=20,
        work_seconds=30,
    )


@pytest.fixture
def client(settings):
    # Entering the context runs the app's startup, which creates the tables.
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def hold_jobs(monkeypatch):
    """Stop requests from generating anything, so a test can run process_job itself."""
    monkeypatch.setattr(api.jobs, "process_job", lambda *args, **kwargs: None)
