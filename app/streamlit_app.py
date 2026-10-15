
"""Streamlit dashboard for DossierIQ."""

import tempfile
from pathlib import Path

import streamlit as st

from core.investigation import DEFAULT_DB_PATH, run_investigation
from core.investigation_graph import load_investigation_graph
from storage.investigation_retrieval import list_investigations
from app.graph_visualizer import render_knowledge_graph
from app.graph_visualizer import render_knowledge_graph
st.set_page_config(
    page_title="DossierIQ | Document Intelligence",
    page_icon="🔎",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------- Session state ----------

if "investigation_result" not in st.session_state:
    st.session_state.investigation_result = None

if "investigation_error" not in st.session_state:
    st.session_state.investigation_error = None


# ---------- Header ----------

st.title("🔎 DossierIQ")
st.caption(
    "Multi-document intelligence, entity linking, and "
    "evidence-backed relationship discovery."
)

# ---------- Sidebar ----------

with st.sidebar:
    st.header("Investigation Workspace")
    st.write("Upload documents to start a new investigation.")

    uploaded_files = st.file_uploader(
        "Upload PDF or TXT documents",
        type=["pdf", "txt"],
        accept_multiple_files=True,
        help="Select multiple documents for a single investigation.",
    )

    if uploaded_files:
        st.caption(f"{len(uploaded_files)} document(s) selected")

    start_investigation = st.button(
        "Start Investigation",
        type="primary",
        use_container_width=True,
        disabled=not uploaded_files,
    )
    
    st.divider()
    st.subheader("Saved Investigations")

    try:
        saved_investigations = list_investigations(DEFAULT_DB_PATH)
    except (OSError, ValueError) as exc:
        saved_investigations = []
        st.warning(f"Could not load saved investigations: {exc}")

    if saved_investigations:
        investigation_options = {
            (
                f"{item['created_at']} · {item['investigation_id']}"
            ): item["investigation_id"]
            for item in saved_investigations
        }

        selected_label = st.selectbox(
            "Choose an investigation",
            options=list(investigation_options.keys()),
            index=None,
            placeholder="Select a saved investigation...",
        )

        open_investigation = st.button(
            "Open Investigation",
            use_container_width=True,
            disabled=selected_label is None,
        )
    else:
        st.caption("No saved investigations found.")
        selected_label = None
        open_investigation = False

# ---------- Open saved investigation ----------

if open_investigation and selected_label is not None:
    st.session_state.investigation_result = None
    st.session_state.investigation_error = None

    selected_id = investigation_options[selected_label]

    try:
        with st.spinner("Loading saved investigation..."):
            investigation, graph = load_investigation_graph(
                selected_id,
                DEFAULT_DB_PATH,
            )

            documents = investigation["documents"]
            entities = investigation["entity_mentions"]
            relationships = list(investigation["relationships"])

            st.session_state.investigation_result = {
                "investigation_id": investigation["investigation_id"],
                "documents": documents,
                "entities": entities,
                "graph": graph,
                "summary": {
                    "document_count": len(documents),
                    "entity_mention_count": len(entities),
                },
                "graph_summary": {
                    "node_count": graph.number_of_nodes(),
                    "edge_count": graph.number_of_edges(),
                },
            }

    except Exception as exc:
        st.session_state.investigation_error = (
            f"{type(exc).__name__}: {exc}"
        )


# ---------- Run investigation ----------

if start_investigation and uploaded_files:
    st.session_state.investigation_result = None
    st.session_state.investigation_error = None

    try:
        with st.spinner(
            "Processing documents, extracting entities, "
            "and discovering relationships..."
        ):
            with tempfile.TemporaryDirectory(prefix="dossieriq_") as temp_dir:
                temp_path = Path(temp_dir)
                document_paths = []
                used_names = set()

                for index, uploaded_file in enumerate(uploaded_files, start=1):
                    # Use only the filename, not any uploaded path.
                    filename = Path(uploaded_file.name).name
                    if not filename:
                        filename = f"document_{index}.txt"

                    # Avoid overwriting files with duplicate names.
                    candidate = filename
                    suffix = Path(filename).suffix
                    stem = Path(filename).stem
                    counter = 2

                    while candidate.casefold() in used_names:
                        candidate = f"{stem}_{counter}{suffix}"
                        counter += 1

                    used_names.add(candidate.casefold())
                    destination = temp_path / candidate
                    destination.write_bytes(uploaded_file.getvalue())
                    document_paths.append(str(destination))

                result = run_investigation(
                    document_paths,
                    persist=True,
                    db_path=DEFAULT_DB_PATH,
                )

                # The returned result contains extracted text and graph data,
                # so it remains usable after temporary files are deleted.
                st.session_state.investigation_result = result

    except Exception as exc:
        st.session_state.investigation_error = (
            f"{type(exc).__name__}: {exc}"
        )

# ---------- Error display ----------

if st.session_state.investigation_error:
    st.error(
        "The investigation could not be completed. "
        "Check the error details below."
    )
    st.code(st.session_state.investigation_error)

# ---------- Results ----------

result = st.session_state.investigation_result

if result is None:
    st.info(
        "Upload one or more PDF/TXT documents in the sidebar, "
        "then click **Start Investigation**."
    )

    st.subheader("What DossierIQ does")
    col1, col2, col3 = st.columns(3)

    col1.markdown(
        "**1. Document ingestion**\n\n"
        "Extracts text from supported documents."
    )
    col2.markdown(
        "**2. Entity and relationship extraction**\n\n"
        "Identifies entities and supported connections."
    )
    col3.markdown(
        "**3. Evidence-backed graph**\n\n"
        "Connects entities while preserving source evidence."
    )

else:
    documents = result["documents"]
    entities = result["entities"]
    graph = result["graph"]
    summary = result["summary"]
    graph_summary = result["graph_summary"]

    st.success("Investigation completed and saved.")

    st.subheader("Investigation Overview")

    metric1, metric2, metric3, metric4 = st.columns(4)

    metric1.metric("Documents", summary["document_count"])
    metric2.metric("Entity Mentions", summary["entity_mention_count"])
    metric3.metric("Unique Entities", graph_summary["node_count"])
    metric4.metric("Relationships", graph_summary["edge_count"])

    st.caption(f"Investigation ID: {result['investigation_id']}")
    st.caption(f"Database: {DEFAULT_DB_PATH}")

    st.divider()

    # ---------- Documents ----------

    st.subheader("Processed Documents")

    document_rows = [
        {
            "Filename": document["filename"],
            "Type": document["file_type"],
            "Characters": document["character_count"],
        }
        for document in documents
    ]

    st.dataframe(
        document_rows,
        use_container_width=True,
        hide_index=True,
    )

    # ---------- Entity mentions ----------

    st.subheader("Extracted Entities")

    entity_rows = [
        {
            "Entity": entity["entity_text"],
            "Type": entity["entity_type"],
            "Canonical Name": entity["normalized_name"],
            "Document": entity["filename"],
            "Context": entity["context"],
        }
        for entity in entities
    ]

    if entity_rows:
        st.dataframe(
            entity_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No entities were detected in these documents.")

    # ---------- Relationships ----------

    st.subheader("Discovered Relationships")

    relationship_rows = []

    for source, target, data in graph.edges(data=True):
        source_name = graph.nodes[source]["canonical_name"]
        target_name = graph.nodes[target]["canonical_name"]

        relationship_rows.append(
            {
                "Source Entity": source_name,
                "Relationship": data["relationship_type"],
                "Target Entity": target_name,
                "Document": data["filename"],
                "Evidence": data["evidence"],
            }
        )

    if relationship_rows:
        st.dataframe(
            relationship_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info(
            "No supported relationships were found. "
            "This does not necessarily mean the documents contain none."
        )

    # ---------- Graph preview ----------
    
    
    # ---------- Interactive Knowledge Graph ----------

    st.divider()

    render_knowledge_graph(graph, height="600px")
    
    # ---------- Graph Console ----------

    st.divider()
    st.subheader("Graph Console")
    st.caption(
        "Search entities, inspect their connections, and review "
        "the evidence supporting each relationship."
    )

    # Build a compact entity index from the knowledge graph.
    graph_entity_options = sorted(
        graph.nodes,
        key=lambda node_id: str(
            graph.nodes[node_id].get("canonical_name", node_id)
        ).casefold(),
    )

    graph_relationship_records = []

    if graph.is_multigraph():
        graph_edge_iterator = graph.edges(keys=True, data=True)

        for source, target, key, data in graph_edge_iterator:
            graph_relationship_records.append(
                (source, target, data)
            )
    else:
        for source, target, data in graph.edges(data=True):
            graph_relationship_records.append(
                (source, target, data)
            )

    # Summary metrics.
    console_col1, console_col2, console_col3 = st.columns(3)

    console_col1.metric("Entities", graph.number_of_nodes())
    console_col2.metric(
        "Relationships", len(graph_relationship_records)
    )
    console_col3.metric(
        "Source documents",
        len({
            str(data.get("filename", "Unknown document"))
            for _, _, data in graph_relationship_records
        }),
    )

    if not graph_entity_options:
        st.info("There are no entities to inspect.")
    else:
        def console_entity_label(node_id):
            node_data = graph.nodes[node_id]
            entity_name = node_data.get(
                "canonical_name", str(node_id)
            )
            entity_type = node_data.get("entity_type", "UNKNOWN")
            return f"{entity_name} ({entity_type})"

                # Prefer the entity with the most direct relationships.
        def connection_count(node_id):
            return graph.degree(node_id)

        default_node = max(
            graph_entity_options,
            key=connection_count,
        )

        console_selected_node = st.selectbox(
            "Find an entity",
            options=graph_entity_options,
            index=graph_entity_options.index(default_node),
            format_func=console_entity_label,
            key="graph_console_selected_entity",
        )
        selected_entity_data = graph.nodes[console_selected_node]

        st.markdown(
            f"### {selected_entity_data.get('canonical_name', console_selected_node)}"
        )
        st.caption(
            f"Entity type: "
            f"{selected_entity_data.get('entity_type', 'UNKNOWN')}"
        )

        # Show relationships connected to the selected entity.
        selected_connections = []

        for source, target, data in graph_relationship_records:
            if (
                source == console_selected_node
                or target == console_selected_node
            ):
                selected_connections.append(
                    (source, target, data)
                )

        if not selected_connections:
            st.info(
                "This entity has no detected relationships in "
                "the current investigation."
            )
        else:
            console_rows = []

            for source, target, data in selected_connections:
                console_rows.append({
                    "Direction": (
                        "Outgoing"
                        if source == console_selected_node
                        else "Incoming"
                    ),
                    "Source Entity": graph.nodes[source].get(
                        "canonical_name", str(source)
                    ),
                    "Relationship": data.get(
                        "relationship_type", "RELATED_TO"
                    ),
                    "Target Entity": graph.nodes[target].get(
                        "canonical_name", str(target)
                    ),
                    "Document": data.get(
                        "filename", "Unknown document"
                    ),
                    "Evidence": data.get(
                        "evidence", "No evidence recorded"
                    ),
                })

            st.dataframe(
                console_rows,
                use_container_width=True,
                hide_index=True,
            )


    # ---------- Investigation Explorer ----------

    st.divider()
    st.subheader("Investigation Explorer")
    st.caption(
        "Select an entity to inspect its direct connections "
        "and the evidence supporting each relationship."
    )

    if graph.number_of_nodes() == 0:
        st.info("No entities are available to explore.")
    else:
        node_ids = list(graph.nodes)

        def format_entity(node_id):
            node_data = graph.nodes[node_id]
            name = node_data.get("canonical_name", str(node_id))
            entity_type = node_data.get("entity_type", "UNKNOWN")
            return f"{name} ({entity_type})"

        selected_node = st.selectbox(
            "Search or select an entity",
            options=node_ids,
            format_func=format_entity,
            key="explorer_selected_entity",
        )

        selected_data = graph.nodes[selected_node]
        selected_name = selected_data.get(
            "canonical_name", str(selected_node)
        )
        selected_type = selected_data.get("entity_type", "UNKNOWN")

        st.markdown(f"### {selected_name}")
        st.caption(f"Entity type: {selected_type}")

        
        # ---------- Explore connected entities ----------

        connection_depth = st.radio(
            "Connection depth",
            options=[1, 2],
            format_func=lambda value: (
                "Direct connections (1 hop)"
                if value == 1
                else "Extended network (2 hops)"
            ),
            horizontal=True,
            key="explorer_connection_depth",
        )

        # Find nearby entities in either direction. Relationship
        # arrows remain unchanged in the displayed evidence table.
        distances = {selected_node: 0}
        frontier = [selected_node]

        while frontier:
            current_node = frontier.pop(0)
            current_distance = distances[current_node]

            if current_distance >= connection_depth:
                continue

            if graph.is_directed():
                neighbors = set(graph.successors(current_node))
                neighbors.update(graph.predecessors(current_node))
            else:
                neighbors = set(graph.neighbors(current_node))

            for neighbor in neighbors:
                if neighbor not in distances:
                    distances[neighbor] = current_distance + 1
                    frontier.append(neighbor)

        # Include relationship records inside the explored neighborhood.
        connections = []

        if graph.is_multigraph():
            edge_iterator = graph.edges(keys=True, data=True)

            for source, target, key, data in edge_iterator:
                if source not in distances or target not in distances:
                    continue

                source_distance = distances[source]
                target_distance = distances[target]

                if connection_depth == 1:
                    include_edge = (
                        source == selected_node
                        or target == selected_node
                    )
                else:
                    include_edge = (
                        max(source_distance, target_distance) <= 2
                        and min(source_distance, target_distance) < 2
                    )

                if include_edge:
                    direction = (
                        "Outgoing"
                        if source == selected_node
                        else "Incoming"
                        if target == selected_node
                        else "Extended network"
                    )
                    connections.append(
                        (source, target, direction, data)
                    )
        else:
            for source, target, data in graph.edges(data=True):
                if source not in distances or target not in distances:
                    continue

                source_distance = distances[source]
                target_distance = distances[target]

                if connection_depth == 1:
                    include_edge = (
                        source == selected_node
                        or target == selected_node
                    )
                else:
                    include_edge = (
                        max(source_distance, target_distance) <= 2
                        and min(source_distance, target_distance) < 2
                    )

                if include_edge:
                    direction = (
                        "Outgoing"
                        if source == selected_node
                        else "Incoming"
                        if target == selected_node
                        else "Extended network"
                    )
                    connections.append(
                        (source, target, direction, data)
                    )


        if not connections:
            st.info(
                "No direct relationships were found for this entity."
            )
        else:
            st.metric("Direct relationships", len(connections))

            connection_rows = []

            for source, target, direction, data in connections:
                source_name = graph.nodes[source].get(
                    "canonical_name", str(source)
                )
                target_name = graph.nodes[target].get(
                    "canonical_name", str(target)
                )

                connection_rows.append(
                    {
                        "Direction": direction,
                        "Source Entity": source_name,
                        "Relationship": data.get(
                            "relationship_type", "RELATED_TO"
                        ),
                        "Target Entity": target_name,
                        "Document": data.get(
                            "filename", "Unknown document"
                        ),
                        "Evidence": data.get(
                            "evidence", "No evidence recorded"
                        ),
                    }
                )

            # ---------- Relationship filters ----------

            st.markdown("#### Filter relationships")

            relationship_types = sorted(
                {row["Relationship"] for row in connection_rows}
            )
            source_documents = sorted(
                {row["Document"] for row in connection_rows}
            )

            filter_col1, filter_col2 = st.columns(2)

            with filter_col1:
                selected_types = st.multiselect(
                    "Relationship type",
                    options=relationship_types,
                    default=relationship_types,
                    key="explorer_relationship_types",
                )

            with filter_col2:
                selected_documents = st.multiselect(
                    "Source document",
                    options=source_documents,
                    default=source_documents,
                    key="explorer_source_documents",
                )

            filtered_rows = [
                row
                for row in connection_rows
                if (
                    row["Relationship"] in selected_types
                    and row["Document"] in selected_documents
                )
            ]

            st.caption(
                f"Showing {len(filtered_rows)} of "
                f"{len(connection_rows)} direct relationship record(s)."
            )

            if filtered_rows:
                st.dataframe(
                    filtered_rows,
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info(
                    "No relationships match the selected filters. "
                    "Try selecting another type or document."
                )



st.divider()
st.caption(
    "DossierIQ · Traceable document intelligence "
    "with evidence-backed relationships"
)
