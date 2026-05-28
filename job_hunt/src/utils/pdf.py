"""pdfminer.six wrapper — extract plain text from a PDF file."""
from pathlib import Path


def extract_text(pdf_path: str | Path) -> str:
    """Return the plain text content of a PDF.

    Raises FileNotFoundError if the file does not exist.
    Raises ImportError if pdfminer.six is not installed.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    from pdfminer.high_level import extract_text as _extract
    return _extract(str(pdf_path))
