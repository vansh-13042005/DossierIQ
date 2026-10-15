"""Tests for core/knowledge_graph.py (standard-library unittest only).

Run from the project root with:
    python -m unittest tests.test_knowledge_graph -v
or:
    python -m unittest discover -v
"""

import copy
import unittest

import networkx as nx

from core.knowledge_graph import build_knowledge_graph

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
RELATIONSHIP_FIELDS = {
    "source_entity_id": int,
    "target_entity_id": int,
    "relationship_type": str,
    "document_id": str,
    "filename": str,
    "evidence": str,
}
MENTION_EVIDENCE_FIELDS = {
    "entity_text",
    "document_id",
    "filename",
    "start_char",
    "end_char",
    "context",
}
EDGE_FIELDS = {"relationship_type", "document_id", "filename", "evidence"}

# Values of the wrong type for each expected type (bool is included for int).
WRONG_VALUES = {
    int: ["1", 1.5, None, True, False, [1]],
    str: [None, 1, 2.5, ["x"], {"a": 1}, b"bytes"],
}



def make_entity(
    entity_id: int = 1,
    entity_text: str = "Orion Systems",
    **overrides: object,
) -> dict:
    """Build a valid resolved entity mention, optionally overriding fields."""
    valid_text = isinstance(entity_text, str)

    entity = {
        "entity_id": entity_id,
        "entity_text": entity_text,
        "entity_type": "ORG",
        "normalized_name": (
            entity_text.casefold() if valid_text else "orion systems"
        ),
        "document_id": "doc-1",
        "filename": "a.txt",
        "start_char": 0,
        "end_char": len(entity_text) if valid_text else 1,
        "context": (
            f"{entity_text} signed an agreement."
            if valid_text
            else "Sample context."
        ),
    }
    entity.update(overrides)
    return entity


def make_relationship(source: int = 1, target: int = 2, **overrides: object) -> dict:
    """Build a valid relationship record, optionally overriding fields."""
    relationship = {
        "source_entity_id": source,
        "target_entity_id": target,
        "relationship_type": "SIGNED_WITH",
        "document_id": "doc-1",
        "filename": "a.txt",
        "evidence": "Orion Systems signed an agreement with Delta Research.",
    }
    relationship.update(overrides)
    return relationship



def two_entities() -> list[dict]:
    """Two valid entities with IDs 1 and 2."""
    return [
        make_entity(1, "Orion Systems"),
        make_entity(2, "Delta Corporation"),
    ]



class TestGraphConstruction(unittest.TestCase):
    """Tests for nodes and node attributes."""

    def test_empty_input_produces_empty_multidigraph(self) -> None:
        graph = build_knowledge_graph([])

        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(graph.number_of_nodes(), 0)
        self.assertEqual(graph.number_of_edges(), 0)

    def test_empty_relationships_list_is_accepted(self) -> None:
        graph = build_knowledge_graph(two_entities(), [])

        self.assertEqual(graph.number_of_nodes(), 2)
        self.assertEqual(graph.number_of_edges(), 0)

    def test_each_distinct_entity_id_creates_one_node(self) -> None:
        entities = [
            make_entity(1, "Orion"),
            make_entity(2, "Delta"),
            make_entity(1, "Orion"),
            make_entity(3, "Pune", entity_type="GPE"),
            make_entity(2, "Delta"),
        ]
        graph = build_knowledge_graph(entities)

        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(set(graph.nodes), {1, 2, 3})
        self.assertEqual(graph.number_of_nodes(), 3)

    def test_node_has_required_attributes(self) -> None:
        graph = build_knowledge_graph([make_entity(7, "Orion Systems")])
        attributes = graph.nodes[7]

        for key in ("entity_id", "canonical_name", "entity_type", "mentions"):
            self.assertIn(key, attributes)
        self.assertEqual(attributes["entity_id"], 7)
        self.assertEqual(attributes["canonical_name"], "orion systems")
        self.assertEqual(attributes["entity_type"], "ORG")
        self.assertIsInstance(attributes["mentions"], list)

    def test_first_mention_determines_canonical_name_and_type(self) -> None:
        entities = [
            make_entity(1, "Orion Systems", normalized_name="orion systems", entity_type="ORG"),
            make_entity(1, "ORION  SYSTEMS", normalized_name="orion systems variant",
                        entity_type="PRODUCT"),
        ]
        attributes = build_knowledge_graph(entities).nodes[1]

        self.assertEqual(attributes["canonical_name"], "orion systems")
        self.assertEqual(attributes["entity_type"], "ORG")

    def test_repeated_mentions_are_all_retained_in_order(self) -> None:
        entities = [
            make_entity(1, "Orion", start_char=0, end_char=5, document_id="doc-1",
                        filename="a.txt", context="Orion first."),
            make_entity(1, "orion", start_char=40, end_char=45, document_id="doc-1",
                        filename="a.txt", context="Then orion again."),
            make_entity(1, "ORION", start_char=3, end_char=8, document_id="doc-2",
                        filename="b.txt", context="ORION in another file."),
        ]
        mentions = build_knowledge_graph(entities).nodes[1]["mentions"]

        self.assertEqual(len(mentions), 3)
        for source, mention in zip(entities, mentions):
            self.assertEqual(set(mention.keys()), MENTION_EVIDENCE_FIELDS)
            for field in MENTION_EVIDENCE_FIELDS:
                self.assertEqual(mention[field], source[field])

    def test_mentions_are_kept_per_node(self) -> None:
        entities = [make_entity(1, "Orion"), make_entity(2, "Delta"), make_entity(2, "Delta")]
        graph = build_knowledge_graph(entities)

        self.assertEqual(len(graph.nodes[1]["mentions"]), 1)
        self.assertEqual(len(graph.nodes[2]["mentions"]), 2)


