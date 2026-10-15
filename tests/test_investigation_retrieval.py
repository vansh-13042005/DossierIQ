"""Tests for storage/investigation_retrieval.py.

Uses only unittest, tempfile and unittest.mock. Data is created with the real
initialize_database() and save_investigation() in per-test temporary
directories.

Run from the project root with:
    python -m unittest tests.test_investigation_retrieval -v
or:
    python -m unittest discover -v
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
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
from storage.database import get_connection, initialize_database  # noqa: E402
from storage.investigation_retrieval import (  # noqa: E402
    InvestigationNotFoundError,
    get_investigation,
    list_investigations,
)
from storage.investigation_store import save_investigation  # noqa: E402

GET_CONNECTION = "storage.investigation_retrieval.get_connection"
STORE_EXTRACT = "storage.investigation_store.extract_relationships"

RESULT_KEYS = {
    "investigation_id", "created_at", "documents", "entities",
    "entity_mentions", "relationships",
}
DOCUMENT_KEYS = {"document_id", "filename", "file_type", "text", "character_count"}
ENTITY_KEYS = {"entity_id", "canonical_name", "entity_type"}
MENTION_KEYS = {
    "entity_id", "entity_text", "entity_type", "normalized_name", "document_id",
    "filename", "start_char", "end_char", "context",
}
RELATIONSHIP_KEYS = {
    "source_entity_id", "target_entity_id", "relationship_type",
    "document_id", "filename", "evidence",
}
LIST_KEYS = {"investigation_id", "created_at"}

INVALID_IDS = [None, True, False, 0, 1, 1.5, b"id", ["id"], {"id": 1}, "", "   ", "\n\t "]
INVALID_PATHS = [None, True, 0, 42, 1.5, b"db", ["db"], {"a": 1}, "", "   ", "\n\t ", ":memory:"]


# --- Test data builders ------------------------------------------------------

def make_mention(document: dict, entity_id: int, text: str, entity_type: str,
                 sentence: str) -> dict:
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


def make_result(
    org_a: str = "Orion Systems",
    org_b: str = "Delta Research",
    person: str = "Priya Sharma",
    filename: str = "a.txt",
    document_id: str = "doc-1",
) -> dict:
    """A valid result: 3 entities, 4 mentions (org_a twice), 2 relationships
    recognised by the real extractor (1 ACQUIRED 2, 3 WORKS_FOR 1)."""
    sentence_1 = f"{org_a} acquired {org_b}."
    sentence_2 = f"{person} works for {org_a}."
    text = f"{sentence_1} {sentence_2}"
    document = {
        "document_id": document_id,
        "filename": filename,
        "file_type": "txt",
        "text": text,
        "character_count": len(text),
    }
    return {
        "documents": [document],
        "entities": [
            make_mention(document, 1, org_a, "ORG", sentence_1),
            make_mention(document, 2, org_b, "ORG", sentence_1),
            make_mention(document, 3, person, "PERSON", sentence_2),
            make_mention(document, 1, org_a, "ORG", sentence_2),
        ],
        "summary": {
            "document_count": 1,
            "entity_mention_count": 4,
            "unique_entity_count": 3,
        },
        "graph": object(),  # never stored
        "graph_summary": {"node_count": 3, "edge_count": 2},
    }


def assert_plain(testcase: unittest.TestCase, value: object) -> None:
    """Recursively check the value uses only plain dict/list/str/int/None."""
    if isinstance(value, dict):
        testcase.assertIs(type(value), dict)
        for key, item in value.items():
            testcase.assertIs(type(key), str)
            assert_plain(testcase, item)
    elif isinstance(value, list):
        testcase.assertIs(type(value), list)
        for item in value:
            assert_plain(testcase, item)
    else:
        testcase.assertIn(type(value), (str, int, type(None)))


class RetrievalTestCase(unittest.TestCase):
    """Base class: temporary directory, database path and helpers."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        # Cleanups run last-in-first-out; connections registered later are
        # closed before the directory is removed (required on Windows).
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db_path = self.temp_path / "dossieriq.db"

    def save(self, result: dict | None = None) -> str:
        return save_investigation(make_result() if result is None else result,
                                  self.db_path)

    def execute(self, sql: str, params: tuple = ()) -> None:
        """Run a parameterised write directly against the test database."""
        with closing(get_connection(self.db_path)) as connection:
            connection.execute(sql, params)
            connection.commit()

    def assert_closed(self, connection: sqlite3.Connection) -> None:
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute("SELECT 1")

    def recording_get_connection(self, deny_table: str | None = None):
        """Return (replacement get_connection, list of connections it opened).

        The connections are real. If ``deny_table`` is given, SQLite's
        authorizer refuses any read of that table, which makes queries on it
        fail however the module issues them.
        """
        opened: list[sqlite3.Connection] = []

        def authorizer(action, arg1, arg2, db_name, source):
            if action == sqlite3.SQLITE_READ and arg1 == deny_table:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        def factory(db_path):
            connection = get_connection(db_path)
            if deny_table is not None:
                connection.set_authorizer(authorizer)
            opened.append(connection)
            return connection

        return factory, opened


