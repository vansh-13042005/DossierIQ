"""Conservative rule-based relationship extraction for DossierIQ.

This is an initial baseline, not a general relation extractor. It only
recognises a few explicit phrasings (listed in ``_PATTERNS``) and only when
the text between two entity mentions in one sentence is exactly the pattern
phrase (ignoring case and repeated whitespace). Anything else is ignored.
A missing relationship therefore means "no rule matched", not "no
relationship exists".

Only the Python standard library is used.
"""

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

# Each pattern maps the exact connecting phrase (normalized: whitespace
# collapsed, lower-case) found between two mentions to:
#   (relationship_type, source_is_left, allowed_source_types, allowed_target_types)
# ``source_is_left`` says whether the entity on the left of the phrase is the
# relationship's source. Entity types are spaCy labels, compared exactly.
_PATTERNS: dict[str, tuple[str, bool, frozenset[str], frozenset[str]]] = {
    # "<A> signed a contract with <B>"      -> A --SIGNED_CONTRACT_WITH--> B
    "signed a contract with": (
        "SIGNED_CONTRACT_WITH", True,
        frozenset({"ORG", "PERSON"}), frozenset({"ORG", "PERSON"}),
    ),
    # "<A> signed an agreement with <B>"    -> A --SIGNED_AGREEMENT_WITH--> B
    "signed an agreement with": (
        "SIGNED_AGREEMENT_WITH", True,
        frozenset({"ORG", "PERSON"}), frozenset({"ORG", "PERSON"}),
    ),
        # "<A> entered into a research collaboration with <B>"
    # -> A --RESEARCH_COLLABORATION_WITH--> B
    "entered into a research collaboration with": (
        "RESEARCH_COLLABORATION_WITH",
        True,
        frozenset({"ORG"}),
        frozenset({"ORG"}),
    ),
    # "<A> acquired <B>"                    -> A --ACQUIRED--> B
    "acquired": (
        "ACQUIRED", True, frozenset({"ORG"}), frozenset({"ORG"}),
    ),
    # "<A> acquired a minority stake in <B>" -> A --ACQUIRED--> B
    "acquired a minority stake in": (
        "ACQUIRED", True, frozenset({"ORG"}), frozenset({"ORG"}),
    ),
    # "<A> was acquired by <B>"             -> B --ACQUIRED--> A
    "was acquired by": (
        "ACQUIRED", False, frozenset({"ORG"}), frozenset({"ORG"}),
    ),
    # "<A> works for <B>"                   -> A --WORKS_FOR--> B
    "works for": (
        "WORKS_FOR", True, frozenset({"PERSON"}), frozenset({"ORG"}),
    ),
    # "<A> is employed by <B>"              -> A --WORKS_FOR--> B
    "is employed by": (
        "WORKS_FOR", True, frozenset({"PERSON"}), frozenset({"ORG"}),
    ),
}


def _validate_entities(entities: list[dict]) -> None:
    """Check the input is a list of well-formed resolved entity mentions.

    Only checks that can be made from the mention fields themselves are
    performed. Offsets are checked for basic sanity (non-negative, end after
    start); they cannot be checked against the document text, which is not
    available here.
    """
    if not isinstance(entities, list):
        raise ValueError(f"Entities must be a list, got {type(entities).__name__}.")

    for index, mention in enumerate(entities):
        label = f"Entity at index {index}"

        if not isinstance(mention, dict):
            raise ValueError(
                f"{label} must be a dictionary, got {type(mention).__name__}."
            )

        for field, expected_type in _ENTITY_FIELDS.items():
            if field not in mention:
                raise ValueError(f"{label} is missing required field '{field}'.")

            value = mention[field]
            # bool is a subclass of int, so reject it explicitly.
            if not isinstance(value, expected_type) or isinstance(value, bool):
                raise ValueError(
                    f"Field '{field}' of {label} must be of type "
                    f"{expected_type.__name__}, got {type(value).__name__}."
                )

        if mention["entity_id"] < 1:
            raise ValueError(f"Field 'entity_id' of {label} must be a positive integer.")

        for field in ("entity_text", "entity_type", "document_id", "filename", "context"):
            if not mention[field].strip():
                raise ValueError(f"Field '{field}' of {label} must not be empty.")

        if mention["start_char"] < 0:
            raise ValueError(f"Field 'start_char' of {label} must not be negative.")

        if mention["end_char"] <= mention["start_char"]:
            raise ValueError(
                f"Field 'end_char' of {label} must be greater than 'start_char'."
            )


def _group_by_sentence(entities: list[dict]) -> dict[tuple[str, str], list[dict]]:
    """Group mentions by (document_id, context), keeping first-appearance order.

    Raises:
        ValueError: If mentions in the same group have different filenames.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for mention in entities:
        key = (mention["document_id"], mention["context"])
        groups.setdefault(key, []).append(mention)

    for (document_id, _), mentions in groups.items():
        filenames = {mention["filename"] for mention in mentions}
        if len(filenames) > 1:
            raise ValueError(
                f"Inconsistent filenames for document_id '{document_id}' "
                f"within the same sentence: {sorted(filenames)}."
            )

    return groups


def _normalize_phrase(text: str) -> str:
    """Trim, collapse repeated whitespace and lower-case a phrase."""
    return " ".join(text.split()).casefold()


def _span_is_valid(mention: dict) -> bool:
    """Return True if the mention's offsets are sane and match its text length."""
    start, end, text = mention["start_char"], mention["end_char"], mention["entity_text"]
    return start >= 0 and end > start and len(text) > 0 and end - start == len(text)