class TestRelationships(unittest.TestCase):
    """Tests for edges."""

    def test_valid_relationship_creates_edge_with_attributes(self) -> None:
        relationship = make_relationship(1, 2)
        graph = build_knowledge_graph(two_entities(), [relationship])

        self.assertEqual(graph.number_of_edges(), 1)
        edge_data = list(graph.get_edge_data(1, 2).values())[0]
        for field in EDGE_FIELDS:
            self.assertEqual(edge_data[field], relationship[field])

    def test_edge_direction_is_preserved(self) -> None:
        graph = build_knowledge_graph(two_entities(), [make_relationship(1, 2)])

        self.assertTrue(graph.has_edge(1, 2))
        self.assertFalse(graph.has_edge(2, 1))

    def test_opposite_directions_create_separate_edges(self) -> None:
        relationships = [
            make_relationship(1, 2, relationship_type="OWNS"),
            make_relationship(2, 1, relationship_type="OWNED_BY"),
        ]
        graph = build_knowledge_graph(two_entities(), relationships)

        self.assertEqual(graph.number_of_edges(1, 2), 1)
        self.assertEqual(graph.number_of_edges(2, 1), 1)

    def test_parallel_edges_are_allowed(self) -> None:
        relationships = [
            make_relationship(1, 2, relationship_type="SIGNED_WITH", evidence="First evidence."),
            make_relationship(1, 2, relationship_type="PARTNER_OF", evidence="Second evidence."),
            make_relationship(1, 2, relationship_type="SIGNED_WITH", evidence="Third evidence."),
        ]
        graph = build_knowledge_graph(two_entities(), relationships)

        self.assertEqual(graph.number_of_edges(1, 2), 3)
        evidences = {data["evidence"] for data in graph.get_edge_data(1, 2).values()}
        self.assertEqual(evidences, {"First evidence.", "Second evidence.", "Third evidence."})

    def test_self_referential_relationship_is_accepted(self) -> None:
        graph = build_knowledge_graph(
            two_entities(), [make_relationship(1, 1, relationship_type="RENAMED_TO")]
        )

        self.assertTrue(graph.has_edge(1, 1))
        self.assertEqual(graph.number_of_edges(1, 1), 1)

    def test_unknown_source_or_target_raises_value_error(self) -> None:
        cases = {
            "unknown source": make_relationship(99, 2),
            "unknown target": make_relationship(1, 99),
            "both unknown": make_relationship(98, 99),
        }
        for label, relationship in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ValueError):
                    build_knowledge_graph(two_entities(), [relationship])

    def test_relationship_without_any_entities_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            build_knowledge_graph([], [make_relationship(1, 2)])

    def test_no_relationships_are_inferred_from_co_occurrence(self) -> None:
        graph = build_knowledge_graph(two_entities())  # same document, no relationships

        self.assertEqual(graph.number_of_edges(), 0)


