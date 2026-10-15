"""Tests for the optional SQLite persistence in core/investigation.py.

Uses only unittest, tempfile and unittest.mock. The pipeline is patched, so
no real documents, spaCy model or network is needed. Database files are only
created inside temporary directories.

Run from the project root with:
    python -m unittest tests.test_investigation_persistence -v
or:
    python -m unittest discover -v
"""

import os
import sqlite3
import sys
import tempfile
import unittest
import uuid
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import networkx as nx

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.investigation import DEFAULT_DB_PATH, run_investigation  # noqa: E402

# Names are patched where investigation.py looks them up.
PROCESS = "core.investigation.process_documents"
SAVE = "core.investigation.save_investigation"

BASE_KEYS = {"documents", "entities", "summary", "graph", "graph_summary"}
SENTENCE = "Orion Systems acquired Delta Research."


def make_pipeline_result() -> dict:
    """Build a valid fake process_documents() result.

    The offsets are aligned with the sentence, so the real relationship
    extractor, graph builder and storage layer all accept it
    (1 --ACQUIRED--> 2).
    """
    base = {
        "entity_type": "ORG",
        "document_id": "id-a",
        "filename": "a.txt",
        "context": SENTENCE,
    }
    return {
        "documents": [
            {
                "document_id": "id-a",
                "filename": "a.txt",
                "file_type": "txt",
                "text": SENTENCE,
                "character_count": len(SENTENCE),
            }
        ],
        "entities": [
            {**base, "entity_id": 1, "entity_text": "Orion Systems",
             "normalized_name": "orion systems", "start_char": 0, "end_char": 13},
            {**base, "entity_id": 2, "entity_text": "Delta Research",
             "normalized_name": "delta research", "start_char": 23, "end_char": 37},
        ],
        "summary": {
            "document_count": 1,
            "entity_mention_count": 2,
            "unique_entity_count": 2,
        },
    }


class PersistenceTestCase(unittest.TestCase):
    """Base class: a temporary directory per test."""

    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.temp_path = Path(temp_dir.name)
        self.db_path = self.temp_path / "dossieriq.db"
        self.pipeline_result = make_pipeline_result()

    def run_with_mocked_save(self, **kwargs: object):
        """Run run_investigation with the pipeline and storage patched.

        Returns (result, process mock, save mock, keys the result had when
        save was called).
        """
        keys_at_save: list[set[str]] = []

        def fake_save(investigation: dict, path: object) -> str:
            keys_at_save.append(set(investigation))
            return "fake-investigation-id"

        with patch(PROCESS, return_value=self.pipeline_result) as process, \
             patch(SAVE, side_effect=fake_save) as save:
            result = run_investigation(["a.txt"], **kwargs)  # type: ignore[arg-type]
        return result, process, save, keys_at_save

    def count_rows(self, table: str, path: Path | None = None) -> int:
        assert table in ("investigations", "documents", "entities",
                         "entity_mentions", "relationships")
        with closing(sqlite3.connect(str(path or self.db_path))) as connection:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


class TestPersistenceDisabled(PersistenceTestCase):
    """Default invocation and persist=False never touch storage."""

    def test_default_invocation_does_not_call_save(self) -> None:
        _, _, save, _ = self.run_with_mocked_save()

        save.assert_not_called()

    def test_explicit_persist_false_does_not_call_save(self) -> None:
        _, _, save, _ = self.run_with_mocked_save(persist=False)

        save.assert_not_called()

    def test_result_has_no_investigation_id_when_not_persisting(self) -> None:
        result, _, _, _ = self.run_with_mocked_save()

        self.assertEqual(set(result), BASE_KEYS)
        self.assertNotIn("investigation_id", result)

    def test_default_invocation_creates_no_files_in_working_directory(self) -> None:
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.temp_path)

        with patch(PROCESS, return_value=self.pipeline_result):
            run_investigation(["a.txt"])
            run_investigation(["a.txt"], persist=False)

        self.assertEqual(list(self.temp_path.iterdir()), [])

    def test_persist_false_with_valid_db_path_creates_no_file(self) -> None:
        nested = self.temp_path / "sub" / "dossieriq.db"

        _, _, save, _ = self.run_with_mocked_save(persist=False, db_path=nested)

        save.assert_not_called()
        self.assertFalse(nested.exists())
        self.assertEqual(list(self.temp_path.iterdir()), [])

    def test_persist_false_ignores_invalid_db_path(self) -> None:
        invalid_paths = [42, 1.5, ["x"], b"bytes", {"a": 1}, "", "   ", True]
        for invalid in invalid_paths:
            with self.subTest(db_path=invalid):
                result, process, save, _ = self.run_with_mocked_save(
                    persist=False, db_path=invalid
                )

                process.assert_called_once()
                save.assert_not_called()
                self.assertEqual(set(result), BASE_KEYS)


