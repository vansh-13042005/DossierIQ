"""SQLite connection management and schema initialisation for DossierIQ.

This module only opens connections and creates the database schema. It does
not save or retrieve investigations. Nothing touches the filesystem at import
time; a database file is created only when the caller invokes
``get_connection()`` or ``initialize_database()`` with a path.

Only the Python standard library is used.
"""

import sqlite3
from pathlib import Path

# The whole script runs in one transaction, so a failure part-way through
# leaves no half-created schema. Every statement is idempotent.
_SCHEMA_SQL = """
BEGIN;

CREATE TABLE IF NOT EXISTS investigations (
    investigation_id TEXT PRIMARY KEY,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS documents (
    investigation_id TEXT    NOT NULL,
    document_id      TEXT    NOT NULL,
    filename         TEXT    NOT NULL,
    file_type        TEXT    NOT NULL,
    text             TEXT    NOT NULL,
    character_count  INTEGER NOT NULL CHECK (character_count >= 0),
    PRIMARY KEY (investigation_id, document_id),
    FOREIGN KEY (investigation_id)
        REFERENCES investigations (investigation_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entities (
    investigation_id TEXT    NOT NULL,
    entity_id        INTEGER NOT NULL,
    canonical_name   TEXT    NOT NULL,
    entity_type      TEXT    NOT NULL,
    PRIMARY KEY (investigation_id, entity_id),
    FOREIGN KEY (investigation_id)
        REFERENCES investigations (investigation_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS entity_mentions (
    mention_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id TEXT    NOT NULL,
    entity_id        INTEGER NOT NULL,
    document_id      TEXT    NOT NULL,
    entity_text      TEXT    NOT NULL,
    entity_type      TEXT    NOT NULL,
    normalized_name  TEXT    NOT NULL,
    filename         TEXT    NOT NULL,
    start_char       INTEGER NOT NULL CHECK (start_char >= 0),
    end_char         INTEGER NOT NULL CHECK (end_char > start_char),
    context          TEXT    NOT NULL,
    FOREIGN KEY (investigation_id, entity_id)
        REFERENCES entities (investigation_id, entity_id)
        ON DELETE CASCADE,
    FOREIGN KEY (investigation_id, document_id)
        REFERENCES documents (investigation_id, document_id)
        ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS relationships (
    relationship_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    investigation_id   TEXT    NOT NULL,
    source_entity_id   INTEGER NOT NULL,
    target_entity_id   INTEGER NOT NULL,
    relationship_type  TEXT    NOT NULL,
    document_id        TEXT    NOT NULL,
    filename           TEXT    NOT NULL,
    evidence           TEXT    NOT NULL,
    FOREIGN KEY (investigation_id, source_entity_id)
        REFERENCES entities (investigation_id, entity_id)
        ON DELETE CASCADE,
    FOREIGN KEY (investigation_id, target_entity_id)
        REFERENCES entities (investigation_id, entity_id)
        ON DELETE CASCADE,
    FOREIGN KEY (investigation_id, document_id)
        REFERENCES documents (investigation_id, document_id)
        ON DELETE CASCADE
);

-- Entities and documents are already indexed by their composite primary keys
-- (investigation first). These cover the child-table foreign keys and the
-- most likely lookups.
CREATE INDEX IF NOT EXISTS idx_entities_investigation_type
    ON entities (investigation_id, entity_type);

CREATE INDEX IF NOT EXISTS idx_mentions_entity
    ON entity_mentions (investigation_id, entity_id);

CREATE INDEX IF NOT EXISTS idx_mentions_document
    ON entity_mentions (investigation_id, document_id);

CREATE INDEX IF NOT EXISTS idx_relationships_source
    ON relationships (investigation_id, source_entity_id);

CREATE INDEX IF NOT EXISTS idx_relationships_target
    ON relationships (investigation_id, target_entity_id);

CREATE INDEX IF NOT EXISTS idx_relationships_document
    ON relationships (investigation_id, document_id);

COMMIT;
"""


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with foreign-key enforcement enabled.

    SQLite does not enforce foreign keys unless ``PRAGMA foreign_keys`` is
    turned on for each connection, so every connection should be opened
    through this function. Rows are returned as ``sqlite3.Row`` objects.

    The caller owns the returned connection and must close it. This function
    does not create parent directories; ``initialize_database()`` does.

    ``":memory:"`` is allowed here, but each such connection is a separate,
    empty database that disappears when the connection is closed.

    Args:
        db_path: Path to the SQLite database file, or ``":memory:"``.

    Returns:
        An open ``sqlite3.Connection``.

    Raises:
        sqlite3.Error: If the database cannot be opened or configured.
    """
    connection = sqlite3.connect(str(db_path))
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error:
        connection.close()
        raise
    return connection


def initialize_database(db_path: str | Path) -> None:
    """Create the parent directory and all tables and indexes if missing.

    Safe to call repeatedly: existing tables, indexes and data are left
    untouched. The schema is created in a single transaction. If creation
    fails, any open transaction is rolled back and the original exception is
    re-raised. The connection is always closed.

    In-memory databases are rejected: this function closes its connection
    before returning, which would destroy an in-memory database immediately.
    To use an in-memory database, open it with ``get_connection(":memory:")``
    and create the schema on that same connection.

    Args:
        db_path: Path to the SQLite database file.

    Raises:
        ValueError: If ``db_path`` is ``":memory:"``.
        OSError: If the parent directory cannot be created.
        sqlite3.Error: If the database cannot be opened or the schema cannot
            be created.
    """
    if str(db_path) == ":memory:":
        raise ValueError(
            "initialize_database() does not support ':memory:' because the "
            "connection is closed before returning, which would discard the "
            "database. Use a file path, or call get_connection(':memory:') "
            "and create the schema on that connection."
        )

    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    connection = get_connection(db_path)
    try:
        try:
            connection.executescript(_SCHEMA_SQL)
        except Exception:
            # The script's BEGIN may have started a transaction that was
            # never committed. Roll it back if one is open, then re-raise
            # the original error.
            if connection.in_transaction:
                try:
                    connection.rollback()
                except sqlite3.Error:
                    pass  # Keep the original exception; don't mask it.
            raise
    finally:
        connection.close()