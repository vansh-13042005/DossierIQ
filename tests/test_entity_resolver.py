
"""Tests for core/entity_resolver.py using standard-library unittest."""

import copy
import unittest

from core.entity_resolver import resolve_entities

ORIGINAL_FIELDS = {
    "entity_text",
    "entity_type",
    "document_id",
    "filename",
    "start_char",
    "end_char",
    "context",
}
OUTPUT_FIELDS = ORIGINAL_FIELDS | {"normalized_name", "entity_id"}



def make_mention(entity_text="John Smith", **overrides):
    """Build a valid entity mention, optionally overriding fields."""
    mention = {
        "entity_text": entity_text,
        "entity_type": "PERSON",
        "document_id": "doc-1",
        "filename": "sample.txt",
        "start_char": 0,
        "end_char": len(entity_text) if isinstance(entity_text, str) else 1,
        "context": (
            f"{entity_text} attended the meeting."
            if isinstance(entity_text, str)
            else "Sample context."
        ),
    }
    mention.update(overrides)
    return mention



class TestResolveEntitiesBasics(unittest.TestCase):

    def test_empty_list(self):
        self.assertEqual(resolve_entities([]), [])

    def test_single_mention(self):
        result = resolve_entities([make_mention("  John   SMITH ")])
        self.assertEqual(result[0]["entity_id"], 1)
        self.assertEqual(result[0]["normalized_name"], "john smith")

    def test_case_and_whitespace_variants_share_id(self):
        names = [
            "John Smith",
            "john smith",
            "JOHN SMITH",
            "  John    Smith  ",
            "John\tSmith",
        ]
        result = resolve_entities([make_mention(name) for name in names])
        self.assertEqual(
            {record["entity_id"] for record in result}, {1}
        )
        self.assertEqual(
            {record["normalized_name"] for record in result},
            {"john smith"},
        )

    def test_different_types_get_different_ids(self):
        result = resolve_entities([
            make_mention("Paris", entity_type="GPE"),
            make_mention("Paris", entity_type="PERSON"),
        ])
        self.assertEqual([r["entity_id"] for r in result], [1, 2])

    def test_entity_type_comparison_is_case_sensitive(self):
        result = resolve_entities([
            make_mention("Paris", entity_type="GPE"),
            make_mention("Paris", entity_type="gpe"),
        ])
        self.assertNotEqual(
            result[0]["entity_id"], result[1]["entity_id"]
        )

    def test_similar_names_are_not_merged(self):
        pairs = [
            ("John Smith", "John Jones"),
            ("John Smith", "John"),
            ("Smith", "John Smith"),
            ("Apple", "Apple Inc."),
        ]
        for first, second in pairs:
            with self.subTest(first=first, second=second):
                result = resolve_entities([
                    make_mention(first), make_mention(second)
                ])
                self.assertNotEqual(
                    result[0]["entity_id"], result[1]["entity_id"]
                )

    def test_repeated_mentions_share_id_but_remain_separate(self):
        mentions = [
            make_mention(
                "Delta Research", entity_type="ORG",
                start_char=0, end_char=14,
            ),
            make_mention(
                "Delta Research", entity_type="ORG",
                start_char=50, end_char=64,
            ),
            make_mention(
                "Delta Research", entity_type="ORG",
                start_char=90, end_char=104,
            ),
        ]
        result = resolve_entities(mentions)
        self.assertEqual(len(result), 3)
        self.assertEqual(
            {record["entity_id"] for record in result}, {1}
        )
        self.assertEqual(
            [r["start_char"] for r in result], [0, 50, 90]
        )

    def test_ids_follow_first_appearance(self):
        names = ["Zeta", "Alpha", "zeta", "Beta", "ALPHA"]
        result = resolve_entities([make_mention(n) for n in names])
        self.assertEqual(
            [r["entity_id"] for r in result], [1, 2, 1, 3, 2]
        )

    def test_ids_are_deterministic(self):
        mentions = [
            make_mention("Zeta"),
            make_mention("Alpha"),
            make_mention("zeta"),
        ]
        self.assertEqual(
            resolve_entities(mentions), resolve_entities(mentions)
        )

    def test_ids_restart_each_call(self):
        resolve_entities([
            make_mention("Alpha"), make_mention("Beta")
        ])
        result = resolve_entities([make_mention("Gamma")])
        self.assertEqual(result[0]["entity_id"], 1)


