# Bulk Certificate Generator

Post a list of recipients with the event details and get back a job. The certificates (one PDF each) are generated for you, you can check progress at any time, and then you download them.

FastAPI, SQLAlchemy and reportlab. SQLite for local use, PostgreSQL for hosting (it runs on Vercel).

## Setup and run

Python 3.11 or newer (developed on 3.12).

```bash
python -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app:app
```

The API is at http://127.0.0.1:8000, interactive docs at `/docs`. Tables are created on startup. Settings come from environment variables:

- `DATABASE_URL`: defaults to a SQLite file in `./data`. Any SQLAlchemy URL works, and `postgres://` or `postgresql://` URLs as a host hands them out are accepted as they are.
- `MAX_RECIPIENTS`: largest job accepted, default `5000`.
- `WORK_SECONDS`: how long one request may spend generating certificates before it answers, default `60`.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

54 tests, about two seconds, each on its own temporary database. They cover job creation, input validation, certificate generation, progress, a single certificate failing, continuing a job that ran out of time or whose worker died, and retrieval.

## Deploy on Vercel

1. Push the repository to GitHub and import it as a new project in Vercel. It is detected as a FastAPI app, so there is nothing to configure.
2. In the project's Storage tab, add a Postgres database (Neon from the Marketplace works) and connect it to the project. That sets `DATABASE_URL`.
3. Deploy, or redeploy if the project was already built. The tables are created on first start. The API is at `https://<project>.vercel.app`, docs at `/docs`.

Vercel's filesystem is read-only, so SQLite can't be used there; without `DATABASE_URL` the app stops at startup and says so. Create the database in the region your functions run in (Washington, D.C. unless you changed it). Keep `WORK_SECONDS` under the function's maximum duration (300 s). The API has no authentication, so anyone with the URL can use it; turn on Deployment Protection if that matters.

## Submit a request

```bash
curl -X POST http://127.0.0.1:8000/jobs -H "Content-Type: application/json" \
     -d @examples/sample_request.json
```

The answer is `202` with the job. A small job is already finished by then:

```json
{
  "id": "1f2df5ae-e2fe-4bf2-9eed-4c95eb1e4f29",
  "status": "completed_with_errors",
  "event_name": "Python Bootcamp 2026",
  "issued_by": "Acme Academy",
  "issued_on": "2026-10-01",
  "counts": {"total": 5, "pending": 0, "generated": 4, "failed": 1},
  "progress_percent": 100.0,
  "created_at": "2026-10-10T01:07:25.904584Z",
  "finished_at": "2026-10-10T01:07:25.920307Z"
}
```

| Field | Notes |
|---|---|
| `event_name` | required, up to 80 characters |
| `issued_by` | required, up to 50 characters |
| `issued_on` | optional ISO date, defaults to today (UTC) |
| `recipients` | required, 1 to `MAX_RECIPIENTS` items |
| `recipients[].name` | required, up to 60 characters |
| `recipients[].email` | required, a valid address |

A problem with the request as a whole (broken JSON, missing or blank `event_name`, empty list, too many recipients) is rejected with `422`. A problem with one recipient is not: that recipient is stored as `failed` with the reason, and everyone else is processed normally.

## Check progress

```bash
curl http://127.0.0.1:8000/jobs/<job-id>
```

This returns the job in the shape above. Status is `queued`, `processing`, `completed`, `completed_with_errors` (some generated, some failed) or `failed` (nothing generated). `progress_percent` is (generated + failed) / total, so recipients rejected by validation count as processed. If a job isn't finished, this call also carries on generating it, unless another request is already doing so (see below).

To see which recipients failed and why:

```bash
curl "http://127.0.0.1:8000/jobs/<job-id>/certificates?status=failed"
```
```json
[
  {
    "id": "89ef75fd-c7cc-4619-bb39-c42b44af1e3e",
    "position": 3,
    "name": "Karan Mehta",
    "email": "not-an-email",
    "status": "failed",
    "error": "email: value is not a valid email address: An email address must have an @-sign.",
    "download_url": null
  }
]
```

Results come back in submission order and `position` is the 0-based index in your `recipients` list. `status` (`pending`, `generated`, `failed`), `limit` (1 to 1000, default 100) and `offset` are optional.

## Retrieve certificates

Every generated item in that list has a `download_url`:

```bash
curl -o asha.pdf http://127.0.0.1:8000/certificates/<certificate-id>/file
```

`409` means it isn't generated yet. `404` means it failed (the response says why) or doesn't exist.

## Design decisions

**No background worker: the request does the work.** A serverless function has no long-lived process to keep a worker thread in, and I didn't want a job's progress to depend on what the platform does with work left over after the response. So `POST /jobs` validates, stores and then generates the certificates, for up to `WORK_SECONDS`, before it answers. That takes about 10 seconds for 5,000 recipients on the machine I built this on, and a small job is done by the time you see the response. If a job doesn't finish in its budget, the pending rows simply stay in the database and the next `GET /jobs/{id}` continues from there.

**The database is the queue, and a lease keeps it safe.** All the state is rows: each certificate is `pending`, `generated` or `failed`. Whoever works on a job first takes a 30-second lease on it and renews it as it goes. A second request that finds a live lease just reports progress. A request that dies stops renewing, so the next one takes over. I ran three server processes on PostgreSQL with six clients polling one 5,000-certificate job, and every certificate was generated exactly once. Certificates are committed 25 at a time to keep round trips to a remote database low, so a crash redoes at most the last 25.

**One failure never takes the job down.** Each certificate is generated inside its own try/except. The error is stored on that row and the loop moves on. The job ends `completed_with_errors`, or `failed` if nothing was generated.

**Validation is per recipient, and it knows the template.** One typo in 4,000 rows shouldn't force a resubmit, so a bad recipient only fails itself. And reportlab's built-in fonts draw any character outside Western European Latin as a black box without raising an error. So the template's limits (characters, lengths, whether the text fits its slot) are shared with validation, and a name like `Łukasz` or `आशा` is rejected with a message instead of producing a broken certificate. Supporting more scripts means bundling a TTF font in `certificate.py` (and, for Indic scripts, a renderer that does text shaping, which reportlab doesn't).

**PDFs are stored in the database.** Hosts like Vercel have no persistent disk. A certificate is about 2 KB, so a 5,000-certificate job is roughly 11 MB. For much larger volumes, swap the `pdf` column for object storage. SQLite runs with WAL and with foreign keys on (that caught a real bug, rows inserted in the wrong order, which PostgreSQL would have rejected). I ran the whole flow on PostgreSQL 16 by hand; the test suite runs on SQLite.

Not included: authentication, retrying failed certificates, clean-up of old jobs, migrations (tables come from `create_all`).
