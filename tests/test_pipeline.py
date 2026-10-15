"""Tests for core/pipeline.py (standard-library unittest and unittest.mock only).

Run from the project root with:
    python -m unittest tests.test_pipeline -v
or:
    python -m unittest discover -v
"""

import unittest
from unittest.mock import patch

from core.pipeline import process_documents

# Names are patched where pipeline.py looks them up.
LOAD = "core.pipeline.load_document"
EXTRACT = "core.pipeline.extract_entities"
RESOLVE = "core.pipeline.resolve_entities"


def make_document(name: str) -> dict:
    """Build a fake loaded document."""
    return {
        "document_id": f"id-{name}",
        "filename": name,
        "file_type": "txt",
        "text": f"Text of {name}.",
        "character_count": len(f"Text of {name}."),
    }


def make_mention(text: str, document: dict, entity_type: str = "ORG") -> dict:
    """Build a fake entity mention belonging to a document."""
    return {
        "entity_text": text,
        "entity_type": entity_type,
        "document_id": document["document_id"],
        "filename": document["filename"],
        "start_char": 0,
        "end_char": len(text),
        "context": f"{text} appears here.",
    }


def fake_resolver(mentions: list[dict]) -> list[dict]:
    """Minimal stand-in for resolve_entities: IDs by (lowercase text, type)."""
    ids: dict[tuple[str, str], int] = {}
    resolved = []
    for mention in mentions:
        key = (
    " ".join(mention["entity_text"].split()).casefold(),
    mention["entity_type"],
)
        ids.setdefault(key, len(ids) + 1)
        record = dict(mention)
        record["normalized_name"] = key[0]
        record["entity_id"] = ids[key]
        resolved.append(record)
    return resolved


class TestProcessDocumentsValidation(unittest.TestCase):
    """Tests for input validation."""

    def test_non_list_input_raises_value_error(self) -> None:
        for invalid in (None, "a.txt", 42, ("a.txt",), {"a.txt"}, {"path": "a.txt"}):
            with self.subTest(invalid=invalid):
                with patch(LOAD) as load:
                    with self.assertRaises(ValueError):
                        process_documents(invalid)  # type: ignore[arg-type]
                    load.assert_not_called()

    def test_empty_list_raises_value_error(self) -> None:
        with patch(LOAD) as load:
            with self.assertRaises(ValueError):
                process_documents([])
            load.assert_not_called()


