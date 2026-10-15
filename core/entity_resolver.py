
"""Rule-based entity resolution for DossierIQ (standard library only)."""

_REQUIRED_FIELDS: dict[str, type] = {
    "entity_text": str,
    "entity_type": str,
    "document_id": str,
    "filename": str,
    "start_char": int,
    "end_char": int,
    "context": str,
}


def _normalize_name(name: str) -> str:
    """Trim, collapse repeated whitespace and case-fold a name."""
    return " ".join(name.split()).casefold()


def _validate_entities(entities: list[dict]) -> None:
    """Validate entity mention dictionaries and their required fields."""
    if not isinstance(entities, list):
        raise ValueError(
            f"Entities must be a list, got {type(entities).__name__}."
        )

    for index, mention in enumerate(entities):
        if not isinstance(mention, dict):
            raise ValueError(
                f"Entity at index {index} must be a dictionary, "
                f"got {type(mention).__name__}."
            )

        for field, expected_type in _REQUIRED_FIELDS.items():
            if field not in mention:
                raise ValueError(
                    f"Entity at index {index} is missing required field "
                    f"'{field}'."
                )

            value = mention[field]

            # Reject bool for offsets because bool is a subclass of int.
            if (
                not isinstance(value, expected_type)
                or (
                    expected_type is int
                    and isinstance(value, bool)
                )
            ):
                raise ValueError(
                    f"Field '{field}' of entity at index {index} must be "
                    f"of type {expected_type.__name__}, "
                    f"got {type(value).__name__}."
                )

        if not _normalize_name(mention["entity_text"]):
            raise ValueError(
                f"Field 'entity_text' of entity at index {index} "
                "must not be empty."
            )

        if not mention["entity_type"].strip():
            raise ValueError(
                f"Field 'entity_type' of entity at index {index} "
                "must not be empty."
            )

        if mention["start_char"] < 0:
            raise ValueError(
                f"Field 'start_char' of entity at index {index} "
                f"must be >= 0, got {mention['start_char']}."
            )

        if mention["end_char"] <= mention["start_char"]:
            raise ValueError(
                f"Field 'end_char' of entity at index {index} must be "
                f"greater than 'start_char' ({mention['start_char']}), "
                f"got {mention['end_char']}."
            )


def resolve_entities(entities: list[dict]) -> list[dict]:
    """Resolve exact normalized name/type matches into entity IDs.

    Names are normalized by trimming whitespace, collapsing repeated
    whitespace, and applying case-folding. Entity types are compared
    case-sensitively.

    Each original mention remains a separate output record. Mentions
    share an entity_id only when both normalized names and entity types
    match exactly.

    IDs start at 1 and follow the order of first appearance.

    Raises:
        ValueError: If the input or any mention has invalid fields.
    """
    _validate_entities(entities)

    entity_ids: dict[tuple[str, str], int] = {}
    resolved: list[dict] = []

    for mention in entities:
        normalized_name = _normalize_name(mention["entity_text"])
        key = (normalized_name, mention["entity_type"])

        if key not in entity_ids:
            entity_ids[key] = len(entity_ids) + 1

        record = dict(mention)
        record["normalized_name"] = normalized_name
        record["entity_id"] = entity_ids[key]
        resolved.append(record)

    return resolved
