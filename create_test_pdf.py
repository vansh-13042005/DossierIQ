"""Create data/documents/sample.pdf for testing the DossierIQ PDF loader."""

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUTPUT_PATH = Path("data") / "documents" / "sample.pdf"
TEXT = "Orion Systems signed an agreement with Delta Research in Pune on 12 June."


def create_sample_pdf() -> None:
    """Write a single-page PDF containing the sample sentence."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    pdf = canvas.Canvas(str(OUTPUT_PATH), pagesize=A4)
    _, height = A4
    pdf.setFont("Helvetica", 12)
    pdf.drawString(72, height - 72, TEXT)
    pdf.save()

    print(f"Created {OUTPUT_PATH}")


if __name__ == "__main__":
    create_sample_pdf()