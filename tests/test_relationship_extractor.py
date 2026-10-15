"""Tests for core/relationship_extractor.py (standard-library unittest only).

Run from the project root with:
    python -m unittest tests.test_relationship_extractor -v
or:
    python -m unittest discover -v
"""

import copy
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

from core.relationship_extractor import extract_relationships  # noqa: E402

ENTITY_FIELDS = {
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
RELATIONSHIP_KEYS = {
    "source_entity_id",
    "target_entity_id",
    "relationship_type",
    "document_id",
    "filename",
    "evidence",
}

ACQUISITION = "Orion Systems acquired Delta Research."

# Values of the wrong type for each expected type (bool is included for int).
WRONG_VALUES = {
    int: ["1", 1.5, None, True, False, [1]],
    str: [None, 1, 2.5, ["x"], {"a": 1}, b"bytes"],
}


def make_mention(
    entity_id: int,
    text: str,
    entity_type: str,
    context: str,
    *,
    occurrence: int = 0,
    doc_offset: int = 0,
    document_id: str = "doc-1",
    filename: str = "a.txt",
    **overrides: object,
) -> dict:
    """Build a resolved mention whose offsets are computed from the sentence.

    ``doc_offset`` is where the sentence starts in the (imaginary) document,
    so ``start_char`` is ``doc_offset`` plus the position of the chosen
    occurrence of ``text`` inside ``context``.
    """
    position = -1
    for _ in range(occurrence + 1):
        position = context.index(text, position + 1)

    start = doc_offset + position
    mention = {
        "entity_id": entity_id,
        "entity_text": text,
        "entity_type": entity_type,
        "normalized_name": " ".join(text.split()).casefold(),
        "document_id": document_id,
        "filename": filename,
        "start_char": start,
        "end_char": start + len(text),
        "context": context,
    }
    mention.update(overrides)
    return mention


def make_pair(
    sentence: str,
    left_text: str,
    left_type: str,
    right_text: str,
    right_type: str,
    **kwargs: object,
) -> list[dict]:
    """Build two mentions (entity IDs 1 and 2) found in one sentence."""
    return [
        make_mention(1, left_text, left_type, sentence, **kwargs),
        make_mention(2, right_text, right_type, sentence, **kwargs),
    ]


def acquisition_pair(**kwargs: object) -> list[dict]:
    """Two valid ORG mentions in 'Orion Systems acquired Delta Research.'"""
    return make_pair(
        ACQUISITION, "Orion Systems", "ORG", "Delta Research", "ORG", **kwargs
    )


class TestSupportedPatterns(unittest.TestCase):
    """Every documented pattern, including direction."""

    # (sentence, left text, left type, right text, right type,
    #  relationship type, source is the left mention)
    CASES = [
        ("Orion Systems signed a contract with Delta Research.",
         "Orion Systems", "ORG", "Delta Research", "ORG",
         "SIGNED_CONTRACT_WITH", True),
        ("Orion Systems signed an agreement with Delta Research.",
         "Orion Systems", "ORG", "Delta Research", "ORG",
         "SIGNED_AGREEMENT_WITH", True),
        ("Priya Sharma signed a contract with Orion Systems.",
         "Priya Sharma", "PERSON", "Orion Systems", "ORG",
         "SIGNED_CONTRACT_WITH", True),
        ("Orion Systems signed an agreement with Priya Sharma.",
         "Orion Systems", "ORG", "Priya Sharma", "PERSON",
         "SIGNED_AGREEMENT_WITH", True),
        ("Priya Sharma signed an agreement with Rahul Mehta.",
         "Priya Sharma", "PERSON", "Rahul Mehta", "PERSON",
         "SIGNED_AGREEMENT_WITH", True),
        ("Orion Systems acquired Delta Research.",
         "Orion Systems", "ORG", "Delta Research", "ORG",
         "ACQUIRED", True),
        ("Delta Research was acquired by Orion Systems.",
         "Delta Research", "ORG", "Orion Systems", "ORG",
         "ACQUIRED", False),
        ("Priya Sharma works for Orion Systems.",
         "Priya Sharma", "PERSON", "Orion Systems", "ORG",
         "WORKS_FOR", True),
        ("Priya Sharma is employed by Orion Systems.",
         "Priya Sharma", "PERSON", "Orion Systems", "ORG",
         "WORKS_FOR", True),
    ]

    def test_each_pattern_produces_expected_relationship(self) -> None:
        for sentence, l_text, l_type, r_text, r_type, rel_type, source_left in self.CASES:
            for doc_offset in (0, 250):
                with self.subTest(sentence=sentence, doc_offset=doc_offset):
                    mentions = make_pair(
                        sentence, l_text, l_type, r_text, r_type, doc_offset=doc_offset
                    )
                    left_id, right_id = 1, 2
                    source, target = (
                        (left_id, right_id) if source_left else (right_id, left_id)
                    )

                    result = extract_relationships(mentions)

                    self.assertEqual(
                        result,
                        [
                            {
                                "source_entity_id": source,
                                "target_entity_id": target,
                                "relationship_type": rel_type,
                                "document_id": "doc-1",
                                "filename": "a.txt",
                                "evidence": sentence,
                            }
                        ],
                    )

    def test_passive_acquisition_reverses_direction(self) -> None:
        sentence = "Delta Research was acquired by Orion Systems."
        mentions = make_pair(
            sentence, "Delta Research", "ORG", "Orion Systems", "ORG"
        )  # Delta = 1 (acquired), Orion = 2 (acquirer)

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["relationship_type"], "ACQUIRED")
        self.assertEqual(result[0]["source_entity_id"], 2)
        self.assertEqual(result[0]["target_entity_id"], 1)

    def test_active_and_passive_acquisition_agree_on_direction(self) -> None:
        active = extract_relationships(
            [
                make_mention(1, "Orion Systems", "ORG", "Orion Systems acquired Delta Research."),
                make_mention(2, "Delta Research", "ORG", "Orion Systems acquired Delta Research."),
            ]
        )
        passive_sentence = "Delta Research was acquired by Orion Systems."
        passive = extract_relationships(
            [
                make_mention(1, "Orion Systems", "ORG", passive_sentence),
                make_mention(2, "Delta Research", "ORG", passive_sentence),
            ]
        )

        self.assertEqual(
            (active[0]["source_entity_id"], active[0]["target_entity_id"]),
            (passive[0]["source_entity_id"], passive[0]["target_entity_id"]),
        )
        def test_acquisition_of_minority_stake(self) -> None:
            sentence = (
                "On 3 August 2025, Orion Systems acquired "
                "a minority stake in Northstar Analytics."
            )
            mentions = make_pair(
                sentence,
                "Orion Systems",
                "ORG",
                "Northstar Analytics",
                "ORG",
            )

            result = extract_relationships(mentions)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["relationship_type"], "ACQUIRED")
            self.assertEqual(result[0]["source_entity_id"], 1)
            self.assertEqual(result[0]["target_entity_id"], 2)
            self.assertEqual(result[0]["evidence"], sentence)    

    def test_connecting_phrase_ignores_case_and_repeated_whitespace(self) -> None:
        sentence = "Orion Systems  ACQUIRED   Delta Research."
        mentions = make_pair(sentence, "Orion Systems", "ORG", "Delta Research", "ORG")

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["relationship_type"], "ACQUIRED")
        self.assertEqual(result[0]["evidence"], sentence)

    def test_mention_input_order_does_not_matter(self) -> None:
        mentions = acquisition_pair()
        forward = extract_relationships(mentions)
        backward = extract_relationships(list(reversed(mentions)))

        self.assertEqual(forward, backward)
        self.assertEqual(len(forward), 1)

    def test_three_entities_only_matching_pair_is_linked(self) -> None:
        sentence = "Priya Sharma works for Orion Systems in Pune."
        mentions = [
            make_mention(1, "Priya Sharma", "PERSON", sentence),
            make_mention(2, "Orion Systems", "ORG", sentence),
            make_mention(3, "Pune", "GPE", sentence),
        ]

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_entity_id"], 1)
        self.assertEqual(result[0]["target_entity_id"], 2)
        self.assertEqual(result[0]["relationship_type"], "WORKS_FOR")

    def test_relationships_are_returned_in_sentence_order(self) -> None:
        first = "Orion Systems acquired Delta Research."
        second = "Priya Sharma works for Orion Systems."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", first, doc_offset=0),
            make_mention(2, "Delta Research", "ORG", first, doc_offset=0),
            make_mention(3, "Priya Sharma", "PERSON", second, doc_offset=100),
            make_mention(1, "Orion Systems", "ORG", second, doc_offset=100),
        ]

        result = extract_relationships(mentions)

        self.assertEqual(
            [r["relationship_type"] for r in result], ["ACQUIRED", "WORKS_FOR"]
        )


