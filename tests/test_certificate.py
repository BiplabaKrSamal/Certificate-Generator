import io
import uuid
from dataclasses import replace
from datetime import date

import pytest
from pypdf import PdfReader

from certgen.certificate import CertificateData, render_certificate, text_problem

CERTIFICATE = CertificateData(
    certificate_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
    name="Asha Verma",
    event_name="Python Bootcamp 2026",
    issued_by="Acme Academy",
    issued_on=date(2026, 10, 1),
)


def page_text(data: CertificateData) -> str:
    return PdfReader(io.BytesIO(render_certificate(data))).pages[0].extract_text()


def test_renders_one_landscape_a4_page():
    pdf = render_certificate(CERTIFICATE)

    assert pdf.startswith(b"%PDF")
    reader = PdfReader(io.BytesIO(pdf))
    assert len(reader.pages) == 1
    box = reader.pages[0].mediabox
    assert (round(box.width), round(box.height)) == (842, 595)


def test_contains_the_recipient_and_job_details():
    text = page_text(CERTIFICATE)

    for expected in [
        "Asha Verma",
        "Python Bootcamp 2026",
        "Acme Academy",
        "1 October 2026",
        "12345678-1234-5678-1234-567812345678",
    ]:
        assert expected in text


def test_long_text_shrinks_to_fit_instead_of_overflowing():
    name = "Priyanka Chaturvedi-Sharma Venkataraghavan Subramaniam"
    event = "Advanced Machine Learning and Data Engineering Bootcamp 2026 Cohort"

    assert text_problem("name", name) is None
    assert text_problem("event_name", event) is None
    text = page_text(replace(CERTIFICATE, name=name, event_name=event))
    assert name in text and event in text


@pytest.mark.parametrize(
    "field, text, expected",
    [
        ("name", "José Ñandú O'Brien", None),
        ("name", "Łukasz", "can't render"),
        ("name", "आशा", "can't render"),
        ("name", "W" * 60, "too wide"),
        ("name", "A" * 61, "too long"),
        ("event_name", "A" * 80, "too wide"),
    ],
)
def test_text_problem(field, text, expected):
    problem = text_problem(field, text)

    if expected is None:
        assert problem is None
    else:
        assert expected in problem


def test_rendering_refuses_text_it_cannot_draw():
    with pytest.raises(ValueError, match="name has characters"):
        render_certificate(replace(CERTIFICATE, name="Łukasz"))
