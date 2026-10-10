"""The certificate template.

reportlab's built-in fonts only cover Western European characters and draw
anything else as black boxes, without raising. So `text_problem` is shared with
request validation: text that can't be drawn properly is rejected up front.
"""

from dataclasses import dataclass
from datetime import date
from io import BytesIO
from typing import NamedTuple
from uuid import UUID

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

WIDTH, HEIGHT = landscape(A4)
CENTER = WIDTH / 2
NAVY, GOLD, INK, MUTED = (
    HexColor(c) for c in ("#1b2a49", "#b08d4a", "#3a3a3a", "#7a7a7a")
)


class Slot(NamedTuple):
    font: str
    size: int  # preferred size; the text shrinks down to min_size to fit
    min_size: int
    width: int
    max_chars: int


SLOTS = {
    "name": Slot("Times-BoldItalic", 44, 20, 620, 60),
    "event_name": Slot("Times-Bold", 24, 14, 620, 80),
    "issued_by": Slot("Times-Roman", 14, 9, 230, 50),
}


@dataclass(frozen=True)
class CertificateData:
    certificate_id: UUID
    name: str
    event_name: str
    issued_by: str
    issued_on: date


def text_problem(field: str, text: str) -> str | None:
    """Why this text can't go on the certificate, or None if it can."""
    slot = SLOTS[field]
    if len(text) > slot.max_chars:
        return f"is too long (max {slot.max_chars} characters)"
    undrawable = {ch for ch in text if not ch.encode("cp1252", errors="ignore")}
    if undrawable:
        return "has characters the certificate font can't render: " + " ".join(
            sorted(undrawable)[:5]
        )
    if _fit_size(field, text) is None:
        return "is too wide to fit on the certificate"
    return None


def render_certificate(data: CertificateData) -> bytes:
    sizes = {}
    for field in SLOTS:
        text = getattr(data, field)
        if problem := text_problem(field, text):
            raise ValueError(f"{field} {problem}")
        sizes[field] = _fit_size(field, text)

    buffer = BytesIO()
    c = Canvas(buffer, pagesize=(WIDTH, HEIGHT))
    c.setTitle(f"Certificate - {data.name}")

    c.setStrokeColor(NAVY)
    c.setLineWidth(3)
    c.rect(24, 24, WIDTH - 48, HEIGHT - 48)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.8)
    c.rect(34, 34, WIDTH - 68, HEIGHT - 68)

    _text(c, 450, "CERTIFICATE", "Times-Bold", 46, NAVY)
    _text(c, 422, "OF COMPLETION", "Helvetica", 14, GOLD)
    _text(c, 372, "This certificate is proudly presented to", "Times-Italic", 16, INK)
    _text(c, 320, data.name, SLOTS["name"].font, sizes["name"], NAVY)
    c.setStrokeColor(GOLD)
    c.setLineWidth(0.6)
    c.line(CENTER - 260, 306, CENTER + 260, 306)
    _text(c, 262, "for successfully completing", "Times-Roman", 16, INK)
    _text(c, 226, data.event_name, SLOTS["event_name"].font, sizes["event_name"], NAVY)

    issued_on = f"{data.issued_on.day} {data.issued_on:%B %Y}"
    left, right = 170, WIDTH - 170
    c.setStrokeColor(NAVY)
    c.setLineWidth(0.8)
    for x in (left, right):
        c.line(x - 115, 100, x + 115, 100)
    _text(c, 108, issued_on, "Times-Roman", 14, INK, left)
    _text(
        c, 108, data.issued_by, SLOTS["issued_by"].font, sizes["issued_by"], INK, right
    )
    _text(c, 86, "Date of issue", "Helvetica", 9, MUTED, left)
    _text(c, 86, "Issued by", "Helvetica", 9, MUTED, right)
    _text(c, 52, f"Certificate ID: {data.certificate_id}", "Helvetica", 8, MUTED)

    c.showPage()
    c.save()
    return buffer.getvalue()


def _fit_size(field: str, text: str) -> int | None:
    slot = SLOTS[field]
    for size in range(slot.size, slot.min_size - 1, -1):
        if stringWidth(text, slot.font, size) <= slot.width:
            return size
    return None


def _text(
    c: Canvas, y: float, text: str, font: str, size: int, color, x=CENTER
) -> None:
    c.setFillColor(color)
    c.setFont(font, size)
    c.drawCentredString(x, y, text)