class TestOutputShape(unittest.TestCase):
    """Returned records follow the schema expected by build_knowledge_graph()."""

    def test_records_have_exactly_the_six_required_keys(self) -> None:
        result = extract_relationships(acquisition_pair())

        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0].keys()), RELATIONSHIP_KEYS)

    def test_field_types_and_values(self) -> None:
        result = extract_relationships(
            acquisition_pair(document_id="doc-9", filename="report.pdf")
        )
        record = result[0]

        for field in ("source_entity_id", "target_entity_id"):
            self.assertIsInstance(record[field], int)
            self.assertNotIsInstance(record[field], bool)
        for field in ("relationship_type", "document_id", "filename", "evidence"):
            self.assertIsInstance(record[field], str)
            self.assertTrue(record[field].strip())
        self.assertEqual(record["document_id"], "doc-9")
        self.assertEqual(record["filename"], "report.pdf")
        self.assertEqual(record["evidence"], ACQUISITION)

    def test_empty_input_returns_empty_list(self) -> None:
        self.assertEqual(extract_relationships([]), [])

    def test_input_is_not_mutated(self) -> None:
        mentions = acquisition_pair() + make_pair(
            "Priya Sharma works for Orion Systems.",
            "Priya Sharma", "PERSON", "Orion Systems", "ORG",
            doc_offset=100,
        )
        snapshot = copy.deepcopy(mentions)

        result = extract_relationships(mentions)

        self.assertEqual(mentions, snapshot)
        self.assertGreater(len(result), 0)
        for record in result:
            for mention in mentions:
                self.assertIsNot(record, mention)