class TestResolveEntitiesOutput(unittest.TestCase):

    def test_output_fields(self):
        result = resolve_entities([
            make_mention("John Smith"),
            make_mention("Paris", entity_type="GPE"),
        ])
        for record in result:
            self.assertEqual(set(record.keys()), OUTPUT_FIELDS)
            self.assertIsInstance(record["normalized_name"], str)
            self.assertIsInstance(record["entity_id"], int)

    def test_original_order_and_values_are_preserved(self):
        mentions = [
            make_mention("Zeta Corp", entity_type="ORG"),
            make_mention("Alpha"),
            make_mention("zeta corp", entity_type="ORG"),
        ]
        result = resolve_entities(mentions)
        self.assertEqual(len(result), len(mentions))
        for original, record in zip(mentions, result):
            for field in ORIGINAL_FIELDS:
                self.assertEqual(record[field], original[field])

    def test_input_is_not_mutated(self):
        mentions = [
            make_mention("John Smith"),
            make_mention("  john   smith "),
        ]
        snapshot = copy.deepcopy(mentions)
        result = resolve_entities(mentions)

        self.assertEqual(mentions, snapshot)
        self.assertIsNot(result, mentions)
        for record, mention in zip(result, mentions):
            self.assertIsNot(record, mention)
            self.assertNotIn("entity_id", mention)
            self.assertNotIn("normalized_name", mention)


class TestResolveEntitiesValidation(unittest.TestCase):

    def assert_value_error(self, entities):
        with self.assertRaises(ValueError):
            resolve_entities(entities)

    def test_invalid_top_level_input(self):
        for invalid in (None, "text", 42, {"entity_text": "x"}, ("a",), {1, 2}):
            with self.subTest(invalid=invalid):
                self.assert_value_error(invalid)

    def test_non_dictionary_entries(self):
        for invalid in (None, "John Smith", 42, ["John"], ("John",)):
            with self.subTest(entry=invalid):
                self.assert_value_error([make_mention(), invalid])

    def test_missing_fields(self):
        for field in ORIGINAL_FIELDS:
            with self.subTest(field=field):
                mention = make_mention()
                del mention[field]
                with self.assertRaises(ValueError):
                    resolve_entities([mention])

    def test_incorrect_string_field_types(self):
        fields = [
            "entity_text", "entity_type", "document_id",
            "filename", "context",
        ]
        for field in fields:
            for invalid in (None, 123, 4.5, ["x"], {"a": 1}, b"bytes"):
                with self.subTest(field=field, value=invalid):
                    with self.assertRaises(ValueError):
                        resolve_entities([
                            make_mention(**{field: invalid})
                        ])

    def test_incorrect_offset_types(self):
        for field in ("start_char", "end_char"):
            for invalid in (None, "5", 1.5, [1], {"a": 1}):
                with self.subTest(field=field, value=invalid):
                    with self.assertRaises(ValueError):
                        resolve_entities([
                            make_mention(**{field: invalid})
                        ])

    def test_boolean_offsets_are_rejected(self):
        cases = [
            {"start_char": True, "end_char": 10},
            {"start_char": False, "end_char": 10},
            {"start_char": 0, "end_char": True},
            {"start_char": 0, "end_char": False},
            {"start_char": True, "end_char": True},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides):
                self.assert_value_error([make_mention(**overrides)])

    def test_empty_entity_text(self):
        for value in ("", "   ", "\n\t "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolve_entities([make_mention(entity_text=value)])

    def test_empty_entity_type(self):
        for value in ("", "   ", "\n\t "):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    resolve_entities([make_mention(entity_type=value)])

    def test_negative_start_offset(self):
        for start in (-1, -10):
            with self.subTest(start=start):
                with self.assertRaises(ValueError):
                    resolve_entities([
                        make_mention(start_char=start, end_char=5)
                    ])

    def test_end_offset_not_greater_than_start(self):
        for start, end in [(5, 5), (5, 4), (10, 0), (0, 0)]:
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    resolve_entities([
                        make_mention(start_char=start, end_char=end)
                    ])

    def test_minimal_valid_offsets(self):
        result = resolve_entities([
            make_mention(start_char=0, end_char=1)
        ])
        self.assertEqual(len(result), 1)

    def test_one_invalid_entry_rejects_whole_input(self):
        mentions = [
            make_mention("John Smith"),
            make_mention("Paris", start_char=-1),
        ]
        self.assert_value_error(mentions)


if __name__ == "__main__":
    unittest.main()
