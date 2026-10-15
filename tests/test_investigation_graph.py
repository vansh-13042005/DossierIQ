
"""Tests for retrieving saved investigations and rebuilding their graphs."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import networkx as nx

from core.investigation_graph import load_investigation_graph
from storage.investigation_retrieval import InvestigationNotFoundError


def make_investigation() -> dict:
    """Return a minimal valid investigation retrieval result."""
    return {
        "investigation_id": "investigation-123",
        "created_at": "2026-10-13T10:00:00+00:00",
        "documents": [],
        "entities": [],
        "entity_mentions": [
            {
                "entity_id": 1,
                "entity_text": "Orion Systems",
                "entity_type": "ORG",
                "normalized_name": "orion systems",
                "document_id": "doc-1",
                "filename": "sample.txt",
                "start_char": 0,
                "end_char": 13,
                "context": "Orion Systems signed an agreement.",
            },
            {
                "entity_id": 2,
                "entity_text": "Delta Research",
                "entity_type": "ORG",
                "normalized_name": "delta research",
                "document_id": "doc-1",
                "filename": "sample.txt",
                "start_char": 40,
                "end_char": 54,
                "context": "Delta Research signed an agreement.",
            },
        ],
        "relationships": [
            {
                "source_entity_id": 1,
                "target_entity_id": 2,
                "relationship_type": "SIGNED_WITH",
                "document_id": "doc-1",
                "filename": "sample.txt",
                "evidence": (
                    "Orion Systems signed an agreement with Delta Research."
                ),
            }
        ],
    }


class TestLoadInvestigationGraph(unittest.TestCase):

    def test_retrieves_investigation_and_builds_graph(self):
        investigation_data = make_investigation()

        with patch(
            "core.investigation_graph.get_investigation",
            return_value=investigation_data,
        ) as mock_get:
            investigation, graph = load_investigation_graph(
                "investigation-123", "unused.db"
            )

        mock_get.assert_called_once_with("investigation-123", "unused.db")

        self.assertIs(investigation, investigation_data)
        self.assertIsInstance(graph, nx.MultiDiGraph)
        self.assertEqual(set(graph.nodes), {1, 2})
        self.assertTrue(graph.has_edge(1, 2))
        self.assertEqual(
            graph.edges[1, 2, 0]["relationship_type"],
            "SIGNED_WITH",
        )

    def test_passes_database_path_to_retrieval(self):
        investigation_data = make_investigation()

        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "dossieriq.db"

            with patch(
                "core.investigation_graph.get_investigation",
                return_value=investigation_data,
            ) as mock_get:
                load_investigation_graph("investigation-123", db_path)

            mock_get.assert_called_once_with("investigation-123", db_path)

    def test_propagates_missing_investigation_error(self):
        with patch(
            "core.investigation_graph.get_investigation",
            side_effect=InvestigationNotFoundError("missing-id"),
        ):
            with self.assertRaises(InvestigationNotFoundError):
                load_investigation_graph("missing-id", "unused.db")

    def test_propagates_database_file_error(self):
        with patch(
            "core.investigation_graph.get_investigation",
            side_effect=FileNotFoundError("database not found"),
        ):
            with self.assertRaises(FileNotFoundError):
                load_investigation_graph("investigation-123", "missing.db")

    def test_rejects_invalid_retrieved_investigation_data(self):
        invalid_data = {
            "investigation_id": "investigation-123",
            "entity_mentions": "not-a-list",
            "relationships": [],
        }

        with patch(
            "core.investigation_graph.get_investigation",
            return_value=invalid_data,
        ):
            with self.assertRaises(ValueError):
                load_investigation_graph("investigation-123", "unused.db")

    def test_empty_investigation_produces_empty_graph(self):
        investigation_data = make_investigation()
        investigation_data["entity_mentions"] = []
        investigation_data["relationships"] = []

        with patch(
            "core.investigation_graph.get_investigation",
            return_value=investigation_data,
        ):
            investigation, graph = load_investigation_graph(
                "investigation-123", "unused.db"
            )

        self.assertEqual(investigation["entity_mentions"], [])
        self.assertEqual(graph.number_of_nodes(), 0)
        self.assertEqual(graph.number_of_edges(), 0)


if __name__ == "__main__":
    unittest.main()
