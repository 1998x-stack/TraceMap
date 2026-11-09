"""Phase 0: PDF parsing must run in a bounded child process."""
from __future__ import annotations

from io import BytesIO

import pytest
from pypdf import PdfWriter


def make_pdf(*, pages: int = 1, password: str | None = None) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    if password:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_parser_returns_pages_from_isolated_worker():
    from tracemap.pdf_worker import parse_pdf_isolated

    assert parse_pdf_isolated(make_pdf()) == [(1, "")]


def test_pdf_parser_rejects_encrypted_and_excessive_page_documents():
    from tracemap.pdf_worker import PDFParseError, parse_pdf_isolated

    with pytest.raises(PDFParseError) as encrypted:
        parse_pdf_isolated(make_pdf(password="secret"))
    assert encrypted.value.code == "UNSUPPORTED_MEDIA_TYPE"
    assert encrypted.value.status == 415

    with pytest.raises(PDFParseError) as too_many:
        parse_pdf_isolated(make_pdf(pages=101))
    assert too_many.value.code == "UNSUPPORTED_MEDIA_TYPE"
    assert too_many.value.status == 415


def test_pdf_parser_timeout_terminates_worker(monkeypatch):
    from tracemap import pdf_worker

    class Connection:
        def poll(self, _timeout):
            return False
        def close(self):
            pass

    class Process:
        def __init__(self, **_kwargs):
            self.alive = True
            self.terminated = False
        def start(self):
            pass
        def is_alive(self):
            return self.alive
        def terminate(self):
            self.terminated = True
            self.alive = False
        def kill(self):
            self.alive = False
        def join(self, _timeout=None):
            pass

    class Context:
        def __init__(self):
            self.process = None
        def Pipe(self, duplex=False):
            assert duplex is False
            return Connection(), Connection()
        def Process(self, **kwargs):
            self.process = Process(**kwargs)
            return self.process

    context = Context()
    monkeypatch.setattr(pdf_worker.multiprocessing, "get_context", lambda _method: context)
    with pytest.raises(pdf_worker.PDFParseError) as timeout:
        pdf_worker.parse_pdf_isolated(b"%PDF-fake", timeout_seconds=0.01)
    assert timeout.value.code == "PDF_PARSE_TIMEOUT"
    assert context.process.terminated