class TestValidation(unittest.TestCase):
    """Tests that invalid input raises ValueError."""

    def test_invalid_top_level_entities_raise_value_error(self) -> None:
        for invalid in (None, "text", 42, {"entity_id": 1}, (make_entity(),), {1, 2}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build_knowledge_graph(invalid)  # type: ignore[arg-type]

    def test_invalid_top_level_relationships_raise_value_error(self) -> None:
        for invalid in ("text", 42, {"source_entity_id": 1}, (make_relationship(),), {1, 2}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build_knowledge_graph(two_entities(), invalid)  # type: ignore[arg-type]

    def test_non_dictionary_entity_records_raise_value_error(self) -> None:
        for bad in (None, "entity", 42, ["x"], ("x",)):
            with self.subTest(record=bad):
                with self.assertRaises(ValueError):
                    build_knowledge_graph([make_entity(), bad])  # type: ignore[list-item]

    def test_non_dictionary_relationship_records_raise_value_error(self) -> None:
        for bad in (None, "rel", 42, ["x"], ("x",)):
            with self.subTest(record=bad):
                with self.assertRaises(ValueError):
                    build_knowledge_graph(two_entities(), [bad])  # type: ignore[list-item]

    def test_missing_entity_fields_raise_value_error(self) -> None:
        for field in ENTITY_FIELDS:
            with self.subTest(missing=field):
                entity = make_entity()
                del entity[field]

                with self.assertRaises(ValueError) as context:
                    build_knowledge_graph([entity])

                self.assertIn(field, str(context.exception))

    def test_missing_relationship_fields_raise_value_error(self) -> None:
        for field in RELATIONSHIP_FIELDS:
            with self.subTest(missing=field):
                relationship = make_relationship()
                del relationship[field]

                with self.assertRaises(ValueError) as context:
                    build_knowledge_graph(two_entities(), [relationship])

                self.assertIn(field, str(context.exception))

    def test_incorrect_entity_field_types_raise_value_error(self) -> None:
        for field, expected_type in ENTITY_FIELDS.items():
            for bad_value in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad_value):
                    with self.assertRaises(ValueError) as context:
                        build_knowledge_graph([make_entity(**{field: bad_value})])

                    self.assertIn(field, str(context.exception))

    def test_incorrect_relationship_field_types_raise_value_error(self) -> None:
        for field, expected_type in RELATIONSHIP_FIELDS.items():
            for bad_value in WRONG_VALUES[expected_type]:
                with self.subTest(field=field, value=bad_value):
                    with self.assertRaises(ValueError) as context:
                        build_knowledge_graph(
                            two_entities(), [make_relationship(**{field: bad_value})]
                        )

                    self.assertIn(field, str(context.exception))

    def test_boolean_entity_ids_are_rejected(self) -> None:
        for bad_id in (True, False):
            with self.subTest(entity_id=bad_id):
                with self.assertRaises(ValueError):
                    build_knowledge_graph([make_entity(entity_id=bad_id)])

    def test_boolean_relationship_endpoints_are_rejected(self) -> None:
        for field in ("source_entity_id", "target_entity_id"):
            for bad_id in (True, False):
                with self.subTest(field=field, value=bad_id):
                    with self.assertRaises(ValueError):
                        build_knowledge_graph(
                            two_entities(), [make_relationship(**{field: bad_id})]
                        )

    def test_boolean_character_offsets_are_rejected(self) -> None:
        for field in ("start_char", "end_char"):
            for bad_value in (True, False):
                with self.subTest(field=field, value=bad_value):
                    with self.assertRaises(ValueError):
                        build_knowledge_graph([make_entity(**{field: bad_value})])

    def test_empty_entity_strings_raise_value_error(self) -> None:
        for field in ("entity_text", "entity_type", "normalized_name"):
            for empty_value in ("", "   ", "\n\t "):
                with self.subTest(field=field, value=empty_value):
                    with self.assertRaises(ValueError) as context:
                        build_knowledge_graph([make_entity(**{field: empty_value})])

                    self.assertIn(field, str(context.exception))

    def test_empty_relationship_strings_raise_value_error(self) -> None:
        for field in ("relationship_type", "evidence"):
            for empty_value in ("", "   ", "\n\t "):
                with self.subTest(field=field, value=empty_value):
                    with self.assertRaises(ValueError) as context:
                        build_knowledge_graph(
                            two_entities(), [make_relationship(**{field: empty_value})]
                        )

                    self.assertIn(field, str(context.exception))

    def test_zero_and_negative_entity_ids_raise_value_error(self) -> None:
        for bad_id in (0, -1, -100):
            with self.subTest(entity_id=bad_id):
                with self.assertRaises(ValueError):
                    build_knowledge_graph([make_entity(entity_id=bad_id)])

    def test_zero_and_negative_relationship_endpoints_raise_value_error(self) -> None:
        for field in ("source_entity_id", "target_entity_id"):
            for bad_id in (0, -1, -100):
                with self.subTest(field=field, value=bad_id):
                    with self.assertRaises(ValueError):
                        build_knowledge_graph(
                            two_entities(), [make_relationship(**{field: bad_id})]
                        )

    def test_one_invalid_entity_rejects_the_whole_input(self) -> None:
        entities = [make_entity(1, "Orion"), make_entity(2, entity_text="")]

        with self.assertRaises(ValueError):
            build_knowledge_graph(entities)

    def test_one_invalid_relationship_rejects_the_whole_input(self) -> None:
        relationships = [make_relationship(1, 2), make_relationship(1, 2, evidence="")]

        with self.assertRaises(ValueError):
            build_knowledge_graph(two_entities(), relationships)


class TestNoMutation(unittest.TestCase):
    """Tests that inputs are left untouched."""

    def test_input_records_are_not_mutated(self) -> None:
        entities = [
            make_entity(1, "Orion Systems"),
            make_entity(1, "orion systems", start_char=30, end_char=43),
            make_entity(2, "Delta Research"),
        ]
        relationships = [make_relationship(1, 2), make_relationship(2, 1)]
        entities_snapshot = copy.deepcopy(entities)
        relationships_snapshot = copy.deepcopy(relationships)

        graph = build_knowledge_graph(entities, relationships)

        self.assertEqual(entities, entities_snapshot)
        self.assertEqual(relationships, relationships_snapshot)
        for entity in entities:
            self.assertNotIn("mentions", entity)

        # Changing the graph must not change the caller's records.
        graph.nodes[1]["mentions"][0]["entity_text"] = "CHANGED"
        self.assertEqual(entities, entities_snapshot)


if __name__ == "__main__":
    unittest.main()