# --- Argument validation -------------------------------------------------------

class TestArgumentValidation(RetrievalTestCase):

    def test_invalid_investigation_ids_raise_value_error(self) -> None:
        self.save()
        for invalid in INVALID_IDS:
            with self.subTest(investigation_id=invalid):
                with self.assertRaises(ValueError):
                    get_investigation(invalid, self.db_path)  # type: ignore[arg-type]

    def test_invalid_db_paths_raise_value_error(self) -> None:
        investigation_id = self.save()
        for invalid in INVALID_PATHS:
            with self.subTest(function="get_investigation", db_path=invalid):
                with self.assertRaises(ValueError):
                    get_investigation(investigation_id, invalid)  # type: ignore[arg-type]
            with self.subTest(function="list_investigations", db_path=invalid):
                with self.assertRaises(ValueError):
                    list_investigations(invalid)  # type: ignore[arg-type]

    def test_validation_happens_before_the_filesystem_is_checked(self) -> None:
        missing = self.temp_path / "missing.db"

        with self.assertRaises(ValueError):
            get_investigation("", missing)
        with self.assertRaises(ValueError):
            get_investigation(None, missing)  # type: ignore[arg-type]
        self.assertFalse(missing.exists())

    def test_memory_path_never_creates_a_file(self) -> None:
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.temp_path)

        with self.assertRaises(ValueError):
            get_investigation("some-id", ":memory:")
        with self.assertRaises(ValueError):
            list_investigations(":memory:")

        self.assertEqual(list(self.temp_path.iterdir()), [])


# --- Missing / unusable database files -----------------------------------------

class TestMissingAndInvalidDatabase(RetrievalTestCase):

    def test_missing_file_raises_file_not_found(self) -> None:
        for label, path in (("Path", self.db_path), ("str", str(self.db_path))):
            with self.subTest(kind=label, function="get_investigation"):
                with self.assertRaises(FileNotFoundError):
                    get_investigation("some-id", path)
            with self.subTest(kind=label, function="list_investigations"):
                with self.assertRaises(FileNotFoundError):
                    list_investigations(path)

    def test_missing_file_is_not_created(self) -> None:
        with self.assertRaises(FileNotFoundError):
            get_investigation("some-id", self.db_path)
        with self.assertRaises(FileNotFoundError):
            list_investigations(self.db_path)

        self.assertFalse(self.db_path.exists())
        self.assertEqual(list(self.temp_path.iterdir()), [])

    def test_missing_parent_directory_is_not_created(self) -> None:
        nested = self.temp_path / "does" / "not" / "exist" / "dossieriq.db"

        with self.assertRaises(FileNotFoundError):
            get_investigation("some-id", nested)
        with self.assertRaises(FileNotFoundError):
            list_investigations(nested)

        self.assertFalse((self.temp_path / "does").exists())

    def test_directory_path_raises_file_not_found(self) -> None:
        directory = self.temp_path / "a_directory"
        directory.mkdir()

        with self.assertRaises(FileNotFoundError):
            get_investigation("some-id", directory)
        with self.assertRaises(FileNotFoundError):
            list_investigations(directory)

    def test_schema_less_file_raises_operational_error(self) -> None:
        self.db_path.touch()  # an empty file is a valid, empty SQLite database

        with self.assertRaises(sqlite3.OperationalError):
            get_investigation("some-id", self.db_path)
        with self.assertRaises(sqlite3.OperationalError):
            list_investigations(self.db_path)

        self.assertEqual(self.db_path.stat().st_size, 0)  # not repaired

    def test_non_sqlite_file_raises_database_error(self) -> None:
        self.db_path.write_text("this is not a sqlite database\n" * 20, encoding="utf-8")

        with self.assertRaises(sqlite3.DatabaseError):
            get_investigation("some-id", self.db_path)
        with self.assertRaises(sqlite3.DatabaseError):
            list_investigations(self.db_path)

    def test_sqlite_errors_are_not_wrapped(self) -> None:
        self.db_path.touch()

        with self.assertRaises(sqlite3.Error) as context:
            get_investigation("some-id", self.db_path)

        self.assertNotIsInstance(context.exception, (ValueError, LookupError))


