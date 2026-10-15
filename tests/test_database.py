"""Tests for storage/database.py (standard-library unittest and tempfile only).

Run from the project root with:
    python -m unittest tests.test_database -v
or:
    python -m unittest discover -v
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from storage.database import get_connection, initialize_database  # noqa: E402

EXPECTED_TABLES = {
    "investigations",
    "documents",
    "entities",
    "entity_mentions",
    "relationships",
}
CREATED_AT = "2026-01-01T00:00:00+00:00"


# --- Helpers -----------------------------------------------------------------
# All values go through parameters. Table names in count_rows() come only from
# the fixed EXPECTED_TABLES set, never from outside input.

def add_investigation(conn: sqlite3.Connection, investigation_id: str = "inv-1") -> None:
    conn.execute(
        "INSERT INTO investigations (investigation_id, created_at) VALUES (?, ?)",
        (investigation_id, CREATED_AT),
    )


def add_document(
    conn: sqlite3.Connection,
    investigation_id: str = "inv-1",
    document_id: str = "doc-1",
    character_count: int = 40,
) -> None:
    conn.execute(
        "INSERT INTO documents (investigation_id, document_id, filename, "
        "file_type, text, character_count) VALUES (?, ?, ?, ?, ?, ?)",
        (investigation_id, document_id, "a.txt", "txt", "Some text.", character_count),
    )


def add_entity(
    conn: sqlite3.Connection,
    investigation_id: str = "inv-1",
    entity_id: int = 1,
    canonical_name: str = "orion systems",
    entity_type: str = "ORG",
) -> None:
    conn.execute(
        "INSERT INTO entities (investigation_id, entity_id, canonical_name, "
        "entity_type) VALUES (?, ?, ?, ?)",
        (investigation_id, entity_id, canonical_name, entity_type),
    )


def add_mention(
    conn: sqlite3.Connection,
    investigation_id: str = "inv-1",
    entity_id: int = 1,
    document_id: str = "doc-1",
    start_char: int = 0,
    end_char: int = 13,
) -> None:
    conn.execute(
        "INSERT INTO entity_mentions (investigation_id, entity_id, document_id, "
        "entity_text, entity_type, normalized_name, filename, start_char, "
        "end_char, context) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            investigation_id, entity_id, document_id, "Orion Systems", "ORG",
            "orion systems", "a.txt", start_char, end_char,
            "Orion Systems acquired Delta Research.",
        ),
    )


def add_relationship(
    conn: sqlite3.Connection,
    investigation_id: str = "inv-1",
    source_entity_id: int = 1,
    target_entity_id: int = 2,
    document_id: str = "doc-1",
) -> None:
    conn.execute(
        "INSERT INTO relationships (investigation_id, source_entity_id, "
        "target_entity_id, relationship_type, document_id, filename, evidence) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            investigation_id, source_entity_id, target_entity_id, "ACQUIRED",
            document_id, "a.txt", "Orion Systems acquired Delta Research.",
        ),
    )


def populate_investigation(conn: sqlite3.Connection, investigation_id: str) -> None:
    """Insert one complete investigation (using the same local IDs each time)."""
    add_investigation(conn, investigation_id)
    add_document(conn, investigation_id, "doc-1")
    add_entity(conn, investigation_id, 1, "orion systems", "ORG")
    add_entity(conn, investigation_id, 2, "delta research", "ORG")
    add_mention(conn, investigation_id, 1, "doc-1", 0, 13)
    add_mention(conn, investigation_id, 2, "doc-1", 23, 37)
    add_relationship(conn, investigation_id, 1, 2, "doc-1")
    conn.commit()


def count_rows(
    conn: sqlite3.Connection, table: str, investigation_id: str | None = None
) -> int:
    assert table in EXPECTED_TABLES
    if investigation_id is None:
        row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    else:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE investigation_id = ?",
            (investigation_id,),
        ).fetchone()
    return row["n"]


class DatabaseTestCase(unittest.TestCase):
    """Base class: a temporary directory and tracked connections."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        # Cleanups run last-in-first-out, so connections registered later are
        # closed before the directory is deleted (required on Windows).
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db_path = self.temp_path / "dossieriq.db"

    def open_connection(self, path: str | Path | None = None) -> sqlite3.Connection:
        connection = get_connection(self.db_path if path is None else path)
        self.addCleanup(connection.close)
        return connection

    def open_initialized(self) -> sqlite3.Connection:
        initialize_database(self.db_path)
        return self.open_connection()


