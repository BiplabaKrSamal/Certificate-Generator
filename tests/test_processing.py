from dataclasses import replace
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from certgen import jobs
from certgen.main import create_app

from .helpers import (
    certificates,
    job_payload,
    process_now,
    run_job,
    set_lease,
)


def test_progress_is_visible_while_the_job_runs(client, hold_jobs, monkeypatch):
    job_id = client.post("/jobs", json=job_payload(5)).json()["id"]
    snapshots = []
    real_render = jobs.render_certificate

    def spy(data):
        snapshots.append(client.get(f"/jobs/{job_id}").json())
        return real_render(data)

    monkeypatch.setattr(jobs, "COMMIT_EVERY", 1)
    monkeypatch.setattr(jobs, "render_certificate", spy)
    process_now(client, job_id)

    assert [s["counts"]["generated"] for s in snapshots] == [0, 1, 2, 3, 4]
    assert {s["status"] for s in snapshots} == {"processing"}
    assert [s["progress_percent"] for s in snapshots] == [0.0, 20.0, 40.0, 60.0, 80.0]
    final = client.get(f"/jobs/{job_id}").json()
    assert final["status"] == "completed"
    assert final["progress_percent"] == 100.0


def test_one_failing_certificate_does_not_stop_the_job(client, monkeypatch):
    real_render = jobs.render_certificate

    def flaky(data):
        if data.name == "Student 2":
            raise OSError("disk full")
        return real_render(data)

    monkeypatch.setattr(jobs, "render_certificate", flaky)

    job = run_job(client, job_payload(5))

    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {"total": 5, "pending": 0, "generated": 4, "failed": 1}
    [failed] = certificates(client, job["id"], status="failed")
    assert failed["name"] == "Student 2"
    assert failed["error"] == "OSError: disk full"


def test_job_where_every_certificate_fails_is_marked_failed(client, monkeypatch):
    def broken(data):
        raise RuntimeError("renderer crashed")

    monkeypatch.setattr(jobs, "render_certificate", broken)

    job = run_job(client, job_payload(3))

    assert job["status"] == "failed"
    assert job["counts"] == {"total": 3, "pending": 0, "generated": 0, "failed": 3}


class FakeClock:
    """Every reading advances one second, so a budget of N seconds is N-1 certificates."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 1.0
        return self.now


def test_a_job_that_runs_out_of_time_is_continued_by_status_requests(
    settings, monkeypatch
):
    monkeypatch.setattr(jobs, "_clock", FakeClock())
    with TestClient(create_app(replace(settings, work_seconds=3))) as client:
        first = client.post("/jobs", json=job_payload(5)).json()

        assert first["status"] == "processing"
        assert first["counts"]["generated"] == 2

        second = client.get(f"/jobs/{first['id']}").json()
        assert second["status"] == "processing"
        assert second["counts"]["generated"] == 4

        third = client.get(f"/jobs/{first['id']}").json()
        assert third["status"] == "completed"
        assert third["counts"]["generated"] == 5


def test_a_job_another_worker_holds_is_left_alone(client, hold_jobs):
    job_id = client.post("/jobs", json=job_payload(3)).json()["id"]
    set_lease(client, job_id, +30)  # someone else is on it

    process_now(client, job_id)
    assert client.get(f"/jobs/{job_id}").json()["counts"]["generated"] == 0

    set_lease(client, job_id, -1)  # they stopped checking in
    process_now(client, job_id)
    assert client.get(f"/jobs/{job_id}").json()["status"] == "completed"


def test_a_crashed_job_resumes_where_it_left_off(client, hold_jobs, monkeypatch):
    job_id = client.post("/jobs", json=job_payload(4)).json()["id"]
    real_render = jobs.render_certificate
    rendered = []

    def die_on_the_third(data):
        rendered.append(data.name)
        if len(rendered) == 3:
            raise KeyboardInterrupt  # the process dying; not caught per certificate
        return real_render(data)

    monkeypatch.setattr(jobs, "COMMIT_EVERY", 1)
    monkeypatch.setattr(
        jobs, "LEASE", timedelta(0)
    )  # a dead worker's lease runs out at once
    monkeypatch.setattr(jobs, "render_certificate", die_on_the_third)
    with pytest.raises(KeyboardInterrupt):
        process_now(client, job_id)
    crashed = client.get(f"/jobs/{job_id}").json()
    assert crashed["status"] == "processing"
    assert crashed["counts"]["generated"] == 2

    rendered.clear()
    monkeypatch.setattr(
        jobs,
        "render_certificate",
        lambda data: rendered.append(data.name) or real_render(data),
    )
    process_now(client, job_id)

    assert rendered == ["Student 2", "Student 3"]  # only what was left
    resumed = client.get(f"/jobs/{job_id}").json()
    assert resumed["status"] == "completed"
    assert resumed["counts"]["generated"] == 4


def test_another_instance_can_finish_a_job(settings):
    with TestClient(create_app(replace(settings, work_seconds=0))) as first:
        job = first.post("/jobs", json=job_payload(3)).json()
        assert job["counts"]["generated"] == 0  # no time to do anything

    with TestClient(create_app(settings)) as second:
        job = second.get(f"/jobs/{job['id']}").json()

    assert job["status"] == "completed"
    assert job["counts"]["generated"] == 3
