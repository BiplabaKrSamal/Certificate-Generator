import uuid
from datetime import timedelta

from sqlalchemy import update

from certgen.database import utcnow

# Bound here, before any test patches the module's attribute.
from certgen.jobs import process_job as _process_job
from certgen.models import Job


def recipient(i: int) -> dict:
    return {"name": f"Student {i}", "email": f"student{i}@example.com"}


def job_payload(count: int = 3, **overrides) -> dict:
    payload = {
        "event_name": "Python Bootcamp 2026",
        "issued_by": "Acme Academy",
        "issued_on": "2026-10-01",
        "recipients": [recipient(i) for i in range(count)],
    }
    return payload | overrides


def run_job(client, payload: dict) -> dict:
    """Submit a job and return its status (a small job is finished when POST answers)."""
    response = client.post("/jobs", json=payload)
    assert response.status_code == 202, response.text
    return client.get(f"/jobs/{response.json()['id']}").json()


def process_now(client, job_id: str, work_seconds: float = 30) -> None:
    """Run the job's work in the test thread. Use together with hold_jobs."""
    _process_job(uuid.UUID(job_id), client.app.state.session_factory, work_seconds)


def set_lease(client, job_id: str, seconds_from_now: float) -> None:
    """Pretend another worker holds (or has abandoned) the job's lease."""
    with client.app.state.session_factory() as session:
        session.execute(
            update(Job)
            .where(Job.id == uuid.UUID(job_id))
            .values(lease_until=utcnow() + timedelta(seconds=seconds_from_now))
        )
        session.commit()


def certificates(client, job_id: str, **params) -> list[dict]:
    response = client.get(f"/jobs/{job_id}/certificates", params=params)
    assert response.status_code == 200, response.text
    return response.json()
