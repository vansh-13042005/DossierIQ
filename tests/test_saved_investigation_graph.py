
"""Tests for reconstructing a knowledge graph from a saved investigation."""

import copy
import unittest

import networkx as nx

from core.knowledge_graph import build_knowledge_graph_from_investigation


def make_mention(
    entity_id: int,
    entity_text: str,
    normalized_name: str,
    document_id: str = "doc-1",
    filename: str = "sample.txt",
    start_char: int = 0,
    end_char: int = 10,
    context: str = "Sample supporting context.",
    entity_type: str = "ORG",
) -> dict:
    return {
        "entity_id": entity_id,
        "entity_text": entity_text,
        "entity_type": entity_type,
        "normalized_name": normalized_name,
        "document_id": document_id,
        "filename": filename,
        "start_char": start_char,
        "end_char": end_char,
        "context": context,
    }


def make_relationship(
    source_entity_id: int = 1,
    target_entity_id: int = 2,
    relationship_type: str = "SIGNED_WITH",
    document_id: str = "doc-1",
    filename: str = "sample.txt",
    evidence: str = "Orion Systems signed an agreement with Delta Research.",
) -> dict:
    return {
        "source_entity_id": source_entity_id,
        "target_entity_id": target_entity_id,
        "relationship_type": relationship_type,
        "document_id": document_id,
        "filename": filename,
        "evidence": evidence,
    }


def make_investigation(
    entity_mentions: list[dict] | None = None,
    relationships: list[dict] | None = None,
) -> dict:
    return {
        "investigation_id": "investigation-1",
        "created_at": "2026-10-13T10:00:00+00:00",
        "documents": [],
        "entities": [],
        "entity_mentions": (
            entity_mentions
            if entity_mentions is not None
            else [
                make_mention(1, "Orion Systems", "orion systems"),
                make_mention(
                    2,
                    "Delta Research",
                    "delta research",
                    start_char=50,
                    end_char=64,
                ),
            ]
        ),
        "relationships": (
            relationships
            if relationships is not None
            else [make_relationship()]
        ),
    }


class TestSavedInvestigationGraph(unittest.TestCase):

    def test_reconstructs_nodes_and_relationships(self):
        investigation = make_investigation()

        graph = build_knowledge_graph_from_investigation(investigation)

        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(set(graph.nodes), {1, 2})
        self.assertTrue(graph.has_edge(1, 2))
        self.assertEqual(graph.number_of_edges(), 1)

    def test_preserves_relationship_direction_and_evidence(self):
        investigation = make_investigation()

        graph = build_knowledge_graph_from_investigation(investigation)

        self.assertTrue(graph.has_edge(1, 2))
        self.assertFalse(graph.has_edge(2, 1))

        edge = graph.get_edge_data(1, 2)[0]
        self.assertEqual(edge["relationship_type"], "SIGNED_WITH")
        self.assertEqual(
            edge["evidence"],
            "Orion Systems signed an agreement with Delta Research.",
        )
        self.assertEqual(edge["document_id"], "doc-1")
        self.assertEqual(edge["filename"], "sample.txt")

    def test_groups_repeated_mentions_under_one_node(self):
        mentions = [
            make_mention(
                1, "Orion Systems", "orion systems",
                start_char=0, end_char=13, context="Orion Systems signed a contract."
            ),
            make_mention(
                1, "Orion", "orion systems",
                document_id="doc-2",
                filename="second.txt",
                start_char=20,
                end_char=25,
                context="Orion appeared in another document.",
            ),
            make_mention(
                2, "Delta Research", "delta research",
                start_char=40, end_char=54,
            ),
        ]
        investigation = make_investigation(mentions)

        graph = build_knowledge_graph_from_investigation(investigation)

        self.assertEqual(graph.number_of_nodes(), 2)
        self.assertEqual(len(graph.nodes[1]["mentions"]), 2)
        self.assertEqual(
            graph.nodes[1]["canonical_name"],
            "orion systems",
        )
        self.assertEqual(
            graph.nodes[1]["mentions"][1]["filename"],
            "second.txt",
        )

    def test_empty_investigation_produces_empty_graph(self):
        investigation = make_investigation([], [])

        graph = build_knowledge_graph_from_investigation(investigation)

        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(graph.number_of_nodes(), 0)
        self.assertEqual(graph.number_of_edges(), 0)

    def test_preserves_multiple_relationships_between_same_entities(self):
        relationships = [
            make_relationship(
                relationship_type="SIGNED_WITH",
                evidence="The organizations signed an agreement.",
            ),
            make_relationship(
                relationship_type="PARTNER_OF",
                evidence="The organizations are described as partners.",
            ),
        ]
        investigation = make_investigation(relationships=relationships)

        graph = build_knowledge_graph_from_investigation(investigation)

        self.assertEqual(graph.number_of_edges(1, 2), 2)
        evidence = {
            data["evidence"]
            for data in graph.get_edge_data(1, 2).values()
        }
        self.assertEqual(
            evidence,
            {
                "The organizations signed an agreement.",
                "The organizations are described as partners.",
            },
        )

    def test_does_not_modify_input_investigation(self):
        investigation = make_investigation()
        original = copy.deepcopy(investigation)

        build_knowledge_graph_from_investigation(investigation)

        self.assertEqual(investigation, original)

    def test_rejects_non_dictionary_input(self):
        for invalid in (None, [], "investigation", 42):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    build_knowledge_graph_from_investigation(invalid)

    def test_rejects_missing_entity_mentions(self):
        investigation = make_investigation()
        del investigation["entity_mentions"]

        with self.assertRaises(ValueError):
            build_knowledge_graph_from_investigation(investigation)

    def test_rejects_missing_relationships(self):
        investigation = make_investigation()
        del investigation["relationships"]

        with self.assertRaises(ValueError):
            build_knowledge_graph_from_investigation(investigation)


if __name__ == "__main__":
    unittest.main()