# --- Unknown investigations ----------------------------------------------------

class TestUnknownInvestigation(RetrievalTestCase):

    def test_unknown_id_raises_investigation_not_found(self) -> None:
        self.save()

        with self.assertRaises(InvestigationNotFoundError):
            get_investigation("no-such-investigation", self.db_path)

    def test_exception_is_a_lookup_error_with_id_attribute(self) -> None:
        self.save()

        with self.assertRaises(LookupError) as context:
            get_investigation("no-such-investigation", self.db_path)

        self.assertTrue(issubclass(InvestigationNotFoundError, LookupError))
        self.assertNotIsInstance(context.exception, ValueError)
        self.assertEqual(context.exception.investigation_id, "no-such-investigation")
        self.assertIn("no-such-investigation", str(context.exception))

    def test_empty_initialised_database_raises_not_found(self) -> None:
        initialize_database(self.db_path)

        with self.assertRaises(InvestigationNotFoundError):
            get_investigation("anything", self.db_path)

    def test_match_is_exact(self) -> None:
        investigation_id = self.save()
        variants = {
            "upper-case": investigation_id.upper(),
            "padded": f" {investigation_id} ",
            "truncated": investigation_id[:-1],
        }
        for label, variant in variants.items():
            with self.subTest(variant=label):
                with self.assertRaises(InvestigationNotFoundError):
                    get_investigation(variant, self.db_path)

    def test_retrieval_leaves_the_database_file_unchanged(self) -> None:
        investigation_id = self.save()
        before = self.db_path.read_bytes()

        get_investigation(investigation_id, self.db_path)
        with self.assertRaises(InvestigationNotFoundError):
            get_investigation("no-such-investigation", self.db_path)
        list_investigations(self.db_path)

        self.assertEqual(self.db_path.read_bytes(), before)


# --- Round trip ----------------------------------------------------------------