def _text_between(context: str, left: dict, right: dict) -> str | None:
    """Return the sentence text between two mentions, or None if unclear.

    Mentions carry offsets into the whole document, but ``context`` is only
    the sentence, so the sentence's start offset in the document is not
    known. It is recovered from the position of the left mention's text in
    the sentence.

    Before any alignment is attempted, both mention texts must each occur
    exactly once in ``context``; if either occurs zero times or more than
    once, None is returned. The alignment is then accepted only if:

    * the mention spans are internally consistent (offsets match text length),
    * the implied sentence offset is not negative,
    * the right mention lies inside the sentence, entirely after the left
      mention (no overlap, no negative indices), and
    * the sentence text at the right mention's position equals its text.

    If the alignment is not consistent, or is ambiguous, None is returned.
    The mention spans cannot be checked against the full document.
    """
    if not _span_is_valid(left) or not _span_is_valid(right):
        return None

    left_text = left["entity_text"]
    right_text = right["entity_text"]

    if context.count(left_text) != 1 or context.count(right_text) != 1:
        return None

    candidates: list[str] = []  # text between mentions, one per consistent alignment
    position = context.find(left_text)
    while position != -1:
        sentence_offset = left["start_char"] - position
        if sentence_offset >= 0:
            left_end = position + len(left_text)
            right_start = right["start_char"] - sentence_offset
            right_end = right["end_char"] - sentence_offset

            if (
                right_start >= left_end
                and right_end <= len(context)
                and context[right_start:right_end] == right_text
            ):
                candidates.append(context[left_end:right_start])

        position = context.find(left_text, position + 1)

    if len(candidates) != 1:
        return None
    return candidates[0]


def _match_pair(left: dict, right: dict) -> dict | None:
    """Return a relationship record if the pair matches a known pattern."""
    between = _text_between(left["context"], left, right)
    if between is None:
        return None

    pattern = _PATTERNS.get(_normalize_phrase(between))
    if pattern is None:
        return None

    relationship_type, source_is_left, source_types, target_types = pattern
    source, target = (left, right) if source_is_left else (right, left)

    if source["entity_type"] not in source_types:
        return None
    if target["entity_type"] not in target_types:
        return None

    return {
        "source_entity_id": source["entity_id"],
        "target_entity_id": target["entity_id"],
        "relationship_type": relationship_type,
        "document_id": left["document_id"],
        "filename": left["filename"],
        "evidence": left["context"],
    }


def extract_relationships(entities: list[dict]) -> list[dict]:
    """Extract explicitly stated relationships between entity mentions.

    Mentions are only paired when they share a ``document_id`` and the same
    sentence (``context``), have different ``entity_id`` values, and the text
    between them is exactly one of the documented phrases, such as
    ``"signed an agreement with"``, ``"acquired"``, ``"was acquired by"``,
    ``"works for"`` or ``"is employed by"``. Entity types must also fit the
    pattern (for example, ``works for`` needs a PERSON then an ORG). Pairs
    that do not match, whose mention texts do not each occur exactly once in
    the sentence, or whose position cannot be aligned unambiguously within
    the sentence, are skipped; co-occurrence alone never creates a
    relationship.

    Duplicate records (same source, target, relationship type and document)
    are removed, keeping the first one found.

    Args:
        entities: Resolved entity mention dictionaries, each with
            ``entity_id``, ``entity_text``, ``entity_type``,
            ``normalized_name``, ``document_id``, ``filename``,
            ``start_char``, ``end_char`` and ``context``.

    Returns:
        A list of relationship dictionaries with the keys
        ``source_entity_id``, ``target_entity_id``, ``relationship_type``,
        ``document_id``, ``filename`` and ``evidence`` (the sentence), in a
        form accepted by ``build_knowledge_graph()``. The input is not
        modified.

    Raises:
        ValueError: If ``entities`` is not a list, a record is missing a
            field, has a field of the wrong type, or has an empty or invalid
            value, or if mentions in the same document and sentence have
            different filenames.
    """
    _validate_entities(entities)
    sentences = _group_by_sentence(entities)

    relationships: list[dict] = []
    seen: set[tuple[int, int, str, str]] = set()

    for mentions in sentences.values():
        ordered = sorted(mentions, key=lambda m: m["start_char"])

        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]:
                if left["entity_id"] == right["entity_id"]:
                    continue

                relationship = _match_pair(left, right)
                if relationship is None:
                    continue

                dedupe_key = (
                    relationship["source_entity_id"],
                    relationship["target_entity_id"],
                    relationship["relationship_type"],
                    relationship["document_id"],
                )
                if dedupe_key in seen:
                    continue

                seen.add(dedupe_key)
                relationships.append(relationship)

    return relationships