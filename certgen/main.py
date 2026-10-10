import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.orm import sessionmaker

from .api import router
from .config import Settings
from .database import init_schema, make_engine


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    engine = make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if os.getenv("VERCEL") and engine.url.get_backend_name() == "sqlite":
            raise RuntimeError(
                "DATABASE_URL is not set. Vercel's filesystem is read-only, so SQLite "
                "can't be used there: add a Postgres database to the project "
                "(Storage tab, for example Neon) and redeploy."
            )
        init_schema(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Bulk Certificate Generator", lifespan=lifespan)
    app.state.settings = settings
    app.state.session_factory = sessionmaker(engine, expire_on_commit=False)
    app.include_router(router)
    return app