class TestPersistenceEnabled(PersistenceTestCase):
    """persist=True saves via save_investigation() and returns the ID."""

    def test_saves_once_and_returns_investigation_id(self) -> None:
        result, _, save, _ = self.run_with_mocked_save(
            persist=True, db_path=self.db_path
        )

        save.assert_called_once()
        self.assertEqual(result["investigation_id"], "fake-investigation-id")

    def test_save_receives_the_five_base_fields(self) -> None:
        result, _, save, keys_at_save = self.run_with_mocked_save(
            persist=True, db_path=self.db_path
        )

        self.assertEqual(keys_at_save, [BASE_KEYS])
        saved = save.call_args.args[0]
        self.assertIs(saved["documents"], self.pipeline_result["documents"])
        self.assertIs(saved["entities"], self.pipeline_result["entities"])
        self.assertIs(saved["summary"], self.pipeline_result["summary"])
        self.assertIsInstance(saved["graph"], nx.MultiDiGraph)

    def test_caller_supplied_path_is_used(self) -> None:
        for label, supplied in (("Path", self.db_path), ("str", str(self.db_path))):
            with self.subTest(kind=label):
                _, _, save, _ = self.run_with_mocked_save(
                    persist=True, db_path=supplied
                )

                self.assertEqual(len(save.call_args.args), 2)
                self.assertEqual(save.call_args.args[1], supplied)

    def test_default_path_is_used_when_db_path_omitted(self) -> None:
        for kwargs in ({"persist": True}, {"persist": True, "db_path": None}):
            with self.subTest(kwargs=kwargs):
                _, _, save, _ = self.run_with_mocked_save(**kwargs)

                self.assertEqual(save.call_args.args[1], DEFAULT_DB_PATH)

    def test_default_path_is_data_dossieriq_db(self) -> None:
        self.assertEqual(Path(DEFAULT_DB_PATH), Path("data") / "dossieriq.db")

    def test_save_errors_propagate(self) -> None:
        with patch(PROCESS, return_value=self.pipeline_result), \
             patch(SAVE, side_effect=sqlite3.OperationalError("disk full")):
            with self.assertRaises(sqlite3.OperationalError):
                run_investigation(["a.txt"], persist=True, db_path=self.db_path)


class TestRealPersistence(PersistenceTestCase):
    """End to end with the real storage layer and a temporary database."""

    def test_saves_to_the_supplied_database_file(self) -> None:
        with patch(PROCESS, return_value=self.pipeline_result):
            result = run_investigation(
                ["a.txt"], persist=True, db_path=self.db_path
            )

        investigation_id = result["investigation_id"]
        self.assertEqual(str(uuid.UUID(investigation_id)), investigation_id)
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(self.count_rows("investigations"), 1)
        self.assertEqual(self.count_rows("documents"), 1)
        self.assertEqual(self.count_rows("entities"), 2)
        self.assertEqual(self.count_rows("entity_mentions"), 2)
        self.assertEqual(self.count_rows("relationships"), 1)

        with closing(sqlite3.connect(str(self.db_path))) as connection:
            row = connection.execute(
                "SELECT investigation_id FROM investigations"
            ).fetchone()
        self.assertEqual(row[0], investigation_id)

    def test_nested_database_directory_is_created(self) -> None:
        nested = self.temp_path / "storage" / "dossieriq.db"

        with patch(PROCESS, return_value=self.pipeline_result):
            run_investigation(["a.txt"], persist=True, db_path=nested)

        self.assertTrue(nested.is_file())
        self.assertFalse(self.db_path.exists())

    def test_two_runs_create_separate_investigations(self) -> None:
        with patch(PROCESS, side_effect=lambda paths: make_pipeline_result()):
            first = run_investigation(["a.txt"], persist=True, db_path=self.db_path)
            second = run_investigation(["a.txt"], persist=True, db_path=self.db_path)

        self.assertNotEqual(first["investigation_id"], second["investigation_id"])
        self.assertEqual(self.count_rows("investigations"), 2)
        self.assertEqual(self.count_rows("entity_mentions"), 4)

    def test_real_persistence_does_not_alter_returned_graph_data(self) -> None:
        with patch(PROCESS, return_value=self.pipeline_result):
            result = run_investigation(["a.txt"], persist=True, db_path=self.db_path)

        self.assertTrue(result["graph"].has_edge(1, 2))
        self.assertEqual(result["graph_summary"], {"node_count": 2, "edge_count": 1})


