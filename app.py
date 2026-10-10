# Entry point: `uvicorn app:app` locally, and the top-level `app` Vercel looks for.
from certgen.main import create_app

app = create_app()
