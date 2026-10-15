"""Investigation workflow for DossierIQ.

Connects the document processing pipeline, rule-based relationship
extraction and knowledge graph construction, and can optionally save the
investigation to SQLite. Relationships come only from
``extract_relationships()``, which recognises a small set of explicit
phrasings, so a sparse or edge-free graph means "no rule matched", not
"no relationship exists".

Persistence is opt-in: nothing touches the database unless the caller asks.
"""

from pathlib import Path

import networkx as nx

from core.knowledge_graph import build_knowledge_graph
from core.pipeline import process_documents
from core.relationship_extractor import extract_relationships
from storage.investigation_store import save_investigation

# Used only when persistence is requested without an explicit path.
# It is relative to the current working directory.
DEFAULT_DB_PATH = Path("data") / "dossieriq.db"


def run_investigation(
    file_paths: list[str],
    *,
    persist: bool = False,
    db_path: str | Path | None = None,
) -> dict:
    """Process documents, extract relationships and build a knowledge graph.

    ``process_documents()`` and ``extract_relationships()`` are each called
    exactly once by this function. The resolved entity mentions and the
    extracted relationship records are then passed to
    ``build_knowledge_graph()``, which creates one node per distinct entity
    ID and one directed edge per relationship. Entity IDs are only unique
    within a single run.

    If ``persist`` is true, the finished result is saved with
    ``save_investigation()`` and the new investigation ID is added to the
    result under ``investigation_id``. If ``persist`` is false (the
    default), the storage layer is not called, no database file is created,
    and ``db_path`` is ignored entirely (it is not even validated).

    Args:
        file_paths: A non-empty list of paths to ``.txt`` or ``.pdf`` files.
        persist: Whether to save the investigation to SQLite. Defaults to
            False.
        db_path: Path to the SQLite database file, used only when ``persist``
            is true. Defaults to ``DEFAULT_DB_PATH`` (``data/dossieriq.db``,
            relative to the working directory).

    Returns:
        A dictionary with the keys:

        * ``documents``: the processed document dictionaries.
        * ``entities``: the resolved entity mention dictionaries.
        * ``summary``: the pipeline summary, unchanged.
        * ``graph``: the ``networkx.MultiDiGraph`` of entities and
          relationships.
        * ``graph_summary``: a dictionary with ``node_count`` and
          ``edge_count``.
        * ``investigation_id``: the saved investigation's UUID string.
          Present only when ``persist`` is true.

    Raises:
        ValueError: If ``file_paths`` is not a non-empty list, ``persist``
            is not a bool, or (only when ``persist`` is true) ``db_path`` is
            not a non-empty string or ``Path``. Errors from the pipeline,
            relationship extractor, graph builder or storage layer are not
            caught.
    """
    if not isinstance(file_paths, list):
        raise ValueError(
            f"file_paths must be a list, got {type(file_paths).__name__}."
        )

    if not file_paths:
        raise ValueError("file_paths must not be empty.")

    if not isinstance(persist, bool):
        raise ValueError(f"persist must be a bool, got {type(persist).__name__}.")

    if persist and db_path is not None:
        if not isinstance(db_path, (str, Path)):
            raise ValueError(
                f"db_path must be a string or Path, got {type(db_path).__name__}."
            )
        if not str(db_path).strip():
            raise ValueError("db_path must not be empty.")

    result = process_documents(file_paths)

    relationships = extract_relationships(result["entities"])

    graph: nx.MultiDiGraph = build_knowledge_graph(
    result["entities"], relationships
)

    investigation = {
        "documents": result["documents"],
        "entities": result["entities"],
        "summary": result["summary"],
        "graph": graph,
        "graph_summary": {
            "node_count": graph.number_of_nodes(),
            "edge_count": graph.number_of_edges(),
        },
    }

    if persist:
        target = DEFAULT_DB_PATH if db_path is None else db_path
        investigation["investigation_id"] = save_investigation(investigation, target)

    return investigation