class TestRoundTrip(RetrievalTestCase):

    def test_result_has_exactly_the_expected_keys(self) -> None:
        investigation_id = self.save()

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(set(data), RESULT_KEYS)
        self.assertEqual(data["investigation_id"], investigation_id)

    def test_created_at_is_iso_8601_utc(self) -> None:
        before = datetime.now().astimezone() - timedelta(minutes=1)
        investigation_id = self.save()

        created_at = datetime.fromisoformat(
            get_investigation(investigation_id, self.db_path)["created_at"]
        )

        self.assertEqual(created_at.utcoffset(), timedelta(0))
        self.assertGreaterEqual(created_at, before)

    def test_documents_round_trip(self) -> None:
        result = make_result()
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(data["documents"], result["documents"])
        self.assertEqual(set(data["documents"][0]), DOCUMENT_KEYS)

    def test_entities_are_distinct_rows(self) -> None:
        investigation_id = self.save()

        data = get_investigation(investigation_id, self.db_path)

        # Entity 1 has two mentions but appears once.
        self.assertEqual(
            data["entities"],
            [
                {"entity_id": 1, "canonical_name": "orion systems", "entity_type": "ORG"},
                {"entity_id": 2, "canonical_name": "delta research", "entity_type": "ORG"},
                {"entity_id": 3, "canonical_name": "priya sharma", "entity_type": "PERSON"},
            ],
        )
        for entity in data["entities"]:
            self.assertEqual(set(entity), ENTITY_KEYS)

    def test_mentions_round_trip_including_repeats_and_order(self) -> None:
        result = make_result()
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(data["entity_mentions"], result["entities"])
        self.assertEqual(len(data["entity_mentions"]), 4)
        self.assertEqual(
            [m["entity_id"] for m in data["entity_mentions"]], [1, 2, 3, 1]
        )

    def test_relationships_round_trip(self) -> None:
        result = make_result()
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        expected = extract_relationships(result["entities"])
        self.assertEqual(len(expected), 2)
        self.assertEqual(data["relationships"], expected)

    def test_database_only_ids_are_omitted(self) -> None:
        investigation_id = self.save()

        data = get_investigation(investigation_id, self.db_path)

        for mention in data["entity_mentions"]:
            self.assertEqual(set(mention), MENTION_KEYS)
        for relationship in data["relationships"]:
            self.assertEqual(set(relationship), RELATIONSHIP_KEYS)
        for table in ("documents", "entities"):
            for record in data[table]:
                self.assertNotIn("investigation_id", record)
        for forbidden in ("mention_id", "relationship_id", "investigation_id"):
            for table in ("entity_mentions", "relationships"):
                for record in data[table]:
                    self.assertNotIn(forbidden, record)

    def test_values_are_plain_dicts_and_lists(self) -> None:
        investigation_id = self.save()

        assert_plain(self, get_investigation(investigation_id, self.db_path))
        assert_plain(self, list_investigations(self.db_path))

    def test_empty_entities_give_empty_lists(self) -> None:
        result = make_result()
        result["entities"] = []
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(len(data["documents"]), 1)
        self.assertEqual(data["entities"], [])
        self.assertEqual(data["entity_mentions"], [])
        self.assertEqual(data["relationships"], [])

    def test_empty_documents_and_entities_give_empty_lists(self) -> None:
        result = make_result()
        result["documents"] = []
        result["entities"] = []
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(set(data), RESULT_KEYS)
        for key in ("documents", "entities", "entity_mentions", "relationships"):
            self.assertEqual(data[key], [])

    def test_entities_without_relationships(self) -> None:
        with patch(STORE_EXTRACT, return_value=[]):
            investigation_id = self.save()

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(len(data["entities"]), 3)
        self.assertEqual(data["relationships"], [])

    def test_non_ascii_text_round_trips(self) -> None:
        result = make_result(org_a="Café Orion", org_b="Zürich Labs", person="Zoë Müller")
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(data["documents"], result["documents"])
        self.assertEqual(data["entity_mentions"], result["entities"])
        self.assertEqual(data["entities"][0]["canonical_name"], "café orion")

    def test_str_and_path_locations_both_work(self) -> None:
        investigation_id = self.save()

        from_path = get_investigation(investigation_id, self.db_path)
        from_str = get_investigation(investigation_id, str(self.db_path))

        self.assertEqual(from_path, from_str)

    def test_repeated_calls_return_equal_but_distinct_objects(self) -> None:
        investigation_id = self.save()

        first = get_investigation(investigation_id, self.db_path)
        second = get_investigation(investigation_id, self.db_path)

        self.assertEqual(first, second)
        self.assertIsNot(first, second)
        self.assertIsNot(first["documents"], second["documents"])
        first["documents"].clear()  # mutating one result must not affect another
        self.assertEqual(len(second["documents"]), 1)


# --- Ordering ------------------------------------------------------------------