class TestReturnFieldsUnchanged(PersistenceTestCase):
    """The existing return fields are present and correct either way."""

    def assert_base_fields(self, result: dict) -> None:
        self.assertIs(result["documents"], self.pipeline_result["documents"])
        self.assertIs(result["entities"], self.pipeline_result["entities"])
        self.assertIs(result["summary"], self.pipeline_result["summary"])
        self.assertEqual(
            result["summary"],
            {"document_count": 1, "entity_mention_count": 2, "unique_entity_count": 2},
        )
        self.assertIsInstance(result["graph"], nx.MultiDiGraph)
        self.assertEqual(set(result["graph"].nodes), {1, 2})
        self.assertEqual(
            result["graph_summary"], {"node_count": 2, "edge_count": 1}
        )
        edge = list(result["graph"].get_edge_data(1, 2).values())[0]
        self.assertEqual(edge["relationship_type"], "ACQUIRED")

    def test_fields_without_persistence(self) -> None:
        result, _, _, _ = self.run_with_mocked_save()

        self.assertEqual(set(result), BASE_KEYS)
        self.assert_base_fields(result)

    def test_fields_with_persistence(self) -> None:
        result, _, _, _ = self.run_with_mocked_save(
            persist=True, db_path=self.db_path
        )

        self.assertEqual(set(result), BASE_KEYS | {"investigation_id"})
        self.assert_base_fields(result)

    def test_persisting_does_not_change_the_base_fields(self) -> None:
        plain, _, _, _ = self.run_with_mocked_save()
        persisted, _, _, _ = self.run_with_mocked_save(
            persist=True, db_path=self.db_path
        )

        for key in ("documents", "entities", "summary", "graph_summary"):
            with self.subTest(key=key):
                self.assertEqual(plain[key], persisted[key])


class TestArgumentValidation(PersistenceTestCase):
    """Invalid persist values and (when persisting) invalid paths."""

    def assert_rejected_before_any_work(self, **kwargs: object) -> None:
        with patch(PROCESS) as process, patch(SAVE) as save:
            with self.assertRaises(ValueError):
                run_investigation(["a.txt"], **kwargs)  # type: ignore[arg-type]

        process.assert_not_called()
        save.assert_not_called()

    def test_invalid_persist_values_raise_value_error(self) -> None:
        for invalid in (None, 0, 1, "yes", "True", [], [True], {}, 1.0):
            with self.subTest(persist=invalid):
                self.assert_rejected_before_any_work(persist=invalid)

    def test_invalid_persist_is_rejected_even_with_valid_path(self) -> None:
        self.assert_rejected_before_any_work(persist="yes", db_path=self.db_path)

    def test_invalid_db_paths_raise_value_error_when_persisting(self) -> None:
        for invalid in (42, 1.5, ["x"], b"bytes", {"a": 1}, True, "", "   ", "\n\t "):
            with self.subTest(db_path=invalid):
                self.assert_rejected_before_any_work(persist=True, db_path=invalid)

    def test_invalid_db_path_creates_no_database(self) -> None:
        original_cwd = os.getcwd()
        self.addCleanup(os.chdir, original_cwd)
        os.chdir(self.temp_path)

        with patch(PROCESS):
            with self.assertRaises(ValueError):
                run_investigation(["a.txt"], persist=True, db_path="   ")

        self.assertEqual(list(self.temp_path.iterdir()), [])

    def test_file_paths_validation_is_unchanged(self) -> None:
        for invalid in (None, "a.txt", 42, ("a.txt",), {"a.txt"}, []):
            with self.subTest(file_paths=invalid):
                with patch(PROCESS) as process, patch(SAVE) as save:
                    with self.assertRaises(ValueError):
                        run_investigation(
                            invalid, persist=True, db_path=self.db_path  # type: ignore[arg-type]
                        )

                process.assert_not_called()
                save.assert_not_called()

    def test_persist_and_db_path_are_keyword_only(self) -> None:
        with self.assertRaises(TypeError):
            run_investigation(["a.txt"], True)  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()