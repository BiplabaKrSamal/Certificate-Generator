import io
import uuid

from pypdf import PdfReader

from .helpers import certificates, job_payload, recipient, run_job


def test_download_a_single_certificate(client):
    job = run_job(client, job_payload(3))
    item = certificates(client, job["id"])[1]
    assert item["download_url"] == f"/certificates/{item['id']}/file"

    response = client.get(item["download_url"])

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    page = PdfReader(io.BytesIO(response.content)).pages[0]
    assert "Student 1" in page.extract_text()


def test_certificate_list_filters_and_paginates(client):
    recipients = [
        recipient(0),
        {"name": "bad"},
        recipient(2),
        recipient(3),
        recipient(4),
    ]
    job = run_job(client, job_payload(0, recipients=recipients))

    page = certificates(client, job["id"], limit=2, offset=2)
    assert [item["position"] for item in page] == [2, 3]

    failed = certificates(client, job["id"], status="failed")
    assert [item["position"] for item in failed] == [1]

    url = f"/jobs/{job['id']}/certificates"
    assert client.get(url, params={"limit": 0}).status_code == 422
    assert client.get(url, params={"status": "bogus"}).status_code == 422


def test_a_certificate_that_is_not_ready_gives_409(client, hold_jobs):
    job_id = client.post("/jobs", json=job_payload(2)).json()["id"]
    first = certificates(client, job_id)[0]

    assert client.get(f"/certificates/{first['id']}/file").status_code == 409


def test_failed_certificate_has_no_file(client):
    job = run_job(client, job_payload(0, recipients=[recipient(0), {"name": "bad"}]))
    [failed] = certificates(client, job["id"], status="failed")

    response = client.get(f"/certificates/{failed['id']}/file")

    assert response.status_code == 404
    assert "email: Field required" in response.json()["detail"]


def test_unknown_certificate_is_404(client):
    assert client.get(f"/certificates/{uuid.uuid4()}/file").status_code == 404
