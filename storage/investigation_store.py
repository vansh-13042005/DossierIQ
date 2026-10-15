"""Persist DossierIQ investigation results to SQLite.

This module only saves investigations. Retrieval is not implemented here.
The NetworkX graph in a result is never stored; it can be rebuilt from the
saved entities and relationships.

Only the Python standard library and existing project modules are used.
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path

from core.relationship_extractor import extract_relationships
from storage.database import get_connection, initialize_database

# Keys the result dictionary must contain (the output of run_investigation()).
_RESULT_KEYS = ("documents", "entities", "summary", "graph", "graph_summary")

_DOCUMENT_FIELDS: dict[str, type] = {
    "document_id": str,
    "filename": str,
    "file_type": str,
    "text": str,
    "character_count": int,
}

_ENTITY_FIELDS: dict[str, type] = {
    "entity_id": int,
    "entity_text": str,
    "entity_type": str,
    "normalized_name": str,
    "document_id": str,
    "filename": str,
    "start_char": int,
    "end_char": int,
    "context": str,
}

_RELATIONSHIP_FIELDS: dict[str, type] = {
    "source_entity_id": int,
    "target_entity_id": int,
    "relationship_type": str,
    "document_id": str,
    "filename": str,
    "evidence": str,
}


def _check_record(record: object, fields: dict[str, type], label: str) -> None:
    """Check that a record is a dict with all fields present and correctly typed."""
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a dictionary, got {type(record).__name__}.")

    for field, expected_type in fields.items():
        if field not in record:
            raise ValueError(f"{label} is missing required field '{field}'.")

        value = record[field]
        # bool is a subclass of int, so reject it explicitly.
        if not isinstance(value, expected_type) or isinstance(value, bool):
            raise ValueError(
                f"Field '{field}' of {label} must be of type "
                f"{expected_type.__name__}, got {type(value).__name__}."
            )


def _check_non_empty(record: dict, fields: tuple[str, ...], label: str) -> None:
    """Check that the named string fields are not empty or whitespace-only."""
    for field in fields:
        if not record[field].strip():
            raise ValueError(f"Field '{field}' of {label} must not be empty.")


def _validate_result(result: dict) -> dict[str, str]:
    """Validate the structure of an investigation result without modifying it.

    Returns:
        A mapping of ``document_id`` to ``filename`` for the result's documents.

    Raises:
        ValueError: If the structure, field values or cross-references are
            invalid.
    """
    if not isinstance(result, dict):
        raise ValueError(f"Result must be a dictionary, got {type(result).__name__}.")

    for key in _RESULT_KEYS:
        if key not in result:
            raise ValueError(f"Result is missing required key '{key}'.")

    for key in ("documents", "entities"):
        if not isinstance(result[key], list):
            raise ValueError(
                f"Result key '{key}' must be a list, got {type(result[key]).__name__}."
            )

    document_filenames: dict[str, str] = {}
    for index, document in enumerate(result["documents"]):
        label = f"Document at index {index}"
        _check_record(document, _DOCUMENT_FIELDS, label)
        _check_non_empty(document, ("document_id", "filename", "file_type"), label)

        if document["character_count"] < 0:
            raise ValueError(f"Field 'character_count' of {label} must not be negative.")
        if document["document_id"] in document_filenames:
            raise ValueError(
                f"Duplicate document_id '{document['document_id']}' at index {index}."
            )
        document_filenames[document["document_id"]] = document["filename"]

    entity_identity: dict[int, tuple[str, str]] = {}
    for index, mention in enumerate(result["entities"]):
        label = f"Entity at index {index}"
        _check_record(mention, _ENTITY_FIELDS, label)
        _check_non_empty(
            mention,
            ("entity_text", "entity_type", "normalized_name",
             "document_id", "filename", "context"),
            label,
        )

        if mention["entity_id"] < 1:
            raise ValueError(f"Field 'entity_id' of {label} must be a positive integer.")
        if mention["start_char"] < 0:
            raise ValueError(f"Field 'start_char' of {label} must not be negative.")
        if mention["end_char"] <= mention["start_char"]:
            raise ValueError(
                f"Field 'end_char' of {label} must be greater than 'start_char'."
            )

        document_id = mention["document_id"]
        if document_id not in document_filenames:
            raise ValueError(
                f"{label} refers to document_id '{document_id}', "
                "which is not in the result's documents."
            )
        if mention["filename"] != document_filenames[document_id]:
            raise ValueError(
                f"{label} has filename '{mention['filename']}', but document "
                f"'{document_id}' has filename '{document_filenames[document_id]}'."
            )

        identity = (mention["normalized_name"], mention["entity_type"])
        known = entity_identity.setdefault(mention["entity_id"], identity)
        if known != identity:
            raise ValueError(
                f"{label} has entity_id {mention['entity_id']} but a different "
                "normalized_name or entity_type than an earlier mention."
            )

    return document_filenames


def _validate_relationships(
    relationships: list[dict],
    entity_ids: set[int],
    document_filenames: dict[str, str],
) -> None:
    """Validate relationship records against this investigation's data.

    Raises:
        ValueError: If a record is malformed, refers to an unknown entity or
            document, or has a filename that differs from its document's.
    """
    if not isinstance(relationships, list):
        raise ValueError(
            f"Relationships must be a list, got {type(relationships).__name__}."
        )

    for index, relationship in enumerate(relationships):
        label = f"Relationship at index {index}"
        _check_record(relationship, _RELATIONSHIP_FIELDS, label)
        _check_non_empty(
            relationship,
            ("relationship_type", "document_id", "filename", "evidence"),
            label,
        )

        for field in ("source_entity_id", "target_entity_id"):
            if relationship[field] not in entity_ids:
                raise ValueError(
                    f"{label} has {field} {relationship[field]}, which is not an "
                    "entity in this investigation."
                )

        document_id = relationship["document_id"]
        if document_id not in document_filenames:
            raise ValueError(
                f"{label} refers to document_id '{document_id}', "
                "which is not in the result's documents."
            )
        if relationship["filename"] != document_filenames[document_id]:
            raise ValueError(
                f"{label} has filename '{relationship['filename']}', but document "
                f"'{document_id}' has filename '{document_filenames[document_id]}'."
            )


def save_investigation(result: dict, db_path: str | Path) -> str:
    """Save an investigation result to SQLite and return its new ID.

    The result is validated, relationships are extracted with
    ``extract_relationships()`` (called exactly once) and those relationships
    are validated, all before the database is touched. All rows are then
    written in a single transaction: if any insert fails, nothing from this
    investigation is kept. The database's foreign keys remain as a second
    line of defence.

    One ``entities`` row is written per distinct ``entity_id`` (using the
    first mention's ``normalized_name`` as ``canonical_name`` and its
    ``entity_type``); every mention is written to ``entity_mentions``. The
    graph and summaries in ``result`` are required to be present but are not
    stored, and ``result`` is not modified.

    Args:
        result: A dictionary as returned by ``run_investigation()``, with the
            keys ``documents`` (list), ``entities`` (list), ``summary``,
            ``graph`` and ``graph_summary``.
        db_path: Path to the SQLite database file (created if missing).

    Returns:
        The generated ``investigation_id`` (a UUID string).

    Raises:
        ValueError: If the result or the extracted relationships are
            malformed or inconsistent.
        sqlite3.Error: If the database cannot be initialised or written.
        OSError: If the database directory cannot be created.
    """
    document_filenames = _validate_result(result)

    documents: list[dict] = result["documents"]
    mentions: list[dict] = result["entities"]
    relationships = extract_relationships(mentions)

    # One row per distinct entity_id, in order of first appearance.
    entities: dict[int, tuple[str, str]] = {}
    for mention in mentions:
        entities.setdefault(
            mention["entity_id"], (mention["normalized_name"], mention["entity_type"])
        )

    _validate_relationships(relationships, set(entities), document_filenames)

    investigation_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc).isoformat()

    initialize_database(db_path)
    connection = get_connection(db_path)
    try:
        try:
            connection.execute("BEGIN")

            connection.execute(
                "INSERT INTO investigations (investigation_id, created_at) VALUES (?, ?)",
                (investigation_id, created_at),
            )

            connection.executemany(
                "INSERT INTO documents (investigation_id, document_id, filename, "
                "file_type, text, character_count) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (
                        investigation_id,
                        d["document_id"],
                        d["filename"],
                        d["file_type"],
                        d["text"],
                        d["character_count"],
                    )
                    for d in documents
                ],
            )

            connection.executemany(
                "INSERT INTO entities (investigation_id, entity_id, canonical_name, "
                "entity_type) VALUES (?, ?, ?, ?)",
                [
                    (investigation_id, entity_id, name, entity_type)
                    for entity_id, (name, entity_type) in entities.items()
                ],
            )

            connection.executemany(
                "INSERT INTO entity_mentions (investigation_id, entity_id, "
                "document_id, entity_text, entity_type, normalized_name, filename, "
                "start_char, end_char, context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        investigation_id,
                        m["entity_id"],
                        m["document_id"],
                        m["entity_text"],
                        m["entity_type"],
                        m["normalized_name"],
                        m["filename"],
                        m["start_char"],
                        m["end_char"],
                        m["context"],
                    )
                    for m in mentions
                ],
            )

            connection.executemany(
                "INSERT INTO relationships (investigation_id, source_entity_id, "
                "target_entity_id, relationship_type, document_id, filename, "
                "evidence) VALUES (?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        investigation_id,
                        r["source_entity_id"],
                        r["target_entity_id"],
                        r["relationship_type"],
                        r["document_id"],
                        r["filename"],
                        r["evidence"],
                    )
                    for r in relationships
                ],
            )

            connection.commit()
        except BaseException:
            # Undo every insert from this investigation, then re-raise the
            # original error.
            if connection.in_transaction:
                connection.rollback()
            raise
    finally:
        connection.close()

    return investigation_id