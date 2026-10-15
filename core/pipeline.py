"""End-to-end processing pipeline for DossierIQ."""

from core.document_loader import load_document
from core.entity_extractor import extract_entities
from core.entity_resolver import resolve_entities


def process_documents(file_paths: list[str]) -> dict:
    """Load documents, extract entity mentions and resolve them together.

    Every file is loaded with ``load_document()`` and processed with
    ``extract_entities()``. All mentions from all documents are then combined
    into a single list and passed to ``resolve_entities()`` exactly once, so
    entity IDs are consistent across documents.

    Args:
        file_paths: A non-empty list of paths to ``.txt`` or ``.pdf`` files.

    Returns:
        A dictionary with exactly three keys:

        * ``documents``: loaded document dictionaries, in input order.
        * ``entities``: resolved entity mention dictionaries, in document
          order and then mention order.
        * ``summary``: a dictionary with ``document_count``,
          ``entity_mention_count`` and ``unique_entity_count``.

    Raises:
        ValueError: If ``file_paths`` is not a list or is empty. Errors raised
            by the loader, extractor or resolver (for example
            ``FileNotFoundError`` or ``ValueError``) are not caught.
    """
    if not isinstance(file_paths, list):
        raise ValueError(
            f"file_paths must be a list, got {type(file_paths).__name__}."
        )

    if not file_paths:
        raise ValueError("file_paths must not be empty.")

    documents: list[dict] = []
    all_mentions: list[dict] = []

    for file_path in file_paths:
        document = load_document(file_path)
        documents.append(document)
        all_mentions.extend(extract_entities(document))

    entities = resolve_entities(all_mentions)

    return {
        "documents": documents,
        "entities": entities,
        "summary": {
            "document_count": len(documents),
            "entity_mention_count": len(entities),
            "unique_entity_count": len({record["entity_id"] for record in entities}),
        },
    }