class TestOrdering(RetrievalTestCase):

    def test_documents_keep_input_order(self) -> None:
        result = make_result()
        result["entities"] = []
        result["documents"] = [
            {"document_id": doc_id, "filename": f"{doc_id}.txt", "file_type": "txt",
             "text": f"Text {doc_id}.", "character_count": len(f"Text {doc_id}.")}
            for doc_id in ("doc-z", "doc-a", "doc-m")
        ]
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(
            [d["document_id"] for d in data["documents"]], ["doc-z", "doc-a", "doc-m"]
        )

    def test_mentions_keep_insertion_order_and_entities_sort_by_id(self) -> None:
        result = make_result()
        result["entities"].reverse()  # entity IDs now appear as 1, 3, 2, 1
        investigation_id = self.save(result)

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(data["entity_mentions"], result["entities"])
        self.assertEqual([m["entity_id"] for m in data["entity_mentions"]], [1, 3, 2, 1])
        self.assertEqual([e["entity_id"] for e in data["entities"]], [1, 2, 3])

    def test_relationships_keep_insertion_order(self) -> None:
        def relationship(source: int, target: int, kind: str) -> dict:
            return {
                "source_entity_id": source, "target_entity_id": target,
                "relationship_type": kind, "document_id": "doc-1",
                "filename": "a.txt", "evidence": f"{kind} evidence",
            }

        unsorted_records = [
            relationship(3, 1, "WORKS_FOR"),
            relationship(2, 1, "PARTNER_OF"),
            relationship(1, 2, "ACQUIRED"),
        ]
        with patch(STORE_EXTRACT, return_value=unsorted_records):
            investigation_id = self.save()

        data = get_investigation(investigation_id, self.db_path)

        self.assertEqual(data["relationships"], unsorted_records)

    def test_repeated_retrieval_is_identical(self) -> None:
        investigation_id = self.save()

        results = [get_investigation(investigation_id, self.db_path) for _ in range(3)]

        self.assertEqual(results[0], results[1])
        self.assertEqual(results[1], results[2])


# --- list_investigations -------------------------------------------------------

class TestListInvestigations(RetrievalTestCase):

    def add_investigation_row(self, investigation_id: str, created_at: str) -> None:
        self.execute(
            "INSERT INTO investigations (investigation_id, created_at) VALUES (?, ?)",
            (investigation_id, created_at),
        )

    def test_empty_initialised_database_returns_empty_list(self) -> None:
        initialize_database(self.db_path)

        self.assertEqual(list_investigations(self.db_path), [])

    def test_populated_database_lists_saved_investigations(self) -> None:
        first = self.save()
        second = self.save(make_result(filename="b.txt"))

        listed = list_investigations(self.db_path)

        self.assertEqual(len(listed), 2)
        self.assertEqual({row["investigation_id"] for row in listed}, {first, second})
        for row in listed:
            self.assertEqual(set(row), LIST_KEYS)
            datetime.fromisoformat(row["created_at"])

    def test_listed_created_at_matches_retrieved_value(self) -> None:
        investigation_id = self.save()

        listed = list_investigations(self.db_path)[0]

        self.assertEqual(
            listed["created_at"],
            get_investigation(investigation_id, self.db_path)["created_at"],
        )

    def test_newest_first_ordering(self) -> None:
        initialize_database(self.db_path)
        self.add_investigation_row("middle", "2026-02-01T00:00:00+00:00")
        self.add_investigation_row("oldest", "2026-01-01T00:00:00+00:00")
        self.add_investigation_row("newest", "2026-03-01T00:00:00+00:00")

        listed = list_investigations(self.db_path)

        self.assertEqual(
            [row["investigation_id"] for row in listed], ["newest", "middle", "oldest"]
        )

    def test_equal_timestamps_are_ordered_by_id(self) -> None:
        initialize_database(self.db_path)
        same_time = "2026-02-01T00:00:00+00:00"
        for investigation_id in ("id-c", "id-a", "id-b"):  # inserted out of order
            self.add_investigation_row(investigation_id, same_time)
        self.add_investigation_row("id-newer", "2026-03-01T00:00:00+00:00")

        listed = list_investigations(self.db_path)

        self.assertEqual(
            [row["investigation_id"] for row in listed],
            ["id-newer", "id-a", "id-b", "id-c"],
        )

    def test_fractional_seconds_sort_after_whole_seconds(self) -> None:
        initialize_database(self.db_path)
        self.add_investigation_row("whole", "2026-02-01T00:00:00+00:00")
        self.add_investigation_row("fractional", "2026-02-01T00:00:00.500000+00:00")

        listed = list_investigations(self.db_path)

        self.assertEqual(
            [row["investigation_id"] for row in listed], ["fractional", "whole"]
        )

    def test_listing_is_repeatable(self) -> None:
        self.save()
        self.save()

        self.assertEqual(
            list_investigations(self.db_path), list_investigations(self.db_path)
        )