class TestInitializeDatabase(DatabaseTestCase):
    """Schema creation."""

    def test_creates_all_five_tables(self) -> None:
        initialize_database(self.db_path)
        connection = self.open_connection()

        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

        self.assertTrue(EXPECTED_TABLES <= {row["name"] for row in rows})

    def test_creates_database_file_and_missing_parent_directories(self) -> None:
        nested_path = self.temp_path / "storage" / "nested" / "dossieriq.db"

        initialize_database(nested_path)

        self.assertTrue(nested_path.is_file())

    def test_repeated_calls_are_safe(self) -> None:
        for _ in range(3):
            initialize_database(self.db_path)

        connection = self.open_connection()
        rows = connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
        self.assertTrue(EXPECTED_TABLES <= {row["name"] for row in rows})

    def test_repeated_calls_preserve_existing_records(self) -> None:
        connection = self.open_initialized()
        populate_investigation(connection, "inv-1")
        connection.close()

        initialize_database(self.db_path)
        initialize_database(self.db_path)

        connection = self.open_connection()
        for table in EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertGreater(count_rows(connection, table, "inv-1"), 0)
        self.assertEqual(count_rows(connection, "entity_mentions", "inv-1"), 2)

    def test_memory_database_is_rejected_with_value_error(self) -> None:
        with self.assertRaises(ValueError) as context:
            initialize_database(":memory:")

        self.assertIn(":memory:", str(context.exception))


class TestGetConnection(DatabaseTestCase):
    """Connection configuration."""

    def test_rows_are_sqlite_row_objects(self) -> None:
        connection = self.open_initialized()
        add_investigation(connection, "inv-1")
        connection.commit()

        row = connection.execute("SELECT * FROM investigations").fetchone()

        self.assertIsInstance(row, sqlite3.Row)
        self.assertEqual(row["investigation_id"], "inv-1")
        self.assertEqual(row["created_at"], CREATED_AT)

    def test_foreign_keys_are_enabled(self) -> None:
        connection = self.open_initialized()

        row = connection.execute("PRAGMA foreign_keys").fetchone()

        self.assertEqual(row[0], 1)

    def test_foreign_keys_are_enabled_on_every_connection(self) -> None:
        initialize_database(self.db_path)

        for _ in range(2):
            connection = self.open_connection()
            self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)


class TestMemoryConnection(DatabaseTestCase):
    """get_connection(':memory:') works while the connection stays open."""

    def test_memory_connection_can_create_and_query_tables(self) -> None:
        connection = self.open_connection(":memory:")

        connection.execute("CREATE TABLE sample (name TEXT NOT NULL)")
        connection.execute("INSERT INTO sample (name) VALUES (?)", ("Orion",))
        row = connection.execute("SELECT name FROM sample").fetchone()

        self.assertIsInstance(row, sqlite3.Row)
        self.assertEqual(row["name"], "Orion")

    def test_memory_connection_enables_foreign_keys(self) -> None:
        connection = self.open_connection(":memory:")

        self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)

    def test_separate_memory_connections_are_separate_databases(self) -> None:
        first = self.open_connection(":memory:")
        second = self.open_connection(":memory:")

        first.execute("CREATE TABLE sample (name TEXT)")

        with self.assertRaises(sqlite3.OperationalError):
            second.execute("SELECT * FROM sample")