class TestEntityTypeAndIdRules(unittest.TestCase):
    """Entity types must fit the pattern and IDs must differ."""

    def test_disallowed_entity_types_create_no_relationship(self) -> None:
        cases = [
            ("Priya Sharma acquired Orion Systems.",
             "Priya Sharma", "PERSON", "Orion Systems", "ORG"),
            ("Orion Systems acquired Priya Sharma.",
             "Orion Systems", "ORG", "Priya Sharma", "PERSON"),
            ("Orion Systems works for Priya Sharma.",
             "Orion Systems", "ORG", "Priya Sharma", "PERSON"),
            ("Orion Systems works for Delta Research.",
             "Orion Systems", "ORG", "Delta Research", "ORG"),
            ("Priya Sharma works for Rahul Mehta.",
             "Priya Sharma", "PERSON", "Rahul Mehta", "PERSON"),
            ("Priya Sharma is employed by Pune.",
             "Priya Sharma", "PERSON", "Pune", "GPE"),
            ("Pune signed an agreement with Orion Systems.",
             "Pune", "GPE", "Orion Systems", "ORG"),
            ("Orion Systems signed a contract with Pune.",
             "Orion Systems", "ORG", "Pune", "GPE"),
            ("Priya Sharma was acquired by Orion Systems.",
             "Priya Sharma", "PERSON", "Orion Systems", "ORG"),
            ("Delta Research was acquired by Priya Sharma.",
             "Delta Research", "ORG", "Priya Sharma", "PERSON"),
        ]
        for sentence, l_text, l_type, r_text, r_type in cases:
            with self.subTest(sentence=sentence):
                mentions = make_pair(sentence, l_text, l_type, r_text, r_type)

                self.assertEqual(extract_relationships(mentions), [])

    def test_entity_type_comparison_is_case_sensitive(self) -> None:
        mentions = make_pair(ACQUISITION, "Orion Systems", "org", "Delta Research", "org")

        self.assertEqual(extract_relationships(mentions), [])

    def test_same_entity_id_is_never_linked(self) -> None:
        sentence = "Orion Systems acquired OSL."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", sentence),
            make_mention(1, "OSL", "ORG", sentence),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_different_entity_ids_are_linked(self) -> None:
        mentions = acquisition_pair()

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertNotEqual(
            result[0]["source_entity_id"], result[0]["target_entity_id"]
        )


