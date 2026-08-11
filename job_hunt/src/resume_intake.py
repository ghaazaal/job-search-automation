"""Taking a resume file in.

Validation lives here rather than in the route, so the rules can be tested
without building a request. PDF only, because pdfminer is the only extractor
present — a .docx has to be refused with a message rather than accepted and
failed later, halfway through a parse.

The client's filename is never used to build a path. The stored name is the
content hash, so a filename of `../../secrets` writes exactly where every
other upload writes.
"""
import hashlib
import re
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024
_PDF_MAGIC = b"%PDF-"
_HEX_DIGEST = re.compile(r"^[0-9a-f]{64}$")


class UploadRejected(Exception):
    """The file cannot be accepted. The message is shown to the user."""


def validate(filename: str, data: bytes) -> None:
    """Raise UploadRejected unless this is a PDF within the size cap."""
    if not data:
        raise UploadRejected("That file is empty.")
    if len(data) > MAX_BYTES:
        raise UploadRejected(
            f"That file is larger than {MAX_BYTES // (1024 * 1024)} MB. "
            "Export a smaller PDF and try again.")
    if not filename.lower().endswith(".pdf") or not data.startswith(_PDF_MAGIC):
        raise UploadRejected(
            "That is not a PDF. Only PDF resumes can be read at the moment.")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def store(data_root: Path | str, user_id: int, sha256: str,
          data: bytes) -> str:
    """Write the PDF under the data root. Returns the path relative to it."""
    if not _HEX_DIGEST.match(sha256):
        raise ValueError(f"not a sha256 hex digest: {sha256!r}")
    relative = f"resumes/{user_id}/{sha256}.pdf"
    target = Path(data_root) / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return relative