class TestForeignKeys(DatabaseTestCase):
    """Parent records must exist, within the same investigation."""

    def test_child_records_with_missing_parents_are_rejected(self) -> None:
        connection = self.open_initialized()
        cases = {
            "document without investigation": lambda: add_document(connection, "missing"),
            "entity without investigation": lambda: add_entity(connection, "missing"),
        }
        for label, insert in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError):
                    insert()

        add_investigation(connection, "inv-1")
        add_document(connection, "inv-1", "doc-1")
        add_entity(connection, "inv-1", 1)
        cases = {
            "mention with missing entity": lambda: add_mention(connection, entity_id=99),
            "mention with missing document": lambda: add_mention(connection, document_id="nope"),
            "relationship with missing source": lambda: add_relationship(
                connection, source_entity_id=99, target_entity_id=1),
            "relationship with missing target": lambda: add_relationship(
                connection, source_entity_id=1, target_entity_id=99),
            "relationship with missing document": lambda: add_relationship(
                connection, source_entity_id=1, target_entity_id=1, document_id="nope"),
        }
        for label, insert in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError):
                    insert()

    def test_same_document_and_entity_ids_are_allowed_in_different_investigations(self) -> None:
        connection = self.open_initialized()

        populate_investigation(connection, "inv-1")
        populate_investigation(connection, "inv-2")

        self.assertEqual(count_rows(connection, "documents"), 2)
        self.assertEqual(count_rows(connection, "entities"), 4)

    def test_duplicate_primary_keys_in_one_investigation_are_rejected(self) -> None:
        connection = self.open_initialized()
        populate_investigation(connection, "inv-1")

        with self.assertRaises(sqlite3.IntegrityError):
            add_document(connection, "inv-1", "doc-1")
        with self.assertRaises(sqlite3.IntegrityError):
            add_entity(connection, "inv-1", 1)

    def test_repeated_mentions_of_one_entity_are_preserved(self) -> None:
        connection = self.open_initialized()
        add_investigation(connection, "inv-1")
        add_document(connection, "inv-1", "doc-1")
        add_entity(connection, "inv-1", 1)

        add_mention(connection, start_char=0, end_char=13)
        add_mention(connection, start_char=50, end_char=63)
        add_mention(connection, start_char=50, end_char=63)  # identical span is allowed

        self.assertEqual(count_rows(connection, "entity_mentions", "inv-1"), 3)

    def test_parallel_relationships_are_preserved(self) -> None:
        connection = self.open_initialized()
        populate_investigation(connection, "inv-1")

        add_relationship(connection, "inv-1", 1, 2, "doc-1")  # same edge again

        self.assertEqual(count_rows(connection, "relationships", "inv-1"), 2)

    def _two_investigations(self) -> sqlite3.Connection:
        """inv-1 has entity 1 / doc-a; inv-2 has entity 2 / doc-b."""
        connection = self.open_initialized()
        add_investigation(connection, "inv-1")
        add_investigation(connection, "inv-2")
        add_document(connection, "inv-1", "doc-a")
        add_document(connection, "inv-2", "doc-b")
        add_entity(connection, "inv-1", 1)
        add_entity(connection, "inv-2", 2)
        return connection

    def test_mention_cannot_use_entity_from_another_investigation(self) -> None:
        connection = self._two_investigations()

        with self.assertRaises(sqlite3.IntegrityError):
            add_mention(connection, "inv-1", entity_id=2, document_id="doc-a")

    def test_mention_cannot_use_document_from_another_investigation(self) -> None:
        connection = self._two_investigations()

        with self.assertRaises(sqlite3.IntegrityError):
            add_mention(connection, "inv-1", entity_id=1, document_id="doc-b")

    def test_mention_within_one_investigation_is_accepted(self) -> None:
        connection = self._two_investigations()

        add_mention(connection, "inv-1", entity_id=1, document_id="doc-a")

        self.assertEqual(count_rows(connection, "entity_mentions", "inv-1"), 1)

    def test_relationship_cannot_cross_investigations(self) -> None:
        connection = self._two_investigations()
        add_entity(connection, "inv-1", 3)
        cases = {
            "source from other investigation": dict(
                source_entity_id=2, target_entity_id=3, document_id="doc-a"),
            "target from other investigation": dict(
                source_entity_id=1, target_entity_id=2, document_id="doc-a"),
            "document from other investigation": dict(
                source_entity_id=1, target_entity_id=3, document_id="doc-b"),
        }
        for label, arguments in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(sqlite3.IntegrityError):
                    add_relationship(connection, "inv-1", **arguments)

        add_relationship(connection, "inv-1", 1, 3, "doc-a")  # valid control
        self.assertEqual(count_rows(connection, "relationships", "inv-1"), 1)


