import enum
import uuid
from datetime import date, datetime

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base, UTCDateTime, utcnow


class JobStatus(enum.StrEnum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"
    FAILED = "failed"


class CertificateStatus(enum.StrEnum):
    PENDING = "pending"
    GENERATED = "generated"
    FAILED = "failed"


def _enum(cls: type[enum.StrEnum]) -> Enum:
    return Enum(
        cls,
        native_enum=False,
        length=32,
        values_callable=lambda members: [m.value for m in members],
    )


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    status: Mapped[JobStatus] = mapped_column(_enum(JobStatus), index=True)
    event_name: Mapped[str] = mapped_column(String(255))
    issued_by: Mapped[str] = mapped_column(String(255))
    issued_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Whoever is generating this job's certificates keeps this in the future.
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Certificate(Base):
    """One row per submitted recipient, including the ones that failed validation."""

    __tablename__ = "certificates"
    __table_args__ = (
        UniqueConstraint("job_id", "position"),
        Index("ix_certificates_job_status", "job_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"))
    position: Mapped[int]  # index in the request's recipients list, 0-based
    name: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[CertificateStatus] = mapped_column(_enum(CertificateStatus))
    error: Mapped[str | None] = mapped_column(Text)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary, deferred=True)
