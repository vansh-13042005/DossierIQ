"""Tests for core/investigation.py (standard-library unittest and unittest.mock only).

Run from the project root with:
    python -m unittest tests.test_investigation -v
or:
    python -m unittest discover -v
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import networkx as nx

# Locate the project root (the folder that contains "core/"), whether this
# file lives in the root or inside tests/, and make it importable.
PROJECT_ROOT = Path(__file__).resolve().parent
if not (PROJECT_ROOT / "core").is_dir():
    PROJECT_ROOT = PROJECT_ROOT.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.investigation import run_investigation  # noqa: E402

# Names are patched where investigation.py looks them up.
PROCESS = "core.investigation.process_documents"
EXTRACT = "core.investigation.extract_relationships"
BUILD_GRAPH = "core.investigation.build_knowledge_graph"


def make_pipeline_result() -> dict:
    """Build a fake process_documents() result."""
    documents = [
        {
            "document_id": "id-a",
            "filename": "a.txt",
            "file_type": "txt",
            "text": "Orion Systems signed with Delta Research.",
            "character_count": 41,
        }
    ]
    entities = [
        {
            "entity_text": "Orion Systems",
            "entity_type": "ORG",
            "document_id": "id-a",
            "filename": "a.txt",
            "start_char": 0,
            "end_char": 13,
            "context": "Orion Systems signed with Delta Research.",
            "normalized_name": "orion systems",
            "entity_id": 1,
        },
        {
            "entity_text": "Delta Research",
            "entity_type": "ORG",
            "document_id": "id-a",
            "filename": "a.txt",
            "start_char": 26,
            "end_char": 40,
            "context": "Orion Systems signed with Delta Research.",
            "normalized_name": "delta research",
            "entity_id": 2,
        },
    ]
    summary = {
        "document_count": 1,
        "entity_mention_count": 2,
        "unique_entity_count": 2,
    }
    return {"documents": documents, "entities": entities, "summary": summary}


def make_relationships() -> list[dict]:
    """Build fake relationship records between entities 1 and 2."""
    return [
        {
            "source_entity_id": 1,
            "target_entity_id": 2,
            "relationship_type": "SIGNED_AGREEMENT_WITH",
            "document_id": "id-a",
            "filename": "a.txt",
            "evidence": "Orion Systems signed an agreement with Delta Research.",
        }
    ]


def make_graph(nodes: int = 2, edges: int = 0) -> nx.MultiDiGraph:
    """Build a small real MultiDiGraph with the given node and edge counts."""
    graph = nx.MultiDiGraph()
    graph.add_nodes_from(range(1, nodes + 1))
    for _ in range(edges):
        graph.add_edge(1, 2)
    return graph


def make_acquisition_result() -> dict:
    """Build a pipeline result with a sentence the real extractor recognises."""
    sentence = "Orion Systems acquired Delta Research."
    base = {
        "entity_type": "ORG",
        "document_id": "id-a",
        "filename": "a.txt",
        "context": sentence,
    }
    entities = [
        {**base, "entity_text": "Orion Systems", "normalized_name": "orion systems",
         "start_char": 0, "end_char": 13, "entity_id": 1},
        {**base, "entity_text": "Delta Research", "normalized_name": "delta research",
         "start_char": 23, "end_char": 37, "entity_id": 2},
    ]
    documents = [
        {
            "document_id": "id-a",
            "filename": "a.txt",
            "file_type": "txt",
            "text": sentence,
            "character_count": len(sentence),
        }
    ]
    summary = {
        "document_count": 1,
        "entity_mention_count": 2,
        "unique_entity_count": 2,
    }
    return {"documents": documents, "entities": entities, "summary": summary}


class TestRunInvestigationValidation(unittest.TestCase):
    """Tests for input validation."""

    def test_non_list_input_raises_value_error(self) -> None:
        for invalid in (None, "a.txt", 42, ("a.txt",), {"a.txt"}, {"path": "a.txt"}):
            with self.subTest(invalid=invalid):
                with patch(PROCESS) as process, patch(EXTRACT) as extract, \
                     patch(BUILD_GRAPH) as build:
                    with self.assertRaises(ValueError):
                        run_investigation(invalid)  # type: ignore[arg-type]

                    process.assert_not_called()
                    extract.assert_not_called()
                    build.assert_not_called()

    def test_empty_list_raises_value_error(self) -> None:
        with patch(PROCESS) as process, patch(EXTRACT) as extract, \
             patch(BUILD_GRAPH) as build:
            with self.assertRaises(ValueError):
                run_investigation([])

            process.assert_not_called()
            extract.assert_not_called()
            build.assert_not_called()


class TestRunInvestigationSuccess(unittest.TestCase):
    """Tests for successful runs with all dependencies mocked."""

    def setUp(self) -> None:
        self.pipeline_result = make_pipeline_result()
        self.relationships = make_relationships()
        self.graph = make_graph(nodes=2, edges=1)

    def run_with_mocks(self, file_paths: list[str]):
        """Run run_investigation with all three dependencies patched."""
        with patch(PROCESS, return_value=self.pipeline_result) as process, \
             patch(EXTRACT, return_value=self.relationships) as extract, \
             patch(BUILD_GRAPH, return_value=self.graph) as build:
            result = run_investigation(file_paths)
        return result, process, extract, build

    def test_process_documents_called_exactly_once_with_file_paths(self) -> None:
        paths = ["a.txt", "b.pdf"]

        _, process, _, _ = self.run_with_mocks(paths)

        process.assert_called_once_with(paths)

    def test_extract_relationships_called_once_with_resolved_entities(self) -> None:
        _, _, extract, _ = self.run_with_mocks(["a.txt"])

        extract.assert_called_once()
        args, kwargs = extract.call_args
        self.assertEqual(len(args), 1)
        self.assertIs(args[0], self.pipeline_result["entities"])
        self.assertEqual(kwargs, {})

    def test_graph_builder_called_once_with_entities_and_relationships(self) -> None:
        _, _, _, build = self.run_with_mocks(["a.txt"])

        build.assert_called_once()
        args, kwargs = build.call_args
        self.assertEqual(len(args), 2)
        self.assertIs(args[0], self.pipeline_result["entities"])
        self.assertIs(args[1], self.relationships)
        self.assertEqual(kwargs, {})

    def test_extracted_relationships_are_not_modified_before_graph_build(self) -> None:
        expected = make_relationships()

        _, _, _, build = self.run_with_mocks(["a.txt"])

        self.assertEqual(build.call_args.args[1], expected)

    def test_result_has_exactly_the_expected_keys(self) -> None:
        result, _, _, _ = self.run_with_mocks(["a.txt"])

        self.assertEqual(
            set(result.keys()),
            {"documents", "entities", "summary", "graph", "graph_summary"},
        )
        self.assertEqual(
            set(result["graph_summary"].keys()), {"node_count", "edge_count"}
        )

    def test_documents_entities_and_summary_are_returned_unchanged(self) -> None:
        result, _, _, _ = self.run_with_mocks(["a.txt"])

        self.assertIs(result["documents"], self.pipeline_result["documents"])
        self.assertIs(result["entities"], self.pipeline_result["entities"])
        self.assertIs(result["summary"], self.pipeline_result["summary"])
        self.assertEqual(
            result["summary"],
            {"document_count": 1, "entity_mention_count": 2, "unique_entity_count": 2},
        )

    def test_relationships_are_not_added_to_the_result(self) -> None:
        result, _, _, _ = self.run_with_mocks(["a.txt"])

        self.assertNotIn("relationships", result)

    def test_graph_is_returned_under_graph_key(self) -> None:
        result, _, _, _ = self.run_with_mocks(["a.txt"])

        self.assertIs(result["graph"], self.graph)
        self.assertIsInstance(result["graph"], nx.MultiDiGraph)

    def test_graph_summary_reports_actual_counts(self) -> None:
        cases = [(0, 0), (2, 0), (3, 4), (5, 1)]
        for nodes, edges in cases:
            with self.subTest(nodes=nodes, edges=edges):
                self.graph = make_graph(nodes=nodes, edges=edges)

                result, _, _, _ = self.run_with_mocks(["a.txt"])

                self.assertEqual(
                    result["graph_summary"],
                    {"node_count": nodes, "edge_count": edges},
                )

    def test_graph_summary_uses_graph_methods(self) -> None:
        mock_graph = MagicMock()
        mock_graph.number_of_nodes.return_value = 7
        mock_graph.number_of_edges.return_value = 3

        with patch(PROCESS, return_value=self.pipeline_result), \
             patch(EXTRACT, return_value=self.relationships), \
             patch(BUILD_GRAPH, return_value=mock_graph):
            result = run_investigation(["a.txt"])

        self.assertEqual(
            result["graph_summary"], {"node_count": 7, "edge_count": 3}
        )
        self.assertIs(result["graph"], mock_graph)

    def test_graph_summary_does_not_come_from_relationship_count(self) -> None:
        # Two relationship records, but the (mock) graph reports one edge:
        # graph_summary must reflect the graph, not the extractor output.
        self.relationships = make_relationships() * 2
        self.graph = make_graph(nodes=2, edges=1)

        result, _, _, _ = self.run_with_mocks(["a.txt"])

        self.assertEqual(result["graph_summary"]["edge_count"], 1)

    def test_empty_entities_and_relationships(self) -> None:
        self.pipeline_result = {
            "documents": make_pipeline_result()["documents"],
            "entities": [],
            "summary": {
                "document_count": 1,
                "entity_mention_count": 0,
                "unique_entity_count": 0,
            },
        }
        self.relationships = []
        self.graph = nx.MultiDiGraph()

        result, _, extract, build = self.run_with_mocks(["a.txt"])

        extract.assert_called_once_with([])
        build.assert_called_once_with([], [])
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["graph_summary"], {"node_count": 0, "edge_count": 0})

    def test_calls_happen_in_order_process_extract_build(self) -> None:
        call_order: list[str] = []

        def process_side_effect(paths: list[str]) -> dict:
            call_order.append("process")
            return self.pipeline_result

        def extract_side_effect(entities: list[dict]) -> list[dict]:
            call_order.append("extract")
            return self.relationships

        def build_side_effect(
            entities: list[dict], relationships: list[dict]
        ) -> nx.MultiDiGraph:
            call_order.append("build")
            return self.graph

        with patch(PROCESS, side_effect=process_side_effect), \
             patch(EXTRACT, side_effect=extract_side_effect), \
             patch(BUILD_GRAPH, side_effect=build_side_effect):
            run_investigation(["a.txt"])

        self.assertEqual(call_order, ["process", "extract", "build"])


class TestRunInvestigationIntegration(unittest.TestCase):
    """Tests using the real relationship extractor and graph builder."""

    def test_real_graph_has_one_node_per_distinct_entity(self) -> None:
        pipeline_result = make_pipeline_result()
        # Add a repeated mention of entity 1 (same ID, so still one node).
        repeated = dict(pipeline_result["entities"][0])
        repeated["start_char"] = 50
        repeated["end_char"] = 63
        pipeline_result["entities"].append(repeated)

        with patch(PROCESS, return_value=pipeline_result) as process:
            result = run_investigation(["a.txt"])

        process.assert_called_once_with(["a.txt"])
        self.assertIsInstance(result["graph"], nx.MultiDiGraph)
        self.assertEqual(set(result["graph"].nodes), {1, 2})
        self.assertEqual(len(result["graph"].nodes[1]["mentions"]), 2)
        self.assertEqual(len(result["entities"]), 3)
        # "signed with" is not a recognised phrase, so no edge is created.
        self.assertEqual(
            result["graph_summary"], {"node_count": 2, "edge_count": 0}
        )

    def test_recognised_sentence_creates_a_directed_edge(self) -> None:
        pipeline_result = make_acquisition_result()

        with patch(PROCESS, return_value=pipeline_result) as process:
            result = run_investigation(["a.txt"])

        process.assert_called_once_with(["a.txt"])
        graph = result["graph"]
        self.assertTrue(graph.has_edge(1, 2))
        self.assertFalse(graph.has_edge(2, 1))
        edge_data = list(graph.get_edge_data(1, 2).values())[0]
        self.assertEqual(edge_data["relationship_type"], "ACQUIRED")
        self.assertEqual(edge_data["document_id"], "id-a")
        self.assertEqual(edge_data["filename"], "a.txt")
        self.assertEqual(edge_data["evidence"], "Orion Systems acquired Delta Research.")
        self.assertEqual(
            result["graph_summary"], {"node_count": 2, "edge_count": 1}
        )

    def test_real_components_receive_and_return_pipeline_data_unchanged(self) -> None:
        pipeline_result = make_acquisition_result()

        with patch(PROCESS, return_value=pipeline_result):
            result = run_investigation(["a.txt"])

        self.assertIs(result["documents"], pipeline_result["documents"])
        self.assertIs(result["entities"], pipeline_result["entities"])
        self.assertIs(result["summary"], pipeline_result["summary"])


class TestRunInvestigationErrors(unittest.TestCase):
    """Tests that exceptions from dependencies propagate."""

    def test_pipeline_file_not_found_propagates(self) -> None:
        with patch(PROCESS, side_effect=FileNotFoundError("missing.txt")), \
             patch(EXTRACT) as extract, patch(BUILD_GRAPH) as build:
            with self.assertRaises(FileNotFoundError):
                run_investigation(["missing.txt"])

        extract.assert_not_called()
        build.assert_not_called()

    def test_pipeline_value_error_propagates(self) -> None:
        with patch(PROCESS, side_effect=ValueError("unsupported format")), \
             patch(EXTRACT) as extract, patch(BUILD_GRAPH) as build:
            with self.assertRaises(ValueError) as context:
                run_investigation(["data.csv"])

        self.assertIn("unsupported format", str(context.exception))
        extract.assert_not_called()
        build.assert_not_called()

    def test_relationship_extractor_error_propagates(self) -> None:
        with patch(PROCESS, return_value=make_pipeline_result()) as process, \
             patch(EXTRACT, side_effect=ValueError("bad mention record")) as extract, \
             patch(BUILD_GRAPH) as build:
            with self.assertRaises(ValueError) as context:
                run_investigation(["a.txt"])

        self.assertIn("bad mention record", str(context.exception))
        process.assert_called_once_with(["a.txt"])
        extract.assert_called_once()
        build.assert_not_called()

    def test_graph_builder_error_propagates(self) -> None:
        with patch(PROCESS, return_value=make_pipeline_result()) as process, \
             patch(EXTRACT, return_value=make_relationships()) as extract, \
             patch(BUILD_GRAPH, side_effect=ValueError("bad entity record")):
            with self.assertRaises(ValueError) as context:
                run_investigation(["a.txt"])

        self.assertIn("bad entity record", str(context.exception))
        process.assert_called_once_with(["a.txt"])
        extract.assert_called_once()

    def test_unexpected_exception_types_are_not_swallowed(self) -> None:
        stages = {
            "process": (RuntimeError("boom"), None, None),
            "extract": (None, RuntimeError("boom"), None),
            "build": (None, None, RuntimeError("boom")),
        }
        for stage, (process_error, extract_error, build_error) in stages.items():
            with self.subTest(stage=stage):
                with patch(PROCESS, return_value=make_pipeline_result(),
                           side_effect=process_error), \
                     patch(EXTRACT, return_value=[], side_effect=extract_error), \
                     patch(BUILD_GRAPH, return_value=make_graph(),
                           side_effect=build_error):
                    with self.assertRaises(RuntimeError):
                        run_investigation(["a.txt"])


if __name__ == "__main__":
    unittest.main()