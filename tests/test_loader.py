"""Tests for core/document_loader.py (standard-library unittest only).

Run from the project root with:
    python -m unittest discover -v
or:
    python -m unittest tests.test_loader -v

These tests also work with pytest later, because pytest can run unittest cases.
"""

import sys
import tempfile
import unittest
import uuid
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.document_loader import (  # noqa: E402
    load_document,
    load_pdf_file,
    load_text_file,
)

SAMPLE_FILE = PROJECT_ROOT / "data" / "documents" / "sample.txt"
PDF_SENTENCE = "Orion Systems signed an agreement with Delta Research in Pune on 12 June."


def create_text_pdf(path: Path, text: str = PDF_SENTENCE) -> None:
    """Create a single-page PDF with extractable text."""
    pdf = canvas.Canvas(str(path), pagesize=A4)
    _, height = A4
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 72, text)
    pdf.save()


def create_blank_pdf(path: Path) -> None:
    """Create a single-page PDF with no text at all."""
    pdf = canvas.Canvas(str(path), pagesize=A4)
    pdf.showPage()
    pdf.save()


class TestLoadTextFile(unittest.TestCase):
    """Tests for load_text_file()."""

    def test_loads_sample_file_successfully(self) -> None:
        result = load_text_file(str(SAMPLE_FILE))

        self.assertIsInstance(result, dict)
        self.assertIsInstance(result["text"], str)
        self.assertGreater(len(result["text"]), 0)

    def test_returns_all_expected_metadata_fields(self) -> None:
        result = load_text_file(str(SAMPLE_FILE))

        expected_keys = {
            "document_id",
            "filename",
            "file_type",
            "text",
            "character_count",
        }
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result["filename"], "sample.txt")
        self.assertEqual(result["file_type"], "txt")

    def test_character_count_matches_extracted_text(self) -> None:
        result = load_text_file(str(SAMPLE_FILE))

        self.assertIsInstance(result["character_count"], int)
        self.assertEqual(result["character_count"], len(result["text"]))

    def test_document_id_is_valid_uuid(self) -> None:
        result = load_text_file(str(SAMPLE_FILE))

        parsed = uuid.UUID(result["document_id"])  # raises ValueError if invalid
        self.assertEqual(str(parsed), result["document_id"])

    def test_missing_file_raises_file_not_found_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "does_not_exist.txt"

            with self.assertRaises(FileNotFoundError):
                load_text_file(str(missing_path))

    def test_unsupported_extension_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = Path(temp_dir) / "data.csv"
            bad_file.write_text("a,b,c", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_text_file(str(bad_file))

    def test_two_loads_generate_different_document_ids(self) -> None:
        first = load_text_file(str(SAMPLE_FILE))
        second = load_text_file(str(SAMPLE_FILE))

        self.assertNotEqual(first["document_id"], second["document_id"])


class TestLoadPdfFile(unittest.TestCase):
    """Tests for load_pdf_file()."""

    def test_extracts_expected_sentence_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "report.pdf"
            create_text_pdf(pdf_path)

            result = load_pdf_file(str(pdf_path))

        self.assertIn(PDF_SENTENCE, result["text"])
        self.assertEqual(result["filename"], "report.pdf")
        self.assertEqual(result["file_type"], "pdf")
        self.assertEqual(result["character_count"], len(result["text"]))
        uuid.UUID(result["document_id"])  # raises ValueError if invalid

    def test_pdf_extension_check_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "REPORT.PDF"
            create_text_pdf(pdf_path)

            result = load_pdf_file(str(pdf_path))

        self.assertEqual(result["file_type"], "pdf")

    def test_missing_pdf_raises_file_not_found_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.pdf"

            with self.assertRaises(FileNotFoundError):
                load_pdf_file(str(missing_path))

    def test_wrong_extension_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "notes.txt"
            txt_path.write_text("hello", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_pdf_file(str(txt_path))

    def test_invalid_pdf_raises_clear_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_pdf = Path(temp_dir) / "fake.pdf"
            fake_pdf.write_text("This is not a real PDF.", encoding="utf-8")

            with self.assertRaises(ValueError) as context:
                load_pdf_file(str(fake_pdf))

        self.assertIn("fake.pdf", str(context.exception))
        self.assertIsNotNone(context.exception.__cause__)

    def test_blank_pdf_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            blank_path = Path(temp_dir) / "blank.pdf"
            create_blank_pdf(blank_path)

            with self.assertRaises(ValueError) as context:
                load_pdf_file(str(blank_path))

        self.assertIn("No extractable text", str(context.exception))

    def test_two_pdf_loads_generate_different_document_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "report.pdf"
            create_text_pdf(pdf_path)

            first = load_pdf_file(str(pdf_path))
            second = load_pdf_file(str(pdf_path))

        self.assertNotEqual(first["document_id"], second["document_id"])


class TestLoadDocument(unittest.TestCase):
    """Tests for load_document()."""

    def test_dispatches_txt_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "notes.txt"
            txt_path.write_text("Plain text content.", encoding="utf-8")

            result = load_document(str(txt_path))

        self.assertEqual(result["file_type"], "txt")
        self.assertEqual(result["filename"], "notes.txt")
        self.assertEqual(result["text"], "Plain text content.")

    def test_dispatches_pdf_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            pdf_path = Path(temp_dir) / "report.pdf"
            create_text_pdf(pdf_path)

            result = load_document(str(pdf_path))

        self.assertEqual(result["file_type"], "pdf")
        self.assertEqual(result["filename"], "report.pdf")
        self.assertIn(PDF_SENTENCE, result["text"])

    def test_dispatch_is_case_insensitive(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            txt_path = Path(temp_dir) / "NOTES.TXT"
            txt_path.write_text("Upper-case extension.", encoding="utf-8")

            result = load_document(str(txt_path))

        self.assertEqual(result["file_type"], "txt")

    def test_missing_file_raises_file_not_found_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "missing.pdf"

            with self.assertRaises(FileNotFoundError):
                load_document(str(missing_path))

    def test_unsupported_extension_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bad_file = Path(temp_dir) / "data.csv"
            bad_file.write_text("a,b,c", encoding="utf-8")

            with self.assertRaises(ValueError) as context:
                load_document(str(bad_file))

        self.assertIn(".csv", str(context.exception))

    def test_invalid_pdf_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_pdf = Path(temp_dir) / "fake.pdf"
            fake_pdf.write_text("Not a PDF.", encoding="utf-8")

            with self.assertRaises(ValueError):
                load_document(str(fake_pdf))

    def test_blank_pdf_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            blank_path = Path(temp_dir) / "blank.pdf"
            create_blank_pdf(blank_path)

            with self.assertRaises(ValueError):
                load_document(str(blank_path))


if __name__ == "__main__":
    unittest.main()