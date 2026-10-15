"""Knowledge graph construction for DossierIQ (NetworkX + standard library)."""

import networkx as nx

# Fields every resolved entity mention must contain, with expected types.
_ENTITY_FIELDS: dict[str, type] = {
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

# Fields every relationship record must contain, with expected types.
_RELATIONSHIP_FIELDS: dict[str, type] = {
    "source_entity_id": int,
    "target_entity_id": int,
    "relationship_type": str,
    "document_id": str,
    "filename": str,
    "evidence": str,
}

# Evidence fields copied from each mention onto its node.
_MENTION_FIELDS = (
    "entity_text",
    "document_id",
    "filename",
    "start_char",
    "end_char",
    "context",
)


def _check_record(record: object, fields: dict[str, type], label: str) -> None:
    """Check that a record is a dict containing all fields with correct types."""
    if not isinstance(record, dict):
        raise ValueError(f"{label} must be a dictionary, got {type(record).__name__}.")

    for field, expected_type in fields.items():
        if field not in record:
            raise ValueError(f"{label} is missing required field '{field}'.")

        value = record[field]
        # bool is a subclass of int, so reject it explicitly.
        if not isinstance(value, expected_type) or isinstance(value, bool):
            raise ValueError(
                f"Field '{field}' of {label} must be of type "
                f"{expected_type.__name__}, got {type(value).__name__}."
            )


def _validate_entities(entities: list[dict]) -> None:
    """Validate the entities list and every mention in it."""
    if not isinstance(entities, list):
        raise ValueError(f"Entities must be a list, got {type(entities).__name__}.")

    for index, mention in enumerate(entities):
        label = f"Entity at index {index}"
        _check_record(mention, _ENTITY_FIELDS, label)

        for field in ("entity_text", "entity_type", "normalized_name"):
            if not mention[field].strip():
                raise ValueError(f"Field '{field}' of {label} must not be empty.")
            
        if mention["entity_id"] < 1:
            raise ValueError(
                f"Field 'entity_id' of {label} must be positive."
            )



def _validate_relationships(relationships: list[dict]) -> None:
    """Validate the relationships list and every record in it."""
    if not isinstance(relationships, list):
        raise ValueError(
            f"Relationships must be a list or None, got {type(relationships).__name__}."
        )

    for index, relationship in enumerate(relationships):
        label = f"Relationship at index {index}"
        _check_record(relationship, _RELATIONSHIP_FIELDS, label)

        for field in ("relationship_type", "evidence"):
            if not relationship[field].strip():
                raise ValueError(f"Field '{field}' of {label} must not be empty.")
            
        for field in ("source_entity_id", "target_entity_id"):
            if relationship[field] < 1:
                raise ValueError(
                    f"Field '{field}' of {label} must be positive."
                )



def build_knowledge_graph(
    entities: list[dict], relationships: list[dict] | None = None
) -> nx.MultiDiGraph:
    """Build a directed multigraph from resolved entity mentions.

    One node is created per distinct ``entity_id``. Each node stores
    ``entity_id``, ``canonical_name`` (the first mention's
    ``normalized_name``), ``entity_type`` (the first mention's type) and a
    ``mentions`` list holding every mention's evidence fields. Edges come
    only from the explicit ``relationships`` argument; nothing is inferred
    from co-occurrence.

    Entity IDs are only unique within a single pipeline run, so graphs built
    from different runs must not be merged by ID.

    Args:
        entities: Resolved mention dictionaries (as returned in the
            ``entities`` list of ``process_documents()``), each with
            ``entity_id``, ``entity_text``, ``entity_type``,
            ``normalized_name``, ``document_id``, ``filename``,
            ``start_char``, ``end_char`` and ``context``.
        relationships: Optional relationship records, each with
            ``source_entity_id``, ``target_entity_id``,
            ``relationship_type``, ``document_id``, ``filename`` and
            ``evidence``.

    Returns:
        A ``networkx.MultiDiGraph``. Edges keep their direction, and several
        edges may connect the same pair of nodes.

    Raises:
        ValueError: If ``entities`` or ``relationships`` is not a list, a
            record is missing a field, has a field of the wrong type, has an
            empty name/type/evidence, or a relationship refers to an
            ``entity_id`` that is not a node in the graph.
    """
    _validate_entities(entities)
    if relationships is not None:
        _validate_relationships(relationships)

    graph = nx.MultiDiGraph()
    
    for mention in entities:
        entity_id = mention["entity_id"]

        if entity_id not in graph:
            graph.add_node(
                entity_id,
                entity_id=entity_id,
                canonical_name=mention["normalized_name"],
                entity_type=mention["entity_type"],
                mentions=[],
            )

        graph.nodes[entity_id]["mentions"].append(
            {field: mention[field] for field in _MENTION_FIELDS}
        )

    for index, relationship in enumerate(relationships or []):
        source = relationship["source_entity_id"]
        target = relationship["target_entity_id"]

        for field, entity_id in (("source_entity_id", source), ("target_entity_id", target)):
            if entity_id not in graph:
                raise ValueError(
                    f"Relationship at index {index} has unknown {field} "
                    f"{entity_id}: no such entity in the graph."
                )

        graph.add_edge(
            source,
            target,
            relationship_type=relationship["relationship_type"],
            document_id=relationship["document_id"],
            filename=relationship["filename"],
            evidence=relationship["evidence"],
        )

    return graph

def build_knowledge_graph_from_investigation(
    investigation: dict,
) -> nx.MultiDiGraph:
    """Reconstruct a knowledge graph from a saved investigation.

    Uses the saved entity mentions and relationships. Does not reload
    documents or rerun entity or relationship extraction.

    Args:
        investigation: Dictionary returned by
            storage.investigation_retrieval.get_investigation().

    Returns:
        A NetworkX directed multigraph.

    Raises:
        ValueError: If the investigation or its required records are invalid.
    """
    if not isinstance(investigation, dict):
        raise ValueError(
            "Investigation must be a dictionary, "
            f"got {type(investigation).__name__}."
        )

    required_fields = ("entity_mentions", "relationships")
    for field in required_fields:
        if field not in investigation:
            raise ValueError(
                f"Investigation is missing required field '{field}'."
            )

    entity_mentions = investigation["entity_mentions"]
    relationships = investigation["relationships"]

    if not isinstance(entity_mentions, list):
        raise ValueError("Investigation field 'entity_mentions' must be a list.")

    if not isinstance(relationships, list):
        raise ValueError("Investigation field 'relationships' must be a list.")

    return build_knowledge_graph(entity_mentions, relationships)
