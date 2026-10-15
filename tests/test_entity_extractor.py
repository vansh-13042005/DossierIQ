"""Tests for core/entity_extractor.py (standard-library unittest only).

Run from the project root with:
    python -m unittest tests.test_entity_extractor -v
or:
    python -m unittest discover -v
"""

import sys
import unittest
from pathlib import Path

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.entity_extractor import extract_entities  # noqa: E402

REQUIRED_KEYS = {
    "entity_text",
    "entity_type",
    "document_id",
    "filename",
    "start_char",
    "end_char",
    "context",
}

# Sample text rich in names, organizations, places and dates. Tests below
# never assert which specific entities spaCy finds, only the structure of
# whatever it returns.
SAMPLE_TEXT = (
    "Apple Inc. was founded by Steve Jobs in California in 1976. "
    "Microsoft signed an agreement with Infosys in Bangalore on 12 June 2023. "
    "Barack Obama visited Paris last Tuesday."
)


def make_document(**overrides: object) -> dict:
    """Build a valid document dictionary, optionally overriding fields."""
    document = {
        "document_id": "doc-123",
        "filename": "sample.txt",
        "text": SAMPLE_TEXT,
    }
    document.update(overrides)
    return document


class TestExtractEntitiesOutput(unittest.TestCase):
    """Tests for the structure of extract_entities() results."""
    
class TestExtractEntities(unittest.TestCase):

    def test_existing_example(self):
        # Your existing test code stays here.
        ...

    def test_extracts_organization_missed_by_spacy(self):
        text = (
            "Orion Systems signed an agreement with "
            "Delta Research in Pune on 12 June."
        )
        document = {
            "document_id": "debug-1",
            "filename": "sample.txt",
            "text": text,
        }

        entities = extract_entities(document)

        organization_names = {
            entity["entity_text"]
            for entity in entities
            if entity["entity_type"] == "ORG"
        }

        self.assertIn("Orion Systems", organization_names)
        self.assertIn("Delta Research", organization_names)

        orion = next(
            entity for entity in entities
            if entity["entity_text"] == "Orion Systems"
        )

        self.assertEqual(
            orion["start_char"],
            text.index("Orion Systems"),
        )
        self.assertEqual(
            orion["end_char"],
            text.index("Orion Systems") + len("Orion Systems"),
        )

    def setUp(self) -> None:
        self.document = make_document()
        self.entities = extract_entities(self.document)

    def test_returns_a_list(self) -> None:
        self.assertIsInstance(self.entities, list)

    def test_sample_text_produces_at_least_one_entity(self) -> None:
        # Guards the other tests from passing vacuously on an empty list.
        self.assertGreater(len(self.entities), 0)

    def test_each_entity_has_all_required_keys(self) -> None:
        for entity in self.entities:
            self.assertEqual(set(entity.keys()), REQUIRED_KEYS)

    def test_entity_text_matches_source_slice(self) -> None:
        text = self.document["text"]
        for entity in self.entities:
            start, end = entity["start_char"], entity["end_char"]
            self.assertIsInstance(start, int)
            self.assertIsInstance(end, int)
            self.assertLess(start, end)
            self.assertEqual(text[start:end], entity["entity_text"])

    def test_document_id_and_filename_are_preserved(self) -> None:
        for entity in self.entities:
            self.assertEqual(entity["document_id"], self.document["document_id"])
            self.assertEqual(entity["filename"], self.document["filename"])

    def test_entity_type_is_non_empty_string(self) -> None:
        for entity in self.entities:
            self.assertIsInstance(entity["entity_type"], str)
            self.assertTrue(entity["entity_type"])

    def test_context_is_non_empty_string(self) -> None:
        for entity in self.entities:
            self.assertIsInstance(entity["context"], str)
            self.assertTrue(entity["context"].strip())

    def test_context_contains_entity_text(self) -> None:
        for entity in self.entities:
            self.assertIn(entity["entity_text"], entity["context"])

    def test_context_comes_from_source_text(self) -> None:
        for entity in self.entities:
            self.assertIn(entity["context"], self.document["text"])

    
    def test_repeated_mentions_are_kept_separate(self) -> None:
        text = (
            "Barack Obama visited Paris. "
            "Later, Barack Obama returned to Paris."
        )
        entities = extract_entities(make_document(text=text))

        obama_mentions = [
            entity for entity in entities
            if entity["entity_text"] == "Barack Obama"
        ]
        self.assertEqual(len(obama_mentions), 2)

        spans = [
            (entity["start_char"], entity["end_char"])
            for entity in entities
        ]
        self.assertEqual(len(spans), len(set(spans)))


    def test_text_without_entities_returns_empty_list(self) -> None:
        entities = extract_entities(make_document(text="... !!! ???"))

        self.assertEqual(entities, [])

    def test_input_document_is_not_modified(self) -> None:
        document = make_document()
        original = dict(document)

        extract_entities(document)

        self.assertEqual(document, original)
        


class TestExtractEntitiesValidation(unittest.TestCase):
    """Tests for input validation in extract_entities()."""

    def test_non_dictionary_inputs_raise_value_error(self) -> None:
        invalid_inputs = [None, "some text", 42, ["text"], ("text",)]
        for invalid in invalid_inputs:
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    extract_entities(invalid)  # type: ignore[arg-type]

    def test_missing_required_fields_raise_value_error(self) -> None:
        for field in ("document_id", "filename", "text"):
            with self.subTest(missing=field):
                document = make_document()
                del document[field]

                with self.assertRaises(ValueError) as context:
                    extract_entities(document)

                self.assertIn(field, str(context.exception))

    def test_empty_required_strings_raise_value_error(self) -> None:
        for field in ("document_id", "filename", "text"):
            for empty_value in ("", "   ", "\n\t"):
                with self.subTest(field=field, value=empty_value):
                    document = make_document(**{field: empty_value})

                    with self.assertRaises(ValueError) as context:
                        extract_entities(document)

                    self.assertIn(field, str(context.exception))

    def test_non_string_required_fields_raise_value_error(self) -> None:
        for field in ("document_id", "filename", "text"):
            for bad_value in (None, 123, 4.5, ["text"], {"a": 1}):
                with self.subTest(field=field, value=bad_value):
                    document = make_document(**{field: bad_value})

                    with self.assertRaises(ValueError) as context:
                        extract_entities(document)

                    self.assertIn(field, str(context.exception))


if __name__ == "__main__":
    unittest.main()