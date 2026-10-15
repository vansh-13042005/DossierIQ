
"""Named entity extraction for DossierIQ using spaCy."""

import re

import spacy


# Load the model once at import time, not on every function call.
_NLP = spacy.load("en_core_web_sm")

_REQUIRED_FIELDS = ("document_id", "filename", "text")

# Conservative fallback for organization names that spaCy misses.
# These patterns only recognize a candidate immediately before a
# relationship phrase supported by DossierIQ's relationship extractor.
_ORGANIZATION_RELATIONSHIP_PATTERNS = (
    re.compile(
        r"\b(?P<name>[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})"
        r"\s+(?=signed\s+an\s+agreement\s+with\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<name>[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})"
        r"\s+(?=signed\s+a\s+contract\s+with\b)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<name>[A-Z][A-Za-z0-9&.'-]*(?:\s+[A-Z][A-Za-z0-9&.'-]*){0,4})"
        r"\s+(?=acquired\b)",
        re.IGNORECASE,
    ),
)


def _validate_document(document: dict) -> None:
    """Check that the document is a dict with non-empty string required fields."""
    if not isinstance(document, dict):
        raise ValueError(
            f"Document must be a dictionary, got {type(document).__name__}."
        )

    for field in _REQUIRED_FIELDS:
        if field not in document:
            raise ValueError(f"Document is missing required field '{field}'.")

        value = document[field]
        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"Document field '{field}' must be a non-empty string."
            )


def _organization_fallbacks(text: str, existing_entities: list) -> list[dict]:
    """Find conservative organization candidates missed by spaCy."""
    fallback_entities = []
    existing_spans = {
        (entity.start_char, entity.end_char)
        for entity in existing_entities
    }

    for pattern in _ORGANIZATION_RELATIONSHIP_PATTERNS:
        for match in pattern.finditer(text):
            name = match.group("name").strip()
            start_char = match.start("name")
            end_char = match.end("name")

            # Do not duplicate or overlap an entity spaCy already detected.
            if any(
                start_char < end and start < end_char
                for start, end in existing_spans
            ):
                continue

            # The fallback is intended for multi-word proper names, not
            # ordinary single capitalized words.
            if len(name.split()) < 2:
                continue

            sentence = next(
                (
                    sent.text
                    for sent in _NLP(text).sents
                    if sent.start_char <= start_char < sent.end_char
                ),
                text,
            )

            fallback_entities.append(
                {
                    "entity_text": name,
                    "entity_type": "ORG",
                    "start_char": start_char,
                    "end_char": end_char,
                    "context": sentence,
                }
            )
            existing_spans.add((start_char, end_char))

    return fallback_entities


def extract_entities(document: dict) -> list[dict]:
    """Extract named entity mentions from a loaded document.

    Each mention becomes its own record; repeated mentions are kept
    separate (no deduplication or entity resolution).

    Args:
        document: A dictionary with non-empty string fields ``document_id``,
            ``filename`` and ``text`` (as returned by ``load_document()``).

    Returns:
        A list of entity mention dictionaries containing the entity text,
        type, document metadata, character offsets and sentence context.

    Raises:
        ValueError: If the document or required fields are invalid.
    """
    _validate_document(document)

    text = document["text"]
    doc = _NLP(text)

    entities = []

    for ent in doc.ents:
        entities.append(
            {
                "entity_text": ent.text,
                "entity_type": ent.label_,
                "document_id": document["document_id"],
                "filename": document["filename"],
                "start_char": ent.start_char,
                "end_char": ent.end_char,
                "context": ent.sent.text,
            }
        )

    for fallback in _organization_fallbacks(text, doc.ents):
        entities.append(
            {
                "entity_text": fallback["entity_text"],
                "entity_type": fallback["entity_type"],
                "document_id": document["document_id"],
                "filename": document["filename"],
                "start_char": fallback["start_char"],
                "end_char": fallback["end_char"],
                "context": fallback["context"],
            }
        )

    entities.sort(key=lambda entity: (entity["start_char"], entity["end_char"]))

    return entities
