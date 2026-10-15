"""Tests for storage/investigation_store.py.

Uses only unittest, tempfile and unittest.mock. Each test works with its own
temporary, file-backed SQLite database.

Run from the project root with:
    python -m unittest tests.test_investigation_store -v
or:
    python -m unittest discover -v
"""

import copy
import sqlite3
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.relationship_extractor import extract_relationships  # noqa: E402
from storage.database import get_connection  # noqa: E402
from storage.investigation_store import save_investigation  # noqa: E402

EXTRACT = "storage.investigation_store.extract_relationships"
GET_CONNECTION = "storage.investigation_store.get_connection"

TABLES = (
    "investigations",
    "documents",
    "entities",
    "entity_mentions",
    "relationships",
)

DOCUMENT_FIELDS = {
    "document_id": str,
    "filename": str,
    "file_type": str,
    "text": str,
    "character_count": int,
}
MENTION_FIELDS = {
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
RELATIONSHIP_FIELDS = {
    "source_entity_id": int,
    "target_entity_id": int,
    "relationship_type": str,
    "document_id": str,
    "filename": str,
    "evidence": str,
}
RESULT_KEYS = ("documents", "entities", "summary", "graph", "graph_summary")

# Wrong-typed values for each expected type (bool is included for int).
WRONG_VALUES = {
    int: ["1", 1.5, None, True, False, [1]],
    str: [None, 1, 2.5, ["x"], {"a": 1}, b"bytes"],
}
EMPTY_STRINGS = ("", "   ", "\n\t ")

DOC_ID = "doc-1"
SENTENCE_1 = "Orion Systems acquired Delta Research."
SENTENCE_2 = "Priya Sharma works for Orion Systems."
DOC_TEXT = f"{SENTENCE_1} {SENTENCE_2}"


# --- Test data builders ------------------------------------------------------

def make_document(
    document_id: str = DOC_ID, filename: str = "a.txt", text: str = DOC_TEXT
) -> dict:
    return {
        "document_id": document_id,
        "filename": filename,
        "file_type": "txt",
        "text": text,
        "character_count": len(text),
    }


def make_mention(
    document: dict, entity_id: int, text: str, entity_type: str, sentence: str
) -> dict:
    """Build a mention whose offsets are computed from the document text."""
    start = document["text"].index(sentence) + sentence.index(text)
    return {
        "entity_id": entity_id,
        "entity_text": text,
        "entity_type": entity_type,
        "normalized_name": " ".join(text.split()).casefold(),
        "document_id": document["document_id"],
        "filename": document["filename"],
        "start_char": start,
        "end_char": start + len(text),
        "context": sentence,
    }


def make_result(filename: str = "a.txt", document_id: str = DOC_ID) -> dict:
    """A valid result: 3 entities, 4 mentions (Orion twice), 2 relationships
    that the real extractor recognises (1 ACQUIRED 2, 3 WORKS_FOR 1)."""
    document = make_document(document_id, filename)
    return {
        "documents": [document],
        "entities": [
            make_mention(document, 1, "Orion Systems", "ORG", SENTENCE_1),
            make_mention(document, 2, "Delta Research", "ORG", SENTENCE_1),
            make_mention(document, 3, "Priya Sharma", "PERSON", SENTENCE_2),
            make_mention(document, 1, "Orion Systems", "ORG", SENTENCE_2),
        ],
        "summary": {
            "document_count": 1,
            "entity_mention_count": 4,
            "unique_entity_count": 3,
        },
        "graph": object(),  # never stored; only its presence is required
        "graph_summary": {"node_count": 3, "edge_count": 2},
    }


def result_with_document(index: int = 0, **overrides: object) -> dict:
    result = make_result()
    result["documents"][index].update(overrides)
    return result


def result_with_mention(index: int = 0, **overrides: object) -> dict:
    result = make_result()
    result["entities"][index].update(overrides)
    return result


def make_relationship(**overrides: object) -> dict:
    relationship = {
        "source_entity_id": 1,
        "target_entity_id": 2,
        "relationship_type": "ACQUIRED",
        "document_id": DOC_ID,
        "filename": "a.txt",
        "evidence": SENTENCE_1,
    }
    relationship.update(overrides)
    return relationship


class StoreTestCase(unittest.TestCase):
    """Base class: temporary directory, database path and connection helpers."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        # Cleanups run last-in-first-out, so connections opened later are
        # closed before the directory is deleted (required on Windows).
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db_path = self.temp_path / "dossieriq.db"

    def open_db(self) -> sqlite3.Connection:
        connection = get_connection(self.db_path)
        self.addCleanup(connection.close)
        return connection

    def count(self, table: str, investigation_id: str | None = None) -> int:
        assert table in TABLES  # table names never come from outside input
        connection = self.open_db()
        if investigation_id is None:
            row = connection.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
        else:
            row = connection.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE investigation_id = ?",
                (investigation_id,),
            ).fetchone()
        return row["n"]

    def counts(self) -> dict[str, int]:
        return {table: self.count(table) for table in TABLES}

    def rows(self, table: str, investigation_id: str, order_by: str) -> list[dict]:
        assert table in TABLES
        connection = self.open_db()
        cursor = connection.execute(
            f"SELECT * FROM {table} WHERE investigation_id = ? ORDER BY {order_by}",
            (investigation_id,),
        )
        return [dict(row) for row in cursor.fetchall()]

    def total_rows(self) -> int:
        """Rows across all tables; 0 if the database file was never created."""
        if not self.db_path.exists():
            return 0
        return sum(self.counts().values())

    def assert_rejected(self, result: object) -> None:
        """The result must raise ValueError and leave nothing stored."""
        with self.assertRaises(ValueError):
            save_investigation(result, self.db_path)  # type: ignore[arg-type]
        self.assertEqual(self.total_rows(), 0)


class TestSaveSuccess(StoreTestCase):
    """Valid results are saved completely."""

    def test_returns_uuid_string(self) -> None:
        investigation_id = save_investigation(make_result(), self.db_path)

        self.assertIsInstance(investigation_id, str)
        self.assertEqual(str(uuid.UUID(investigation_id)), investigation_id)

    def test_accepts_string_and_path_database_locations(self) -> None:
        first = save_investigation(make_result(), str(self.db_path))
        second = save_investigation(make_result(), self.db_path)

        self.assertNotEqual(first, second)
        self.assertEqual(self.count("investigations"), 2)

    def test_creates_database_and_missing_directories(self) -> None:
        nested = self.temp_path / "storage" / "nested" / "dossieriq.db"

        save_investigation(make_result(), nested)

        self.assertTrue(nested.is_file())

    def test_investigation_row_has_utc_iso_timestamp(self) -> None:
        investigation_id = save_investigation(make_result(), self.db_path)

        row = self.rows("investigations", investigation_id, "investigation_id")[0]
        created_at = datetime.fromisoformat(row["created_at"])
        self.assertEqual(created_at.utcoffset(), timedelta(0))

    def test_all_five_tables_contain_expected_records(self) -> None:
        result = make_result()
        investigation_id = save_investigation(result, self.db_path)

        self.assertEqual(
            self.counts(),
            {
                "investigations": 1,
                "documents": 1,
                "entities": 3,
                "entity_mentions": 4,
                "relationships": 2,
            },
        )

        document = result["documents"][0]
        self.assertEqual(
            self.rows("documents", investigation_id, "document_id"),
            [{"investigation_id": investigation_id, **document}],
        )

        self.assertEqual(
            [
                (r["entity_id"], r["canonical_name"], r["entity_type"])
                for r in self.rows("entities", investigation_id, "entity_id")
            ],
            [(1, "orion systems", "ORG"), (2, "delta research", "ORG"),
             (3, "priya sharma", "PERSON")],
        )

        saved_mentions = self.rows("entity_mentions", investigation_id, "mention_id")
        self.assertEqual(len(saved_mentions), len(result["entities"]))
        for saved, original in zip(saved_mentions, result["entities"]):
            self.assertEqual(saved["investigation_id"], investigation_id)
            for field in MENTION_FIELDS:
                self.assertEqual(saved[field], original[field])

        saved_relationships = self.rows(
            "relationships", investigation_id, "relationship_id"
        )
        self.assertEqual(
            [{k: v for k, v in r.items() if k not in ("relationship_id", "investigation_id")}
             for r in saved_relationships],
            [
                make_relationship(),
                make_relationship(
                    source_entity_id=3, target_entity_id=1,
                    relationship_type="WORKS_FOR", evidence=SENTENCE_2,
                ),
            ],
        )

    def test_repeated_mentions_give_one_entity_row_and_many_mention_rows(self) -> None:
        investigation_id = save_investigation(make_result(), self.db_path)

        entity_rows = [
            r for r in self.rows("entities", investigation_id, "entity_id")
            if r["entity_id"] == 1
        ]
        mention_rows = [
            r for r in self.rows("entity_mentions", investigation_id, "mention_id")
            if r["entity_id"] == 1
        ]
        self.assertEqual(len(entity_rows), 1)
        self.assertEqual(len(mention_rows), 2)
        self.assertNotEqual(mention_rows[0]["start_char"], mention_rows[1]["start_char"])

    def test_multiple_relationships_are_saved(self) -> None:
        relationships = [
            make_relationship(),
            make_relationship(relationship_type="SIGNED_AGREEMENT_WITH"),
            make_relationship(),  # parallel edge, kept
            make_relationship(source_entity_id=3, target_entity_id=1,
                              relationship_type="WORKS_FOR", evidence=SENTENCE_2),
        ]
        with patch(EXTRACT, return_value=relationships):
            investigation_id = save_investigation(make_result(), self.db_path)

        saved = self.rows("relationships", investigation_id, "relationship_id")
        self.assertEqual(len(saved), 4)
        self.assertEqual(
            [(r["source_entity_id"], r["target_entity_id"], r["relationship_type"])
             for r in saved],
            [(1, 2, "ACQUIRED"), (1, 2, "SIGNED_AGREEMENT_WITH"),
             (1, 2, "ACQUIRED"), (3, 1, "WORKS_FOR")],
        )

    def test_real_extractor_saves_recognised_relationships(self) -> None:
        result = make_result()
        investigation_id = save_investigation(result, self.db_path)
        self.assertEqual(self.count("relationships", investigation_id), 2)

        with patch(EXTRACT, return_value=[]):
            other_id = save_investigation(make_result(), self.db_path)

        self.assertEqual(self.count("entities", other_id), 3)
        self.assertEqual(self.count("relationships", other_id), 0)

    def test_empty_entities_and_relationships_are_supported(self) -> None:
        result = make_result()
        result["entities"] = []
        result["summary"] = {
            "document_count": 1, "entity_mention_count": 0, "unique_entity_count": 0,
        }

        investigation_id = save_investigation(result, self.db_path)

        self.assertEqual(self.count("investigations", investigation_id), 1)
        self.assertEqual(self.count("documents", investigation_id), 1)
        self.assertEqual(self.count("entities", investigation_id), 0)
        self.assertEqual(self.count("entity_mentions", investigation_id), 0)
        self.assertEqual(self.count("relationships", investigation_id), 0)

    def test_empty_documents_and_entities_are_supported(self) -> None:
        result = make_result()
        result["documents"] = []
        result["entities"] = []

        investigation_id = save_investigation(result, self.db_path)

        self.assertEqual(self.count("investigations", investigation_id), 1)
        self.assertEqual(self.count("documents", investigation_id), 0)

    def test_input_result_is_not_modified(self) -> None:
        result = make_result()
        graph = result["graph"]
        snapshot = copy.deepcopy(
            {k: v for k, v in result.items() if k != "graph"}
        )

        save_investigation(result, self.db_path)

        self.assertEqual(set(result), set(RESULT_KEYS))
        self.assertIs(result["graph"], graph)
        self.assertEqual({k: v for k, v in result.items() if k != "graph"}, snapshot)

    def test_graph_is_not_stored(self) -> None:
        # A non-serialisable graph object must not matter.
        result = make_result()
        result["graph"] = object()

        save_investigation(result, self.db_path)

        self.assertEqual(self.count("investigations"), 1)


class TestExtractRelationshipsCall(StoreTestCase):
    """The extractor is called once, and its errors propagate."""

    def test_called_exactly_once_with_resolved_entity_list(self) -> None:
        result = make_result()

        with patch(EXTRACT, wraps=extract_relationships) as mock_extract:
            save_investigation(result, self.db_path)

        mock_extract.assert_called_once_with(result["entities"])

    def test_extractor_output_is_what_gets_saved(self) -> None:
        custom = [make_relationship(relationship_type="CUSTOM_TYPE")]

        with patch(EXTRACT, return_value=custom):
            investigation_id = save_investigation(make_result(), self.db_path)

        saved = self.rows("relationships", investigation_id, "relationship_id")
        self.assertEqual([r["relationship_type"] for r in saved], ["CUSTOM_TYPE"])

    def test_extractor_value_error_propagates(self) -> None:
        with patch(EXTRACT, side_effect=ValueError("bad mention records")):
            with self.assertRaises(ValueError) as context:
                save_investigation(make_result(), self.db_path)

        self.assertIn("bad mention records", str(context.exception))
        self.assertEqual(self.total_rows(), 0)

    def test_unexpected_extractor_exception_propagates(self) -> None:
        with patch(EXTRACT, side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                save_investigation(make_result(), self.db_path)

        self.assertEqual(self.total_rows(), 0)


class TestResultValidation(StoreTestCase):
    """Malformed results are rejected and nothing is written."""

    def test_rejected_input_does_not_create_database_file(self) -> None:
        with self.assertRaises(ValueError):
            save_investigation(result_with_mention(0, entity_id=0), self.db_path)

        self.assertFalse(self.db_path.exists())

    def test_rejected_input_leaves_existing_investigations_untouched(self) -> None:
        save_investigation(make_result(), self.db_path)
        before = self.counts()

        with self.assertRaises(ValueError):
            save_investigation(result_with_mention(0, start_char=-1), self.db_path)

        self.assertEqual(self.counts(), before)

    def test_non_dictionary_result(self) -> None:
        for bad in (None, [], "result", 42, (make_result(),)):
            with self.subTest(result=bad):
                self.assert_rejected(bad)

    def test_missing_result_keys(self) -> None:
        for key in RESULT_KEYS:
            with self.subTest(missing=key):
                result = make_result()
                del result[key]
                self.assert_rejected(result)

    def test_documents_and_entities_must_be_lists(self) -> None:
        for key in ("documents", "entities"):
            for bad in (None, {}, (), "text", 42):
                with self.subTest(key=key, value=bad):
                    result = make_result()
                    result[key] = bad
                    self.assert_rejected(result)

    def test_non_dictionary_records(self) -> None:
        for key in ("documents", "entities"):
            for bad in (None, "record", 42, ["x"]):
                with self.subTest(key=key, record=bad):
                    result = make_result()
                    result[key].append(bad)
                    self.assert_rejected(result)

    # --- documents ---

    def test_missing_document_fields(self) -> None:
        for field in DOCUMENT_FIELDS:
            with self.subTest(missing=field):
                result = make_result()
                del result["documents"][0][field]
                self.assert_rejected(result)

    def test_invalid_document_field_types(self) -> None:
        for field, expected_type in DOCUMENT_FIELDS.items():
            for bad in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad):
                    self.assert_rejected(result_with_document(**{field: bad}))

    def test_empty_document_strings(self) -> None:
        for field in ("document_id", "filename", "file_type"):
            for empty in EMPTY_STRINGS:
                with self.subTest(field=field, value=empty):
                    self.assert_rejected(result_with_document(**{field: empty}))

    def test_negative_character_count(self) -> None:
        self.assert_rejected(result_with_document(character_count=-1))

    def test_duplicate_document_ids(self) -> None:
        result = make_result()
        result["documents"].append(make_document(DOC_ID, "other.txt"))

        self.assert_rejected(result)

    # --- entity mentions ---

    def test_missing_mention_fields(self) -> None:
        for field in MENTION_FIELDS:
            with self.subTest(missing=field):
                result = make_result()
                del result["entities"][0][field]
                self.assert_rejected(result)

    def test_invalid_mention_field_types(self) -> None:
        for field, expected_type in MENTION_FIELDS.items():
            for bad in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad):
                    self.assert_rejected(result_with_mention(0, **{field: bad}))

    def test_empty_mention_strings(self) -> None:
        fields = ("entity_text", "entity_type", "normalized_name",
                  "document_id", "filename", "context")
        for field in fields:
            for empty in EMPTY_STRINGS:
                with self.subTest(field=field, value=empty):
                    self.assert_rejected(result_with_mention(0, **{field: empty}))

    def test_invalid_entity_ids(self) -> None:
        for bad in (0, -1, -100, True, False):
            with self.subTest(entity_id=bad):
                self.assert_rejected(result_with_mention(0, entity_id=bad))

    def test_negative_start_offset(self) -> None:
        for start in (-1, -10):
            with self.subTest(start_char=start):
                self.assert_rejected(
                    result_with_mention(0, start_char=start, end_char=5)
                )

    def test_end_offset_not_greater_than_start(self) -> None:
        for start, end in ((5, 5), (5, 4), (10, 0), (0, 0)):
            with self.subTest(start_char=start, end_char=end):
                self.assert_rejected(
                    result_with_mention(0, start_char=start, end_char=end)
                )

    def test_boolean_offsets(self) -> None:
        for field in ("start_char", "end_char"):
            for bad in (True, False):
                with self.subTest(field=field, value=bad):
                    self.assert_rejected(result_with_mention(0, **{field: bad}))

    def test_inconsistent_entity_identity(self) -> None:
        # Mention index 3 is a second mention of entity 1.
        cases = {
            "different normalized_name": {"normalized_name": "orion systems ltd"},
            "different entity_type": {"entity_type": "PERSON"},
        }
        for label, overrides in cases.items():
            with self.subTest(case=label):
                self.assert_rejected(result_with_mention(3, **overrides))

    def test_mention_referencing_missing_document(self) -> None:
        self.assert_rejected(result_with_mention(0, document_id="no-such-doc"))

    def test_mention_filename_must_match_its_document(self) -> None:
        self.assert_rejected(result_with_mention(0, filename="other.txt"))

    def test_mention_filename_checked_against_its_own_document(self) -> None:
        result = make_result()
        result["documents"].append(make_document("doc-2", "b.txt", text="Other."))
        result["entities"][0]["document_id"] = "doc-2"  # filename still a.txt

        self.assert_rejected(result)


class TestRelationshipValidation(StoreTestCase):
    """Relationship records from the extractor are validated before writing."""

    def reject_relationships(self, relationships: object) -> None:
        with patch(EXTRACT, return_value=relationships):
            self.assert_rejected(make_result())

    def test_valid_patched_relationship_is_accepted(self) -> None:
        with patch(EXTRACT, return_value=[make_relationship()]):
            investigation_id = save_investigation(make_result(), self.db_path)

        self.assertEqual(self.count("relationships", investigation_id), 1)

    def test_relationships_must_be_a_list(self) -> None:
        for bad in (None, (make_relationship(),), "text", {"a": 1}):
            with self.subTest(value=bad):
                self.reject_relationships(bad)

    def test_non_dictionary_relationship_records(self) -> None:
        for bad in (None, "record", 42, ["x"]):
            with self.subTest(record=bad):
                self.reject_relationships([make_relationship(), bad])

    def test_missing_relationship_fields(self) -> None:
        for field in RELATIONSHIP_FIELDS:
            with self.subTest(missing=field):
                relationship = make_relationship()
                del relationship[field]
                self.reject_relationships([relationship])

    def test_invalid_relationship_field_types(self) -> None:
        for field, expected_type in RELATIONSHIP_FIELDS.items():
            for bad in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad):
                    self.reject_relationships([make_relationship(**{field: bad})])

    def test_empty_relationship_strings(self) -> None:
        for field in ("relationship_type", "document_id", "filename", "evidence"):
            for empty in EMPTY_STRINGS:
                with self.subTest(field=field, value=empty):
                    self.reject_relationships([make_relationship(**{field: empty})])

    def test_unknown_source_or_target_entity(self) -> None:
        cases = {
            "unknown source": make_relationship(source_entity_id=99),
            "unknown target": make_relationship(target_entity_id=99),
            "both unknown": make_relationship(source_entity_id=98, target_entity_id=99),
        }
        for label, relationship in cases.items():
            with self.subTest(case=label):
                self.reject_relationships([relationship])

    def test_relationship_referencing_missing_document(self) -> None:
        self.reject_relationships([make_relationship(document_id="no-such-doc")])

    def test_relationship_filename_must_match_its_document(self) -> None:
        self.reject_relationships([make_relationship(filename="other.txt")])

    def test_one_bad_relationship_rejects_the_whole_investigation(self) -> None:
        self.reject_relationships(
            [make_relationship(), make_relationship(source_entity_id=99)]
        )


class TestAtomicity(StoreTestCase):
    """A failure while writing leaves no partial investigation."""

    @staticmethod
    def failing_get_connection(fail_on: str):
        """Return (replacement get_connection, list of opened connections).

        The connections behave normally except that any statement containing
        ``fail_on`` raises sqlite3.OperationalError.
        """
        opened: list[sqlite3.Connection] = []

        class FailingConnection(sqlite3.Connection):
            def execute(self, sql, *args):
                if fail_on in sql:
                    raise sqlite3.OperationalError("simulated insert failure")
                return super().execute(sql, *args)

            def executemany(self, sql, *args):
                if fail_on in sql:
                    raise sqlite3.OperationalError("simulated insert failure")
                return super().executemany(sql, *args)

        def factory(db_path):
            connection = sqlite3.connect(str(db_path), factory=FailingConnection)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            opened.append(connection)
            return connection

        return factory, opened

    def test_failure_at_any_insert_rolls_back_everything(self) -> None:
        for fail_on in ("INTO investigations", "INTO documents", "INTO entities",
                        "INTO entity_mentions", "INTO relationships"):
            with self.subTest(failing_insert=fail_on):
                self.db_path = self.temp_path / f"{fail_on.split()[-1]}.db"
                factory, opened = self.failing_get_connection(fail_on)

                with patch(GET_CONNECTION, side_effect=factory):
                    with self.assertRaises(sqlite3.OperationalError):
                        save_investigation(make_result(), self.db_path)

                self.assertEqual(self.counts(), {table: 0 for table in TABLES})
                # The connection was closed despite the failure.
                self.assertEqual(len(opened), 1)
                with self.assertRaises(sqlite3.ProgrammingError):
                    opened[0].execute("SELECT 1")

    def test_failure_does_not_affect_previously_saved_investigations(self) -> None:
        first_id = save_investigation(make_result(), self.db_path)
        before = self.counts()
        factory, _ = self.failing_get_connection("INTO relationships")

        with patch(GET_CONNECTION, side_effect=factory):
            with self.assertRaises(sqlite3.OperationalError):
                save_investigation(make_result(), self.db_path)

        self.assertEqual(self.counts(), before)
        self.assertEqual(self.count("investigations", first_id), 1)
        self.assertEqual(self.count("entity_mentions", first_id), 4)

    def test_save_works_again_after_a_failed_attempt(self) -> None:
        factory, _ = self.failing_get_connection("INTO entity_mentions")
        with patch(GET_CONNECTION, side_effect=factory):
            with self.assertRaises(sqlite3.OperationalError):
                save_investigation(make_result(), self.db_path)

        investigation_id = save_investigation(make_result(), self.db_path)

        self.assertEqual(self.count("investigations"), 1)
        self.assertEqual(self.count("entity_mentions", investigation_id), 4)

    def test_database_foreign_keys_back_up_validation(self) -> None:
        # Patching the extractor past validation is not possible for bad
        # references, so confirm the saved data satisfies every foreign key.
        save_investigation(make_result(), self.db_path)

        connection = self.open_db()
        self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])


class TestInvestigationIsolation(StoreTestCase):
    """Investigations never mix, even with overlapping IDs."""

    def test_same_result_saved_twice_gives_separate_investigations(self) -> None:
        first = save_investigation(make_result(), self.db_path)
        second = save_investigation(make_result(), self.db_path)

        self.assertNotEqual(first, second)
        for investigation_id in (first, second):
            with self.subTest(investigation_id=investigation_id):
                self.assertEqual(self.count("documents", investigation_id), 1)
                self.assertEqual(self.count("entities", investigation_id), 3)
                self.assertEqual(self.count("entity_mentions", investigation_id), 4)
                self.assertEqual(self.count("relationships", investigation_id), 2)
        self.assertEqual(self.count("entities"), 6)

    def test_overlapping_ids_keep_each_investigations_own_data(self) -> None:
        first = save_investigation(make_result(filename="a.txt"), self.db_path)
        second = save_investigation(make_result(filename="b.txt"), self.db_path)

        first_doc = self.rows("documents", first, "document_id")[0]
        second_doc = self.rows("documents", second, "document_id")[0]
        self.assertEqual(first_doc["document_id"], second_doc["document_id"])
        self.assertEqual(first_doc["filename"], "a.txt")
        self.assertEqual(second_doc["filename"], "b.txt")

        for investigation_id, filename in ((first, "a.txt"), (second, "b.txt")):
            with self.subTest(investigation_id=investigation_id):
                for table in ("entity_mentions", "relationships"):
                    saved = self.rows(table, investigation_id, "1")
                    self.assertTrue(saved)
                    self.assertEqual({r["filename"] for r in saved}, {filename})
                self.assertEqual(
                    [r["entity_id"] for r in
                     self.rows("entities", investigation_id, "entity_id")],
                    [1, 2, 3],
                )

    def test_deleting_one_investigation_leaves_the_other(self) -> None:
        first = save_investigation(make_result(), self.db_path)
        second = save_investigation(make_result(), self.db_path)

        connection = self.open_db()
        connection.execute(
            "DELETE FROM investigations WHERE investigation_id = ?", (first,)
        )
        connection.commit()

        for table in TABLES[1:]:
            with self.subTest(table=table):
                self.assertEqual(self.count(table, first), 0)
                self.assertGreater(self.count(table, second), 0)


if __name__ == "__main__":
    unittest.main()