# --- Isolation -----------------------------------------------------------------

class TestIsolation(RetrievalTestCase):

    def save_three(self) -> list[str]:
        """Three investigations that all use doc-1 and entity IDs 1, 2, 3."""
        results = [
            make_result("Orion Systems", "Delta Research", "Priya Sharma", "a.txt"),
            make_result("Apex Dynamics", "Borealis Labs", "Rahul Mehta", "b.txt"),
            make_result("Cobalt Works", "Dune Analytics", "Anita Rao", "c.txt"),
        ]
        return [self.save(result) for result in results]

    def test_overlapping_ids_return_only_their_own_data(self) -> None:
        first = make_result("Orion Systems", "Delta Research", "Priya Sharma", "a.txt")
        second = make_result("Apex Dynamics", "Borealis Labs", "Rahul Mehta", "b.txt")
        first_id, second_id = self.save(first), self.save(second)

        for investigation_id, original in ((first_id, first), (second_id, second)):
            with self.subTest(investigation_id=investigation_id):
                data = get_investigation(investigation_id, self.db_path)

                self.assertEqual(data["documents"], original["documents"])
                self.assertEqual(data["entity_mentions"], original["entities"])
                self.assertEqual(
                    data["relationships"], extract_relationships(original["entities"])
                )
                self.assertEqual(
                    [e["canonical_name"] for e in data["entities"]],
                    [m["normalized_name"] for m in original["entities"][:3]],
                )

    def test_every_record_belongs_to_the_requested_investigation(self) -> None:
        ids = self.save_three()
        filenames = dict(zip(ids, ("a.txt", "b.txt", "c.txt")))

        for investigation_id in ids:
            with self.subTest(investigation_id=investigation_id):
                data = get_investigation(investigation_id, self.db_path)
                expected = filenames[investigation_id]

                self.assertEqual(len(data["documents"]), 1)
                self.assertEqual(len(data["entities"]), 3)
                self.assertEqual(len(data["entity_mentions"]), 4)
                self.assertEqual(len(data["relationships"]), 2)
                self.assertEqual({d["filename"] for d in data["documents"]}, {expected})
                for table in ("entity_mentions", "relationships"):
                    self.assertEqual({r["filename"] for r in data[table]}, {expected})

    def test_middle_investigation_is_not_mixed_with_neighbours(self) -> None:
        ids = self.save_three()

        data = get_investigation(ids[1], self.db_path)

        names = {e["canonical_name"] for e in data["entities"]}
        self.assertEqual(names, {"apex dynamics", "borealis labs", "rahul mehta"})

    def test_deleting_one_investigation_leaves_the_others(self) -> None:
        first, second, third = self.save_three()

        self.execute("DELETE FROM investigations WHERE investigation_id = ?", (second,))

        with self.assertRaises(InvestigationNotFoundError):
            get_investigation(second, self.db_path)
        for investigation_id in (first, third):
            data = get_investigation(investigation_id, self.db_path)
            self.assertEqual(len(data["entity_mentions"]), 4)
        self.assertEqual(len(list_investigations(self.db_path)), 2)


# --- Connection handling -------------------------------------------------------

