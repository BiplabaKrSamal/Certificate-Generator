import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from certgen.config import Settings, _with_driver
from certgen.main import create_app


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "postgres://u:p@host/db?sslmode=require",
            "postgresql+psycopg://u:p@host/db?sslmode=require",
        ),
        ("postgresql://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///x.db", "sqlite:///x.db"),
    ],
)
def test_hosted_postgres_urls_get_a_driver(url, expected):
    assert _with_driver(url) == expected


def test_settings_read_the_database_url_the_host_provides(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("POSTGRES_URL", "postgres://u:p@host/db")
    assert Settings.from_env().database_url == "postgresql+psycopg://u:p@host/db"

    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@other/db")
    assert Settings.from_env().database_url == "postgresql+psycopg://u:p@other/db"


def test_entry_point_imports_without_a_database_or_a_writable_disk(tmp_path):
    # Vercel imports app.py while building, before any database is reachable.
    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-c", "import app; print(type(app.app).__name__)"],
        cwd=tmp_path,
        env={"PYTHONPATH": str(root), "PATH": ""},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.stdout.strip() == "FastAPI", result.stderr
    assert list(tmp_path.iterdir()) == []


def test_vercel_without_a_database_says_what_to_do(settings, monkeypatch):
    monkeypatch.setenv(
        "VERCEL", "1"
    )  # its filesystem is read-only, so SQLite can't work

    with (
        pytest.raises(RuntimeError, match="DATABASE_URL is not set"),
        TestClient(create_app(settings)),
    ):
        pass