class TestCascadeDelete(DatabaseTestCase):
    """Deleting an investigation removes everything beneath it."""

    def test_deleting_investigation_cascades_to_all_related_records(self) -> None:
        connection = self.open_initialized()
        populate_investigation(connection, "inv-1")
        populate_investigation(connection, "inv-2")
        for table in EXPECTED_TABLES:
            self.assertGreater(count_rows(connection, table, "inv-1"), 0)

        connection.execute("DELETE FROM investigations WHERE investigation_id = ?", ("inv-1",))
        connection.commit()

        for table in EXPECTED_TABLES:
            with self.subTest(table=table):
                self.assertEqual(count_rows(connection, table, "inv-1"), 0)

    def test_other_investigations_are_untouched_by_cascade(self) -> None:
        connection = self.open_initialized()
        populate_investigation(connection, "inv-1")
        populate_investigation(connection, "inv-2")

        connection.execute("DELETE FROM investigations WHERE investigation_id = ?", ("inv-1",))
        connection.commit()

        self.assertEqual(count_rows(connection, "investigations"), 1)
        self.assertEqual(count_rows(connection, "documents", "inv-2"), 1)
        self.assertEqual(count_rows(connection, "entities", "inv-2"), 2)
        self.assertEqual(count_rows(connection, "entity_mentions", "inv-2"), 2)
        self.assertEqual(count_rows(connection, "relationships", "inv-2"), 1)


class TestCheckConstraints(DatabaseTestCase):
    """Invalid numeric values are rejected."""

    def setUp(self) -> None:
        super().setUp()
        self.connection = self.open_initialized()
        add_investigation(self.connection, "inv-1")
        add_document(self.connection, "inv-1", "doc-1")
        add_entity(self.connection, "inv-1", 1)

    def test_negative_character_count_is_rejected(self) -> None:
        with self.assertRaises(sqlite3.IntegrityError):
            add_document(self.connection, "inv-1", "doc-2", character_count=-1)

    def test_zero_character_count_is_accepted(self) -> None:
        add_document(self.connection, "inv-1", "doc-2", character_count=0)

        self.assertEqual(count_rows(self.connection, "documents", "inv-1"), 2)

    def test_negative_start_offset_is_rejected(self) -> None:
        for start in (-1, -10):
            with self.subTest(start_char=start):
                with self.assertRaises(sqlite3.IntegrityError):
                    add_mention(self.connection, start_char=start, end_char=5)

    def test_end_offset_not_greater_than_start_is_rejected(self) -> None:
        for start, end in ((5, 5), (5, 4), (10, 0), (0, 0)):
            with self.subTest(start_char=start, end_char=end):
                with self.assertRaises(sqlite3.IntegrityError):
                    add_mention(self.connection, start_char=start, end_char=end)

    def test_minimal_valid_offsets_are_accepted(self) -> None:
        add_mention(self.connection, start_char=0, end_char=1)

        self.assertEqual(count_rows(self.connection, "entity_mentions", "inv-1"), 1)


class TestImportSideEffects(DatabaseTestCase):
    """Importing the module must not touch the filesystem."""

    def test_importing_module_creates_no_database_file(self) -> None:
        # Run in a fresh interpreter whose working directory is empty, so any
        # file created at import time would be visible there.
        environment = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))
        completed = subprocess.run(
            [sys.executable, "-B", "-c", "import storage.database"],
            cwd=self.temp_path,
            env=environment,
            capture_output=True,
            text=True,
            timeout=60,
        )

        self.assertEqual(completed.returncode, 0, msg=completed.stderr)
        self.assertEqual(list(self.temp_path.iterdir()), [])


if __name__ == "__main__":
    unittest.main()