import uuid

import pytest

from .helpers import job_payload


def test_a_small_job_is_finished_when_the_request_returns(client):
    response = client.post("/jobs", json=job_payload(3))

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert body["event_name"] == "Python Bootcamp 2026"
    assert body["counts"] == {"total": 3, "pending": 0, "generated": 3, "failed": 0}
    assert body["progress_percent"] == 100.0
    assert body["finished_at"]


def test_a_job_nobody_has_worked_on_is_queued(client, hold_jobs):
    body = client.post("/jobs", json=job_payload(3)).json()

    assert body["status"] == "queued"
    assert body["counts"] == {"total": 3, "pending": 3, "generated": 0, "failed": 0}
    assert body["progress_percent"] == 0.0


def _without(key: str) -> dict:
    payload = job_payload(1)
    del payload[key]
    return payload


BAD_JOBS = {
    "missing event_name": _without("event_name"),
    "blank event_name": job_payload(1, event_name="   "),
    "event_name can't be drawn": job_payload(1, event_name="Łódź workshop"),
    "missing issued_by": _without("issued_by"),
    "bad issued_on": job_payload(1, issued_on="01/10/2026"),
    "no recipients": job_payload(1, recipients=[]),
    "recipients not a list": job_payload(1, recipients="Asha"),
}


@pytest.mark.parametrize("payload", BAD_JOBS.values(), ids=BAD_JOBS.keys())
def test_request_level_problems_reject_the_whole_job(client, payload):
    assert client.post("/jobs", json=payload).status_code == 422


def test_too_many_recipients_is_rejected(client):
    response = client.post("/jobs", json=job_payload(21))

    assert response.status_code == 422
    assert "at most 20" in response.json()["detail"]


def test_unknown_job_is_404(client):
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404
    assert client.get(f"/jobs/{uuid.uuid4()}/certificates").status_code == 404
