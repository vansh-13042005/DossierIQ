
"""Read-only retrieval utilities for saved DossierIQ investigations.

This module retrieves previously saved investigation records from SQLite.
It never creates or initializes a database, and it does not modify stored
records. Connections are always closed, including when a query fails.
"""

import sqlite3
from pathlib import Path

from storage.database import get_connection


class InvestigationNotFoundError(LookupError):
    """Raised when a requested investigation ID does not exist."""

    def __init__(self, investigation_id: str) -> None:
        self.investigation_id = investigation_id
        super().__init__(
            f"Investigation not found: '{investigation_id}'."
        )


def _validate_arguments(
    investigation_id: str,
    db_path: str | Path,
) -> Path:
    """Validate retrieval arguments before accessing the filesystem."""
    if not isinstance(investigation_id, str):
        raise ValueError(
            "investigation_id must be a string, "
            f"got {type(investigation_id).__name__}."
        )

    if not investigation_id.strip():
        raise ValueError("investigation_id must not be empty.")

    if not isinstance(db_path, (str, Path)):
        raise ValueError(
            f"db_path must be a string or Path, got {type(db_path).__name__}."
        )

    if not str(db_path).strip():
        raise ValueError("db_path must not be empty.")

    if str(db_path) == ":memory:":
        raise ValueError(
            "Retrieval requires a persistent database file; "
            "':memory:' cannot contain a previously saved investigation."
        )

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Database file not found: '{path}'. "
            "Retrieval does not create databases."
        )

    return path


def _rows_as_dicts(
    connection: sqlite3.Connection,
    query: str,
    investigation_id: str,
) -> list[dict]:
    """Execute a parameterized investigation-scoped query."""
    rows = connection.execute(query, (investigation_id,)).fetchall()
    return [dict(row) for row in rows]


def get_investigation(
    investigation_id: str,
    db_path: str | Path,
) -> dict:
    """Retrieve an investigation and its associated records.

    Returns plain dictionaries and lists. Storage-only row IDs are omitted
    from mentions and relationships.

    Raises:
        ValueError: If an argument is invalid.
        FileNotFoundError: If the database file does not exist or is a
            directory.
        InvestigationNotFoundError: If the ID is not present in the database.
        sqlite3.Error: If SQLite reports a database or query error.
    """
    path = _validate_arguments(investigation_id, db_path)
    connection = get_connection(path)

    try:
        connection.execute("BEGIN")

        investigation_row = connection.execute(
            """
            SELECT investigation_id, created_at
            FROM investigations
            WHERE investigation_id = ?
            """,
            (investigation_id,),
        ).fetchone()

        if investigation_row is None:
            raise InvestigationNotFoundError(investigation_id)

        documents = _rows_as_dicts(
            connection,
            """
            SELECT document_id, filename, file_type, text, character_count
            FROM documents
            WHERE investigation_id = ?
            ORDER BY rowid
            """,
            investigation_id,
        )

        entities = _rows_as_dicts(
            connection,
            """
            SELECT entity_id, canonical_name, entity_type
            FROM entities
            WHERE investigation_id = ?
            ORDER BY entity_id
            """,
            investigation_id,
        )

        entity_mentions = _rows_as_dicts(
            connection,
            """
            SELECT entity_id, entity_text, entity_type, normalized_name,
                   document_id, filename, start_char, end_char, context
            FROM entity_mentions
            WHERE investigation_id = ?
            ORDER BY mention_id
            """,
            investigation_id,
        )

        relationships = _rows_as_dicts(
            connection,
            """
            SELECT source_entity_id, target_entity_id, relationship_type,
                   document_id, filename, evidence
            FROM relationships
            WHERE investigation_id = ?
            ORDER BY relationship_id
            """,
            investigation_id,
        )

        return {
            "investigation_id": investigation_row["investigation_id"],
            "created_at": investigation_row["created_at"],
            "documents": documents,
            "entities": entities,
            "entity_mentions": entity_mentions,
            "relationships": relationships,
        }
    finally:
        connection.close()


def list_investigations(db_path: str | Path) -> list[dict]:
    """List saved investigations, newest first.

    Each returned record contains only ``investigation_id`` and ``created_at``.
    An initialized database with no saved investigations returns an empty list.

    Raises:
        ValueError: If the database path is invalid.
        FileNotFoundError: If the database file does not exist or is a
            directory.
        sqlite3.Error: If SQLite reports a database or query error.
    """
    if not isinstance(db_path, (str, Path)):
        raise ValueError(
            f"db_path must be a string or Path, got {type(db_path).__name__}."
        )

    if not str(db_path).strip():
        raise ValueError("db_path must not be empty.")

    if str(db_path) == ":memory:":
        raise ValueError(
            "Retrieval requires a persistent database file; "
            "':memory:' cannot contain saved investigations."
        )

    path = Path(db_path)
    if not path.is_file():
        raise FileNotFoundError(
            f"Database file not found: '{path}'. "
            "Retrieval does not create databases."
        )

    connection = get_connection(path)
    try:
        rows = connection.execute(
            """
            SELECT investigation_id, created_at
            FROM investigations
            ORDER BY created_at DESC, investigation_id ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()
