import pytest

from certgen.schemas import validate_recipient

from .helpers import certificates, job_payload, recipient, run_job


def test_valid_recipient_is_cleaned_up():
    parsed, error = validate_recipient(
        {"name": "  Asha   Verma ", "email": "Asha@Example.com"}
    )

    assert error is None
    assert parsed.name == "Asha Verma"
    assert parsed.email == "Asha@example.com"


INVALID = {
    "missing name": ({"email": "a@example.com"}, "name: Field required"),
    "missing email": ({"name": "Asha"}, "email: Field required"),
    "blank name": (
        {"name": "   ", "email": "a@example.com"},
        "name: must not be blank",
    ),
    "bad email": (
        {"name": "Asha", "email": "not-an-email"},
        "email: value is not a valid email address",
    ),
    "name too long": (
        {"name": "A" * 61, "email": "a@example.com"},
        "name: is too long",
    ),
    "name too wide": (
        {"name": "W" * 60, "email": "a@example.com"},
        "name: is too wide",
    ),
    "name can't be drawn": (
        {"name": "आशा", "email": "a@example.com"},
        "name: has characters the certificate font can't render",
    ),
    "control character": (
        {"name": "Asha\x07", "email": "a@example.com"},
        "name: has control characters",
    ),
    "name not a string": (
        {"name": 42, "email": "a@example.com"},
        "name: Input should be a valid string",
    ),
    "not an object": ("Asha <a@example.com>", "recipient must be an object"),
}


@pytest.mark.parametrize("raw, message", INVALID.values(), ids=INVALID.keys())
def test_invalid_recipient_is_rejected_with_a_reason(raw, message):
    parsed, error = validate_recipient(raw)

    assert parsed is None
    assert message in error


def test_invalid_recipients_do_not_block_the_valid_ones(client):
    recipients = [
        recipient(0),
        {"name": "No Email"},
        recipient(2),
        {"name": "Bad", "email": "nope"},
    ]

    job = run_job(client, job_payload(0, recipients=recipients))

    assert job["status"] == "completed_with_errors"
    assert job["counts"] == {"total": 4, "pending": 0, "generated": 2, "failed": 2}
    failed = certificates(client, job["id"], status="failed")
    assert [c["position"] for c in failed] == [1, 3]
    assert "email: Field required" in failed[0]["error"]
    assert failed[0]["name"] == "No Email"
    assert failed[1]["email"] == "nope"  # what was sent is echoed back
    assert all(c["download_url"] is None for c in failed)
    assert len(certificates(client, job["id"], status="generated")) == 2


def test_rejected_recipients_show_up_in_the_submit_response(client, hold_jobs):
    body = client.post(
        "/jobs", json=job_payload(0, recipients=[recipient(0), {"name": "x"}])
    ).json()

    assert body["counts"] == {"total": 2, "pending": 1, "generated": 0, "failed": 1}
    assert body["progress_percent"] == 50.0  # rejected rows count as processed


def test_job_with_no_valid_recipients_fails_straight_away(client):
    job = client.post(
        "/jobs", json=job_payload(0, recipients=[{"name": "x"}, "junk"])
    ).json()

    assert job["status"] == "failed"
    assert job["counts"] == {"total": 2, "pending": 0, "generated": 0, "failed": 2}
    assert job["finished_at"] is not None