class TestNoInferenceFromCoOccurrence(unittest.TestCase):
    """Only exact phrases in one sentence of one document create edges."""

    def test_cooccurrence_in_one_sentence_is_not_enough(self) -> None:
        sentence = "Orion Systems and Delta Research attended the summit."
        mentions = make_pair(sentence, "Orion Systems", "ORG", "Delta Research", "ORG")

        self.assertEqual(extract_relationships(mentions), [])

    def test_unsupported_wording_creates_no_relationship(self) -> None:
        sentences = [
            "Orion Systems purchased Delta Research.",
            "Orion Systems has acquired Delta Research.",
            "Orion Systems, which acquired Delta Research, grew.",
            "Orion Systems signed a deal with Delta Research.",
            "Orion Systems signed an agreement with the firm Delta Research.",
            "Orion Systems acquired the company Delta Research.",
            "Orion Systems was acquired Delta Research.",
            "Orion Systems works with Delta Research.",
            "Orion Systems finalised an agreement with Delta Research.",
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                mentions = make_pair(
                    sentence, "Orion Systems", "ORG", "Delta Research", "ORG"
                )

                self.assertEqual(extract_relationships(mentions), [])

    def test_unsupported_wording_for_person_patterns(self) -> None:
        sentences = [
            "Priya Sharma worked for Orion Systems.",
            "Priya Sharma works at Orion Systems.",
            "Priya Sharma is hired by Orion Systems.",
        ]
        for sentence in sentences:
            with self.subTest(sentence=sentence):
                mentions = make_pair(
                    sentence, "Priya Sharma", "PERSON", "Orion Systems", "ORG"
                )

                self.assertEqual(extract_relationships(mentions), [])

    def test_entities_in_different_sentences_are_not_linked(self) -> None:
        mentions = [
            make_mention(1, "Orion Systems", "ORG", "Orion Systems opened an office.",
                         doc_offset=0),
            make_mention(2, "Delta Research", "ORG", "Delta Research hired staff.",
                         doc_offset=40),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_entities_in_different_documents_are_not_linked(self) -> None:
        mentions = [
            make_mention(1, "Orion Systems", "ORG", ACQUISITION,
                         document_id="doc-1", filename="a.txt"),
            make_mention(2, "Delta Research", "ORG", ACQUISITION,
                         document_id="doc-2", filename="b.txt"),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_single_mention_creates_no_relationship(self) -> None:
        mentions = [make_mention(1, "Orion Systems", "ORG", ACQUISITION)]

        self.assertEqual(extract_relationships(mentions), [])


class TestDuplicateSuppression(unittest.TestCase):
    """Identical source/target/type/document relationships appear once."""

    def test_same_sentence_repeated_in_document_is_deduplicated(self) -> None:
        mentions = acquisition_pair(doc_offset=0) + acquisition_pair(doc_offset=100)

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)

    def test_same_relationship_in_different_sentences_keeps_first(self) -> None:
        first = "Orion Systems acquired Delta Research."
        second = "Orion Systems acquired Delta Research, reports said."
        mentions = (
            make_pair(first, "Orion Systems", "ORG", "Delta Research", "ORG", doc_offset=0)
            + make_pair(second, "Orion Systems", "ORG", "Delta Research", "ORG", doc_offset=100)
        )

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["evidence"], first)

    def test_same_relationship_in_different_documents_is_kept_per_document(self) -> None:
        mentions = (
            acquisition_pair(document_id="doc-1", filename="a.txt")
            + acquisition_pair(document_id="doc-2", filename="b.txt")
        )

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 2)
        self.assertEqual({r["document_id"] for r in result}, {"doc-1", "doc-2"})
        self.assertEqual({r["filename"] for r in result}, {"a.txt", "b.txt"})

    def test_different_relationship_types_between_same_entities_are_kept(self) -> None:
        contract = "Orion Systems signed a contract with Delta Research."
        agreement = "Orion Systems signed an agreement with Delta Research."
        mentions = (
            make_pair(contract, "Orion Systems", "ORG", "Delta Research", "ORG", doc_offset=0)
            + make_pair(agreement, "Orion Systems", "ORG", "Delta Research", "ORG", doc_offset=100)
        )

        result = extract_relationships(mentions)

        self.assertEqual(
            {r["relationship_type"] for r in result},
            {"SIGNED_CONTRACT_WITH", "SIGNED_AGREEMENT_WITH"},
        )
        self.assertEqual(len(result), 2)

    def test_opposite_directions_are_not_duplicates(self) -> None:
        first = "Orion Systems acquired Delta Research."
        second = "Delta Research acquired Orion Systems."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", first, doc_offset=0),
            make_mention(2, "Delta Research", "ORG", first, doc_offset=0),
            make_mention(2, "Delta Research", "ORG", second, doc_offset=100),
            make_mention(1, "Orion Systems", "ORG", second, doc_offset=100),
        ]

        result = extract_relationships(mentions)

        self.assertEqual(
            {(r["source_entity_id"], r["target_entity_id"]) for r in result},
            {(1, 2), (2, 1)},
        )

    def test_active_and_passive_statements_of_same_fact_are_deduplicated(self) -> None:
        active = "Orion Systems acquired Delta Research."
        passive = "Delta Research was acquired by Orion Systems."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", active, doc_offset=0),
            make_mention(2, "Delta Research", "ORG", active, doc_offset=0),
            make_mention(1, "Orion Systems", "ORG", passive, doc_offset=100),
            make_mention(2, "Delta Research", "ORG", passive, doc_offset=100),
        ]

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["evidence"], active)


