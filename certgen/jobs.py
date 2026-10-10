import logging
import time
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from .certificate import CertificateData, render_certificate
from .database import utcnow
from .models import Certificate, CertificateStatus, Job, JobStatus
from .schemas import JobCreate, validate_recipient

log = logging.getLogger(__name__)

UNFINISHED = (JobStatus.QUEUED, JobStatus.PROCESSING)
LEASE = timedelta(seconds=30)  # how long a worker owns a job between check-ins
COMMIT_EVERY = 25  # certificates per commit, to keep round trips to the database low
_clock = time.monotonic


def create_job(session: Session, payload: JobCreate) -> Job:
    """Validate every recipient and store the lot in one transaction.

    Invalid recipients are kept as failed rows with the reason, so the client can
    see what was wrong. Only the valid ones are left pending.
    """
    job = Job(
        id=uuid.uuid4(),
        status=JobStatus.QUEUED,
        event_name=payload.event_name,
        issued_by=payload.issued_by,
        issued_on=payload.issued_on or utcnow().date(),
    )

    certificates = []
    for position, raw in enumerate(payload.recipients):
        recipient, error = validate_recipient(raw)
        certificates.append(
            Certificate(
                id=uuid.uuid4(),
                job_id=job.id,
                position=position,
                name=recipient.name if recipient else _echo(raw, "name"),
                email=recipient.email if recipient else _echo(raw, "email"),
                status=(
                    CertificateStatus.PENDING if recipient else CertificateStatus.FAILED
                ),
                error=error,
            )
        )

    session.add(job)
    # No relationship() links the two models, so the ORM wouldn't know to insert
    # the job first. Flush it explicitly or the foreign key fails.
    session.flush()
    session.add_all(certificates)
    session.commit()
    return job


def status_counts(session: Session, job_id: uuid.UUID) -> dict[CertificateStatus, int]:
    rows = session.execute(
        select(Certificate.status, func.count())
        .where(Certificate.job_id == job_id)
        .group_by(Certificate.status)
    ).all()
    counts = {status: 0 for status in CertificateStatus}
    counts.update(dict(rows))
    return counts


def process_job(
    job_id: uuid.UUID, session_factory: sessionmaker[Session], work_seconds: float
) -> None:
    """Generate the pending certificates of a job, for at most `work_seconds`.

    There is no background worker: whichever request calls this does the work.
    Many requests may call it for the same job. The first to claim the job's
    lease works and the rest return at once. A job that doesn't finish in time
    keeps its pending rows for the next call, and a worker that dies just stops
    renewing the lease, so the next call takes over.
    """
    with session_factory() as session:
        if not _claim(session, job_id):
            return
        job = session.get(Job, job_id)
        pending = session.scalars(
            select(Certificate)
            .where(
                Certificate.job_id == job_id,
                Certificate.status == CertificateStatus.PENDING,
            )
            .order_by(Certificate.position)
        ).all()

        deadline = _clock() + work_seconds
        for done, certificate in enumerate(pending, start=1):
            if _clock() >= deadline:
                job.lease_until = None  # out of time; the next call carries on
                session.commit()
                return
            _generate(job, certificate)
            if done % COMMIT_EVERY == 0:
                job.lease_until = utcnow() + LEASE
                session.commit()
        _finish(session, job)


def _claim(session: Session, job_id: uuid.UUID) -> bool:
    """Take the job's lease if the job is unfinished and nobody holds it."""
    now = utcnow()
    result = session.execute(
        update(Job)
        .where(
            Job.id == job_id,
            Job.status.in_(UNFINISHED),
            or_(Job.lease_until.is_(None), Job.lease_until < now),
        )
        .values(status=JobStatus.PROCESSING, lease_until=now + LEASE)
    )
    session.commit()
    return result.rowcount == 1


def _generate(job: Job, certificate: Certificate) -> None:
    try:
        certificate.pdf = render_certificate(
            CertificateData(
                certificate_id=certificate.id,
                name=certificate.name,
                event_name=job.event_name,
                issued_by=job.issued_by,
                issued_on=job.issued_on,
            )
        )
        certificate.status = CertificateStatus.GENERATED
    except Exception as exc:
        log.exception("certificate %s in job %s failed", certificate.id, job.id)
        certificate.status = CertificateStatus.FAILED
        certificate.error = f"{type(exc).__name__}: {exc}"[:500]


def _finish(session: Session, job: Job) -> None:
    counts = status_counts(session, job.id)
    if counts[CertificateStatus.GENERATED] == 0:
        job.status = JobStatus.FAILED
    elif counts[CertificateStatus.FAILED]:
        job.status = JobStatus.COMPLETED_WITH_ERRORS
    else:
        job.status = JobStatus.COMPLETED
    job.finished_at = utcnow()
    job.lease_until = None
    session.commit()


def _echo(raw: Any, key: str) -> str | None:
    """What the client sent for a rejected recipient, so the failure is easy to match up."""
    value = raw.get(key) if isinstance(raw, dict) else None
    return value.replace("\x00", "")[:255] if isinstance(value, str) else None
