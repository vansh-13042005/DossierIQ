
from pathlib import Path
from uuid import UUID

from core.document_loader import load_text_file


sample_path = Path("data/documents/sample.txt")

document = load_text_file(str(sample_path))

assert document["filename"] == "sample.txt"
assert document["file_type"] == "txt"
assert document["text"].startswith("Orion Systems signed an agreement")
assert document["character_count"] == len(document["text"])
UUID(document["document_id"])

print("Document loaded successfully!")
print(f"Filename: {document['filename']}")
print(f"Character count: {document['character_count']}")
print(f"Document ID: {document['document_id']}")