class TestAmbiguityAndAlignment(unittest.TestCase):
    """Repeated text and bad offsets must never create relationships."""

    def test_repeated_left_text_in_context_is_skipped(self) -> None:
        sentence = "Orion acquired Delta Research, and Orion later grew."
        mentions = [
            make_mention(1, "Orion", "ORG", sentence, occurrence=0),
            make_mention(2, "Delta Research", "ORG", sentence),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_repeated_right_text_in_context_is_skipped(self) -> None:
        sentence = "Orion Systems acquired Delta, and Delta later grew."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", sentence),
            make_mention(2, "Delta", "ORG", sentence, occurrence=0),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_mention_text_that_is_substring_of_other_text_is_skipped(self) -> None:
        sentence = "Apex acquired Apex Labs."
        mentions = [
            make_mention(1, "Apex", "ORG", sentence, occurrence=0),
            make_mention(2, "Apex Labs", "ORG", sentence),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_both_occurrences_of_repeated_text_are_skipped(self) -> None:
        sentence = "Orion acquired Delta Research, and Orion later grew."
        mentions = [
            make_mention(1, "Orion", "ORG", sentence, occurrence=0),
            make_mention(1, "Orion", "ORG", sentence, occurrence=1),
            make_mention(2, "Delta Research", "ORG", sentence),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_right_mention_offsets_shifted_forward_are_skipped(self) -> None:
        mentions = acquisition_pair()
        right = mentions[1]
        right["start_char"] += 3
        right["end_char"] += 3

        self.assertEqual(extract_relationships(mentions), [])

    def test_right_mention_offsets_shifted_backward_are_skipped(self) -> None:
        mentions = acquisition_pair()
        right = mentions[1]
        right["start_char"] -= 3
        right["end_char"] -= 3

        self.assertEqual(extract_relationships(mentions), [])

    def test_left_mention_offsets_shifted_are_skipped(self) -> None:
        mentions = acquisition_pair(doc_offset=10)
        left = mentions[0]
        left["start_char"] += 3
        left["end_char"] += 3

        self.assertEqual(extract_relationships(mentions), [])

    def test_span_length_not_matching_text_length_is_skipped(self) -> None:
        mentions = acquisition_pair()
        mentions[1]["end_char"] += 1  # still end > start, but wrong length

        self.assertEqual(extract_relationships(mentions), [])

    def test_negative_implied_sentence_offset_is_skipped(self) -> None:
        sentence = "Yesterday, Orion Systems acquired Delta Research."
        # doc_offset -9 puts Orion at start_char 2, which would imply the
        # sentence starts before the beginning of the document.
        mentions = make_pair(
            sentence, "Orion Systems", "ORG", "Delta Research", "ORG", doc_offset=-9
        )
        self.assertEqual(mentions[0]["start_char"], 2)

        self.assertEqual(extract_relationships(mentions), [])

    def test_overlapping_mentions_are_skipped(self) -> None:
        sentence = "Orion Systems acquired Delta Research."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", sentence),
            make_mention(2, "Systems acquired", "ORG", sentence),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_correct_offsets_still_match_after_misalignment_cases(self) -> None:
        # Sanity check that the helper builds aligned mentions by default.
        for doc_offset in (0, 1, 37, 1000):
            with self.subTest(doc_offset=doc_offset):
                result = extract_relationships(acquisition_pair(doc_offset=doc_offset))

                self.assertEqual(len(result), 1)


class TestValidation(unittest.TestCase):
    """Malformed input raises ValueError."""

    
def valid_mention(self, **overrides: object) -> dict:
    entity_id = overrides.pop("entity_id", 1)
    return make_mention(
        entity_id, "Orion Systems", "ORG", ACQUISITION, **overrides
    )


    def test_non_list_input_raises_value_error(self) -> None:
        for invalid in (None, "text", 42, {"entity_id": 1}, (self.valid_mention(),), {1, 2}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    extract_relationships(invalid)  # type: ignore[arg-type]

    def test_non_dictionary_records_raise_value_error(self) -> None:
        for bad in (None, "entity", 42, ["x"], ("x",)):
            with self.subTest(record=bad):
                with self.assertRaises(ValueError):
                    extract_relationships([self.valid_mention(), bad])  # type: ignore[list-item]

    def test_missing_fields_raise_value_error(self) -> None:
        for field in ENTITY_FIELDS:
            with self.subTest(missing=field):
                mention = self.valid_mention()
                del mention[field]

                with self.assertRaises(ValueError) as context:
                    extract_relationships([mention])

                self.assertIn(field, str(context.exception))

    def test_wrong_field_types_raise_value_error(self) -> None:
        for field, expected_type in ENTITY_FIELDS.items():
            for bad_value in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad_value):
                    with self.assertRaises(ValueError) as context:
                        extract_relationships([self.valid_mention(**{field: bad_value})])

                    self.assertIn(field, str(context.exception))

    def test_boolean_ids_and_offsets_are_rejected(self) -> None:
        for field in ("entity_id", "start_char", "end_char"):
            for bad_value in (True, False):
                with self.subTest(field=field, value=bad_value):
                    with self.assertRaises(ValueError):
                        extract_relationships([self.valid_mention(**{field: bad_value})])

    def test_zero_and_negative_entity_ids_raise_value_error(self) -> None:
        for bad_id in (0, -1, -100):
            with self.subTest(entity_id=bad_id):
                with self.assertRaises(ValueError) as context:
                    extract_relationships([self.valid_mention(entity_id=bad_id)])

                self.assertIn("entity_id", str(context.exception))

    def test_empty_strings_raise_value_error(self) -> None:
        fields = ("entity_text", "entity_type", "document_id", "filename", "context")
        for field in fields:
            for empty_value in ("", "   ", "\n\t "):
                with self.subTest(field=field, value=empty_value):
                    with self.assertRaises(ValueError) as context:
                        extract_relationships([self.valid_mention(**{field: empty_value})])

                    self.assertIn(field, str(context.exception))

    def test_negative_start_offset_raises_value_error(self) -> None:
        for start in (-1, -10):
            with self.subTest(start=start):
                with self.assertRaises(ValueError) as context:
                    extract_relationships(
                        [self.valid_mention(start_char=start, end_char=5)]
                    )

                self.assertIn("start_char", str(context.exception))

    def test_end_offset_not_greater_than_start_raises_value_error(self) -> None:
        for start, end in ((5, 5), (5, 4), (10, 0), (0, 0)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError) as context:
                    extract_relationships(
                        [self.valid_mention(start_char=start, end_char=end)]
                    )

                self.assertIn("end_char", str(context.exception))

    def test_one_invalid_record_rejects_the_whole_input(self) -> None:
        mentions = acquisition_pair()
        mentions.append(self.valid_mention(entity_id=0))

        with self.assertRaises(ValueError):
            extract_relationships(mentions)

    def test_inconsistent_filenames_in_same_sentence_raise_value_error(self) -> None:
        mentions = [
            make_mention(1, "Orion Systems", "ORG", ACQUISITION, filename="a.txt"),
            make_mention(2, "Delta Research", "ORG", ACQUISITION, filename="b.txt"),
        ]

        with self.assertRaises(ValueError) as context:
            extract_relationships(mentions)

        self.assertIn("filename", str(context.exception).lower())

    def test_inconsistent_filenames_raise_even_without_a_relationship(self) -> None:
        sentence = "Orion Systems and Delta Research attended the summit."
        mentions = [
            make_mention(1, "Orion Systems", "ORG", sentence, filename="a.txt"),
            make_mention(2, "Delta Research", "ORG", sentence, filename="b.txt"),
        ]

        with self.assertRaises(ValueError):
            extract_relationships(mentions)

    def test_different_filenames_in_different_sentences_are_allowed(self) -> None:
        mentions = [
            make_mention(1, "Orion Systems", "ORG", "Orion Systems opened an office.",
                         filename="a.txt"),
            make_mention(2, "Delta Research", "ORG", "Delta Research hired staff.",
                         filename="b.txt"),
        ]

        self.assertEqual(extract_relationships(mentions), [])

    def test_same_filename_in_different_documents_is_allowed(self) -> None:
        mentions = (
            acquisition_pair(document_id="doc-1", filename="same.txt")
            + acquisition_pair(document_id="doc-2", filename="same.txt")
        )

        result = extract_relationships(mentions)

        self.assertEqual(len(result), 2)


if __name__ == "__main__":
    unittest.main()