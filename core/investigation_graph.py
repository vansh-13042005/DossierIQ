
"""Integration utilities for retrieving investigations and rebuilding graphs."""

from pathlib import Path

import networkx as nx

from core.knowledge_graph import build_knowledge_graph_from_investigation
from storage.investigation_retrieval import get_investigation


def load_investigation_graph(
    investigation_id: str,
    db_path: str | Path,
) -> tuple[dict, nx.MultiDiGraph]:
    """Load a saved investigation and reconstruct its knowledge graph.

    Args:
        investigation_id: ID of the saved investigation.
        db_path: Path to the existing SQLite database.

    Returns:
        A tuple containing the retrieved investigation dictionary and its
        reconstructed NetworkX MultiDiGraph.

    Raises:
        ValueError: If the supplied arguments or investigation data are invalid.
        FileNotFoundError: If the database file does not exist.
        InvestigationNotFoundError: If the investigation ID is not found.
        sqlite3.Error: If SQLite reports a database error.
    """
    investigation = get_investigation(investigation_id, db_path)
    graph = build_knowledge_graph_from_investigation(investigation)

    return investigation, graph
