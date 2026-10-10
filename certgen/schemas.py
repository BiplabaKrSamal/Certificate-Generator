from datetime import date, datetime
from functools import partial
from typing import Annotated, Any
from uuid import UUID

from pydantic import AfterValidator, BaseModel, EmailStr, Field, ValidationError

from .certificate import text_problem
from .models import CertificateStatus, JobStatus


def _clean(field: str, value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    if not value.isprintable():
        raise ValueError("has control characters")
    if problem := text_problem(field, value):
        raise ValueError(problem)
    return value


EventName = Annotated[str, AfterValidator(partial(_clean, "event_name"))]
IssuedBy = Annotated[str, AfterValidator(partial(_clean, "issued_by"))]
Name = Annotated[str, AfterValidator(partial(_clean, "name"))]


class JobCreate(BaseModel):
    """The request as a whole. A problem here rejects the entire job."""

    event_name: EventName
    issued_by: IssuedBy
    issued_on: date | None = None
    # Raw items on purpose: one bad recipient must not reject the other four
    # thousand, so each is validated on its own (see validate_recipient).
    recipients: list[Any] = Field(min_length=1)


class RecipientData(BaseModel):
    name: Name
    email: EmailStr


def validate_recipient(raw: Any) -> tuple[RecipientData | None, str | None]:
    if not isinstance(raw, dict):
        return None, "recipient must be an object with name and email"
    try:
        return RecipientData.model_validate(raw), None
    except ValidationError as exc:
        return None, "; ".join(_describe(error) for error in exc.errors())


def _describe(error: Any) -> str:
    field = ".".join(str(part) for part in error["loc"])
    message = error["msg"].removeprefix("Value error, ")
    return f"{field}: {message}" if field else message


class Counts(BaseModel):
    total: int
    pending: int
    generated: int
    failed: int


class JobOut(BaseModel):
    id: UUID
    status: JobStatus
    event_name: str
    issued_by: str
    issued_on: date
    counts: Counts
    progress_percent: float
    created_at: datetime
    finished_at: datetime | None


class CertificateOut(BaseModel):
    id: UUID
    position: int
    name: str | None
    email: str | None
    status: CertificateStatus
    error: str | None
    download_url: str | None