class TestConnectionHandling(RetrievalTestCase):
    """Closure is checked on the real connections the module opened, so the
    tests do not depend on how the module structures its queries."""

    def run_with_recording(self, function, *args, deny_table: str | None = None):
        factory, opened = self.recording_get_connection(deny_table)
        with patch(GET_CONNECTION, side_effect=factory):
            try:
                outcome = function(*args)
            except Exception as error:  # noqa: BLE001 - returned for assertions
                outcome = error
        return outcome, opened

    def test_connection_is_closed_after_success(self) -> None:
        investigation_id = self.save()

        data, opened = self.run_with_recording(
            get_investigation, investigation_id, self.db_path
        )

        self.assertIsInstance(data, dict)
        self.assertGreaterEqual(len(opened), 1)
        for connection in opened:
            self.assert_closed(connection)

    def test_connection_is_closed_after_unknown_id(self) -> None:
        self.save()

        error, opened = self.run_with_recording(
            get_investigation, "no-such-investigation", self.db_path
        )

        self.assertIsInstance(error, InvestigationNotFoundError)
        self.assertGreaterEqual(len(opened), 1)
        for connection in opened:
            self.assert_closed(connection)

    def test_connection_is_closed_and_error_propagates_for_each_table(self) -> None:
        investigation_id = self.save()
        tables = ("investigations", "documents", "entities",
                  "entity_mentions", "relationships")
        for table in tables:
            with self.subTest(denied_table=table):
                error, opened = self.run_with_recording(
                    get_investigation, investigation_id, self.db_path, deny_table=table
                )

                self.assertIsInstance(error, sqlite3.Error)
                self.assertNotIsInstance(error, (ValueError, LookupError))
                self.assertGreaterEqual(len(opened), 1)
                for connection in opened:
                    self.assert_closed(connection)

    def test_list_connection_is_closed_after_success_and_failure(self) -> None:
        self.save()

        listed, opened = self.run_with_recording(list_investigations, self.db_path)
        self.assertIsInstance(listed, list)
        self.assertGreaterEqual(len(opened), 1)
        for connection in opened:
            self.assert_closed(connection)

        error, opened = self.run_with_recording(
            list_investigations, self.db_path, deny_table="investigations"
        )
        self.assertIsInstance(error, sqlite3.Error)
        for connection in opened:
            self.assert_closed(connection)

    def test_no_connection_is_opened_for_invalid_arguments(self) -> None:
        self.save()

        for function, args in (
            (get_investigation, ("", self.db_path)),
            (get_investigation, ("id", self.temp_path / "missing.db")),
            (list_investigations, (":memory:",)),
            (list_investigations, (self.temp_path / "missing.db",)),
        ):
            with self.subTest(function=function.__name__, args=args):
                error, opened = self.run_with_recording(function, *args)

                self.assertIsInstance(error, (ValueError, FileNotFoundError))
                self.assertEqual(opened, [])

    def test_connections_are_closed_for_unusable_database_files(self) -> None:
        for label, content in (("schema-less", b""), ("garbage", b"not a database\n" * 20)):
            with self.subTest(file=label):
                self.db_path.write_bytes(content)

                error, opened = self.run_with_recording(
                    get_investigation, "some-id", self.db_path
                )

                self.assertIsInstance(error, sqlite3.DatabaseError)
                for connection in opened:
                    self.assert_closed(connection)

    def test_database_file_can_be_deleted_after_retrieval(self) -> None:
        # On Windows an open connection would keep the file locked.
        investigation_id = self.save()

        get_investigation(investigation_id, self.db_path)
        with self.assertRaises(InvestigationNotFoundError):
            get_investigation("no-such-investigation", self.db_path)
        list_investigations(self.db_path)

        self.db_path.unlink()
        self.assertFalse(self.db_path.exists())


# --- Import side effects -------------------------------------------------------

class TestImportSideEffects(RetrievalTestCase):

    def test_importing_module_creates_no_files(self) -> None:
        environment = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT))

        completed = subprocess.run(
            [sys.executable, "-B", "-c", "import storage.investigation_retrieval"],
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