class TestProcessDocumentsResults(unittest.TestCase):
    """Tests for the pipeline's output with mocked components."""

    def setUp(self) -> None:
        self.docs = {name: make_document(name) for name in ("a.txt", "b.txt", "c.txt")}

    def run_pipeline(self, paths: list[str], mentions_by_file: dict[str, list[dict]]):
        """Run process_documents with loader/extractor mocked, real-ish resolver."""
        docs = self.docs

        def load_side_effect(path: str) -> dict:
            return docs[path]

        def extract_side_effect(document: dict) -> list[dict]:
            return mentions_by_file.get(document["filename"], [])

        with patch(LOAD, side_effect=load_side_effect) as load, \
             patch(EXTRACT, side_effect=extract_side_effect) as extract, \
             patch(RESOLVE, side_effect=fake_resolver) as resolve:
            result = process_documents(paths)
        return result, load, extract, resolve

    def test_result_has_exactly_three_keys(self) -> None:
        result, *_ = self.run_pipeline(["a.txt"], {})

        self.assertEqual(set(result.keys()), {"documents", "entities", "summary"})
        self.assertEqual(
            set(result["summary"].keys()),
            {"document_count", "entity_mention_count", "unique_entity_count"},
        )

    def test_single_document(self) -> None:
        a = self.docs["a.txt"]
        mentions = {"a.txt": [make_mention("Orion", a), make_mention("Delta", a)]}

        result, load, extract, _ = self.run_pipeline(["a.txt"], mentions)

        self.assertEqual(result["documents"], [a])
        self.assertEqual([e["entity_text"] for e in result["entities"]], ["Orion", "Delta"])
        load.assert_called_once_with("a.txt")
        extract.assert_called_once_with(a)
        self.assertEqual(
            result["summary"],
            {"document_count": 1, "entity_mention_count": 2, "unique_entity_count": 2},
        )

    def test_multiple_documents(self) -> None:
        a, b = self.docs["a.txt"], self.docs["b.txt"]
        mentions = {
            "a.txt": [make_mention("Orion", a)],
            "b.txt": [make_mention("Delta", b), make_mention("Pune", b, "GPE")],
        }

        result, load, extract, _ = self.run_pipeline(["a.txt", "b.txt"], mentions)

        self.assertEqual(load.call_count, 2)
        self.assertEqual(extract.call_count, 2)
        self.assertEqual(result["summary"]["document_count"], 2)
        self.assertEqual(result["summary"]["entity_mention_count"], 3)

    def test_document_order_is_preserved(self) -> None:
        paths = ["c.txt", "a.txt", "b.txt"]

        result, *_ = self.run_pipeline(paths, {})

        self.assertEqual([d["filename"] for d in result["documents"]], paths)

    def test_mention_order_follows_document_then_mention_order(self) -> None:
        a, b = self.docs["a.txt"], self.docs["b.txt"]
        mentions = {
            "a.txt": [make_mention("A1", a), make_mention("A2", a)],
            "b.txt": [make_mention("B1", b), make_mention("B2", b)],
        }

        result, *_ = self.run_pipeline(["b.txt", "a.txt"], mentions)

        self.assertEqual(
            [e["entity_text"] for e in result["entities"]],
            ["B1", "B2", "A1", "A2"],
        )

    def test_resolver_is_called_exactly_once_with_all_mentions(self) -> None:
        a, b, c = self.docs["a.txt"], self.docs["b.txt"], self.docs["c.txt"]
        mentions = {
            "a.txt": [make_mention("Orion", a)],
            "b.txt": [],
            "c.txt": [make_mention("Delta", c), make_mention("Pune", c, "GPE")],
        }

        _, _, _, resolve = self.run_pipeline(["a.txt", "b.txt", "c.txt"], mentions)

        resolve.assert_called_once()
        passed = resolve.call_args.args[0]
        self.assertEqual(
            passed,
            mentions["a.txt"] + mentions["b.txt"] + mentions["c.txt"],
        )

    def test_matching_entities_across_documents_share_ids(self) -> None:
        a, b = self.docs["a.txt"], self.docs["b.txt"]
        mentions = {
            "a.txt": [make_mention("Orion Systems", a), make_mention("Pune", a, "GPE")],
            "b.txt": [make_mention("orion systems", b), make_mention("Delta", b)],
        }

        result, *_ = self.run_pipeline(["a.txt", "b.txt"], mentions)
        entities = result["entities"]

        self.assertEqual(entities[0]["entity_id"], entities[2]["entity_id"])
        self.assertEqual(entities[0]["document_id"], a["document_id"])
        self.assertEqual(entities[2]["document_id"], b["document_id"])
        self.assertEqual(len({e["entity_id"] for e in entities}), 3)

    def test_summary_counts_repeated_mentions_but_unique_ids(self) -> None:
        a, b = self.docs["a.txt"], self.docs["b.txt"]
        mentions = {
            "a.txt": [make_mention("Orion", a), make_mention("Orion", a)],
            "b.txt": [make_mention("Orion", b)],
        }

        result, *_ = self.run_pipeline(["a.txt", "b.txt"], mentions)

        self.assertEqual(
            result["summary"],
            {"document_count": 2, "entity_mention_count": 3, "unique_entity_count": 1},
        )

    def test_no_entities_found(self) -> None:
        result, _, _, resolve = self.run_pipeline(["a.txt", "b.txt"], {})

        self.assertEqual(result["entities"], [])
        self.assertEqual(
            result["summary"],
            {"document_count": 2, "entity_mention_count": 0, "unique_entity_count": 0},
        )
        resolve.assert_called_once_with([])


class TestProcessDocumentsErrors(unittest.TestCase):
    """Tests that errors from components propagate."""

    def test_loader_file_not_found_propagates(self) -> None:
        with patch(LOAD, side_effect=FileNotFoundError("missing.txt")), \
             patch(EXTRACT) as extract, \
             patch(RESOLVE) as resolve:
            with self.assertRaises(FileNotFoundError):
                process_documents(["missing.txt"])

        extract.assert_not_called()
        resolve.assert_not_called()

    def test_loader_value_error_propagates(self) -> None:
        with patch(LOAD, side_effect=ValueError("unsupported")), \
             patch(EXTRACT), patch(RESOLVE):
            with self.assertRaises(ValueError) as context:
                process_documents(["data.csv"])

        self.assertIn("unsupported", str(context.exception))

    def test_failure_on_later_file_is_not_skipped_and_resolver_not_called(self) -> None:
        good = make_document("a.txt")

        def load_side_effect(path: str) -> dict:
            if path == "bad.pdf":
                raise ValueError("unreadable PDF")
            return good

        with patch(LOAD, side_effect=load_side_effect), \
             patch(EXTRACT, return_value=[]), \
             patch(RESOLVE) as resolve:
            with self.assertRaises(ValueError):
                process_documents(["a.txt", "bad.pdf"])

        resolve.assert_not_called()

    def test_extractor_error_propagates(self) -> None:
        with patch(LOAD, return_value=make_document("a.txt")), \
             patch(EXTRACT, side_effect=ValueError("bad document")), \
             patch(RESOLVE) as resolve:
            with self.assertRaises(ValueError):
                process_documents(["a.txt"])

        resolve.assert_not_called()

    def test_resolver_error_propagates(self) -> None:
        with patch(LOAD, return_value=make_document("a.txt")), \
             patch(EXTRACT, return_value=[]), \
             patch(RESOLVE, side_effect=ValueError("bad mentions")):
            with self.assertRaises(ValueError):
                process_documents(["a.txt"])


if __name__ == "__main__":
    unittest.main()