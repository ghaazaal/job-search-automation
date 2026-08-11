"""Tests for src/resume_intake.py — what is allowed in, and where it lands."""
import hashlib

import pytest

from src.resume_intake import (MAX_BYTES, UploadRejected, digest, store,
                               validate)

_PDF = b"%PDF-1.4\nnot really a pdf but it starts like one\n"


def test_a_pdf_is_accepted():
    validate("resume.pdf", _PDF)          # does not raise


def test_a_non_pdf_extension_is_rejected():
    with pytest.raises(UploadRejected, match="not a PDF"):
        validate("resume.docx", _PDF)


def test_a_pdf_extension_over_something_else_is_rejected():
    """The extension is a claim; the leading bytes are the evidence."""
    with pytest.raises(UploadRejected, match="not a PDF"):
        validate("resume.pdf", b"PK\x03\x04 this is a zip")


def test_an_empty_file_says_so():
    with pytest.raises(UploadRejected, match="empty"):
        validate("resume.pdf", b"")


def test_a_file_over_the_cap_is_rejected():
    oversized = _PDF + b"x" * MAX_BYTES
    with pytest.raises(UploadRejected, match="5 MB"):
        validate("resume.pdf", oversized)


def test_digest_is_the_sha256_of_the_bytes():
    assert digest(_PDF) == hashlib.sha256(_PDF).hexdigest()


def test_store_writes_under_the_user_folder_named_by_hash(tmp_path):
    relative = store(tmp_path, user_id=7, sha256=digest(_PDF), data=_PDF)
    assert relative == f"resumes/7/{digest(_PDF)}.pdf"
    assert (tmp_path / relative).read_bytes() == _PDF


def test_the_clients_filename_never_reaches_the_path(tmp_path):
    """A crafted filename must not escape the data root — the stored name is
    the content hash, and the client's name is display only."""
    relative = store(tmp_path, user_id=7, sha256=digest(_PDF), data=_PDF)
    written = list((tmp_path / "resumes" / "7").iterdir())
    assert [p.name for p in written] == [f"{digest(_PDF)}.pdf"]
    assert ".." not in relative


def test_storing_the_same_bytes_twice_is_idempotent(tmp_path):
    first = store(tmp_path, user_id=1, sha256=digest(_PDF), data=_PDF)
    second = store(tmp_path, user_id=1, sha256=digest(_PDF), data=_PDF)
    assert first == second
    assert len(list((tmp_path / "resumes" / "1").iterdir())) == 1
