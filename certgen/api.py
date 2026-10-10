from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import jobs
from .models import Certificate, CertificateStatus, Job
from .schemas import CertificateOut, Counts, JobCreate, JobOut

router = APIRouter()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]


@router.post("/jobs", response_model=JobOut, status_code=202)
def submit_job(payload: JobCreate, request: Request, session: SessionDep):
    """Submit recipients. Certificates are generated before this answers, up to
    WORK_SECONDS; a bigger job is finished by later `GET /jobs/{id}` calls."""
    limit = request.app.state.settings.max_recipients
    if len(payload.recipients) > limit:
        raise HTTPException(422, f"a job can contain at most {limit} recipients")

    job = jobs.create_job(session, payload)
    _work_on(request, session, job)
    return job_view(session, job)


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: UUID, request: Request, session: SessionDep):
    """Status and progress of a job. If it isn't finished, this call also
    carries on generating (unless another request is already doing so)."""
    job = _find_job(session, job_id)
    _work_on(request, session, job)
    return job_view(session, job)


@router.get("/jobs/{job_id}/certificates", response_model=list[CertificateOut])
def list_certificates(
    job_id: UUID,
    session: SessionDep,
    status: CertificateStatus | None = None,
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """Per-recipient results in submission order. Use `status` to see only the failures."""
    _find_job(session, job_id)
    query = select(Certificate).where(Certificate.job_id == job_id)
    if status:
        query = query.where(Certificate.status == status)
    rows = session.scalars(
        query.order_by(Certificate.position).limit(limit).offset(offset)
    )
    return [certificate_view(row) for row in rows]


@router.get("/certificates/{certificate_id}/file")
def download_certificate(certificate_id: UUID, session: SessionDep):
    """One generated certificate as a PDF."""
    row = session.execute(
        select(Certificate.status, Certificate.error, Certificate.pdf).where(
            Certificate.id == certificate_id
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(404, "certificate not found")
    status, error, pdf = row
    if status == CertificateStatus.PENDING:
        raise HTTPException(409, "certificate has not been generated yet")
    if status == CertificateStatus.FAILED:
        raise HTTPException(404, f"no file, generation failed: {error}")
    return Response(
        pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{certificate_id}.pdf"'},
    )


def job_view(session: Session, job: Job) -> JobOut:
    counts = jobs.status_counts(session, job.id)
    total = sum(counts.values())
    done = counts[CertificateStatus.GENERATED] + counts[CertificateStatus.FAILED]
    return JobOut(
        id=job.id,
        status=job.status,
        event_name=job.event_name,
        issued_by=job.issued_by,
        issued_on=job.issued_on,
        counts=Counts(
            total=total,
            pending=counts[CertificateStatus.PENDING],
            generated=counts[CertificateStatus.GENERATED],
            failed=counts[CertificateStatus.FAILED],
        ),
        progress_percent=round(100 * done / total, 1),
        created_at=job.created_at,
        finished_at=job.finished_at,
    )


def certificate_view(certificate: Certificate) -> CertificateOut:
    generated = certificate.status == CertificateStatus.GENERATED
    return CertificateOut(
        id=certificate.id,
        position=certificate.position,
        name=certificate.name,
        email=certificate.email,
        status=certificate.status,
        error=certificate.error,
        download_url=f"/certificates/{certificate.id}/file" if generated else None,
    )


def _work_on(request: Request, session: Session, job: Job) -> None:
    """Spend this request's time budget on the job, if it still has work left."""
    if job.status not in jobs.UNFINISHED:
        return
    session.commit()  # end our read transaction so we see the worker's commits
    jobs.process_job(
        job.id,
        request.app.state.session_factory,
        request.app.state.settings.work_seconds,
    )
    session.refresh(job)


def _find_job(session: Session, job_id: UUID) -> Job:
    job = session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "job not found")
    return job
