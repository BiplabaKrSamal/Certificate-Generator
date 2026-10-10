import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///data/certgen.db"
    max_recipients: int = 5000
    # How long one request may spend generating certificates before it answers.
    # Keep it well under the platform's request limit (300 s on Vercel).
    work_seconds: float = 60

    @classmethod
    def from_env(cls) -> "Settings":
        url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL")
        return cls(
            database_url=_with_driver(url) if url else cls.database_url,
            max_recipients=int(os.getenv("MAX_RECIPIENTS", cls.max_recipients)),
            work_seconds=float(os.getenv("WORK_SECONDS", cls.work_seconds)),
        )


def _with_driver(url: str) -> str:
    """Hosted Postgres hands out postgres:// or postgresql:// URLs; SQLAlchemy wants a driver."""
    for scheme in ("postgres://", "postgresql://"):
        if url.startswith(scheme):
            return "postgresql+psycopg://" + url[len(scheme) :]
    return url
