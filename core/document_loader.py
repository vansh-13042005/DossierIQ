
"""Document loading utilities for DossierIQ (TXT and PDF)."""

import uuid
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError


def _check_file(path: Path, expected_suffix: str) -> None:
    """Validate that the path is an existing file with the expected extension."""
    if not path.is_file():
        raise FileNotFoundError(
            f"File not found: '{path}'. Please check the path."
        )

    if path.suffix.lower() != expected_suffix:
        raise ValueError(
            f"Unsupported file extension '{path.suffix}' for '{path.name}'. "
            f"Only '{expected_suffix}' files are supported by this loader."
        )


def _build_result(path: Path, file_type: str, text: str) -> dict:
    """Build the standard document dictionary with a fresh UUID."""
    return {
        "document_id": str(uuid.uuid4()),
        "filename": path.name,
        "file_type": file_type,
        "text": text,
        "character_count": len(text),
    }


def load_text_file(file_path: str) -> dict:
    """Load a UTF-8 text file and return its content with metadata."""
    path = Path(file_path)
    _check_file(path, ".txt")

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ValueError(
            f"Could not decode '{path.name}' as UTF-8. "
            "The file may use a different encoding or contain invalid text."
        ) from error

    return _build_result(path, "txt", text)


def load_pdf_file(file_path: str) -> dict:
    """Extract text from a PDF and return it with metadata."""
    path = Path(file_path)
    _check_file(path, ".pdf")

    try:
        reader = PdfReader(str(path))
        page_texts = [
            page.extract_text() or ""
            for page in reader.pages
        ]
    except (PdfReadError, OSError) as error:
        raise ValueError(
            f"Could not read '{path.name}' as a PDF. "
            "The file may be corrupted, encrypted, or invalid."
        ) from error

    text = "\n".join(page_texts)

    if not text.strip():
        raise ValueError(
            f"No extractable text found in '{path.name}'. "
            "It may be scanned or image-only and require OCR."
        )

    return _build_result(path, "pdf", text)


def load_document(file_path: str) -> dict:
    """Load a supported document based on its file extension."""
    path = Path(file_path)

    if not path.is_file():
        raise FileNotFoundError(
            f"File not found: '{path}'. Please check the path."
        )

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return load_text_file(str(path))

    if suffix == ".pdf":
        return load_pdf_file(str(path))

    raise ValueError(
        f"Unsupported file extension '{path.suffix}' for '{path.name}'. "
        "Supported formats are '.txt' and '.pdf'."
    )
