"""Interactive knowledge graph visualization for DossierIQ."""

from html import escape
import math

import networkx as nx
import streamlit as st
import streamlit.components.v1 as components
from pyvis.network import Network


BACKGROUND = "#0E1117"

ENTITY_COLORS = {
    "PERSON": "#F59E0B",
    "ORG": "#60A5FA",
    "GPE": "#34D399",
    "LOC": "#2DD4BF",
    "DATE": "#FBBF24",
    "EVENT": "#C084FC",
    "PRODUCT": "#FB7185",
    "NORP": "#A78BFA",
    "FAC": "#F472B6",
    "UNKNOWN": "#9CA3AF",
}


def _format_relationship(relationship_type: str) -> str:
    """Make relationship identifiers readable."""
    return relationship_type.replace("_", " ").title()


def _copy_graph_structure(graph):
    """Create an empty graph with the same directed/multigraph behavior."""
    if graph.is_multigraph():
        return nx.MultiDiGraph()
    if graph.is_directed():
        return nx.DiGraph()
    return nx.Graph()


def render_knowledge_graph(graph, height: str = "680px") -> None:
    """Render a filtered, interactive NetworkX graph using PyVis."""

    if not isinstance(height, str) or not height.endswith("px"):
        raise ValueError("height must be a pixel string, such as '680px'.")
    try:
        height_px = int(height[:-2])
    except ValueError as exc:
        raise ValueError("height must contain a valid pixel value.") from exc
    if height_px <= 0:
        raise ValueError("height must be greater than zero.")
    if graph is None or not hasattr(graph, "nodes") or not hasattr(graph, "edges"):
        raise ValueError("graph must be a NetworkX-compatible graph.")

    st.subheader("Interactive Knowledge Graph")
    st.caption(
        "Explore the full entity context with a cleaner layout. "
        "Hover over a relationship to inspect its source and evidence."
    )

    if graph.number_of_nodes() == 0:
        st.info("This investigation has no entities to visualize.")
        return

    # ---------- Filters (preserved) ----------
    available_types = sorted({
        str(data.get("entity_type", "UNKNOWN")).upper()
        for _, data in graph.nodes(data=True)
    })

    if graph.is_multigraph():
        edge_records = list(graph.edges(keys=True, data=True))
        relationship_values = [
            str(data.get("relationship_type", "RELATED_TO"))
            for _, _, _, data in edge_records
        ]
    else:
        edge_records = list(graph.edges(data=True))
        relationship_values = [
            str(data.get("relationship_type", "RELATED_TO"))
            for _, _, data in edge_records
        ]

    available_relationships = sorted(set(relationship_values))
    filter_col1, filter_col2 = st.columns(2)

    with filter_col1:
        selected_types = st.multiselect(
            "Entity types",
            options=available_types,
            default=available_types,
            key="graph_entity_types",
        )

    with filter_col2:
        selected_relationships = st.multiselect(
            "Relationship types",
            options=available_relationships,
            default=available_relationships,
            format_func=_format_relationship,
            key="graph_relationship_types",
        )

    show_isolated = st.checkbox(
        "Show entities with no visible connections",
        value=True,
        key="graph_show_isolated",
        help="Keep dates, people, and locations visible even when no relationship rule connected them.",
    )

    # ---------- Apply filters ----------
    filtered = _copy_graph_structure(graph)

    for node_id, data in graph.nodes(data=True):
        entity_type = str(data.get("entity_type", "UNKNOWN")).upper()
        if entity_type in selected_types:
            filtered.add_node(node_id, **dict(data))

    for record in edge_records:
        if graph.is_multigraph():
            source, target, key, data = record
        else:
            source, target, data = record
            key = None

        relationship_type = str(data.get("relationship_type", "RELATED_TO"))
        if (
            source in filtered
            and target in filtered
            and relationship_type in selected_relationships
        ):
            if filtered.is_multigraph():
                filtered.add_edge(source, target, key=key, **dict(data))
            else:
                filtered.add_edge(source, target, **dict(data))

    # Only remove isolated entities when the user explicitly disables them.
    if not show_isolated:
        connected_nodes = {
            node for source, target in filtered.edges() for node in (source, target)
        }
        filtered = filtered.subgraph(connected_nodes).copy()

    visible_nodes = filtered.number_of_nodes()
    visible_edges = filtered.number_of_edges()
    metric1, metric2 = st.columns(2)
    metric1.metric("Visible entities", visible_nodes)
    metric2.metric("Visible relationships", visible_edges)

    if visible_nodes == 0:
        st.info("No entities match these filters. Select more entity or relationship types.")
        return

    if visible_edges == 0:
        st.info("No relationships match the current filters. Visible entities are shown without links.")

    # ---------- Build the graph ----------
    network = Network(
        height=height,
        width="100%",
        directed=filtered.is_directed(),
        bgcolor=BACKGROUND,
        font_color="#F3F4F6",
        notebook=False,
        cdn_resources="in_line",
        select_menu=False,
        filter_menu=False,
    )

    # Give connected nodes the central stage; disconnected nodes form a loose outer ring.
    degree = dict(filtered.degree())
    connected_nodes = [node for node in filtered.nodes if degree.get(node, 0) > 0]
    isolated_nodes = [node for node in filtered.nodes if degree.get(node, 0) == 0]

    # Stable initial positions reduce the tendency for isolated entities to overlap the core.
    # PyVis/vis-network still allows users to drag every node freely.
    core_count = max(len(connected_nodes), 1)
    core_radius = max(130, min(260, 38 * core_count))
    positions = {}

    for i, node_id in enumerate(connected_nodes):
        angle = (2 * 3.141592653589793 * i / core_count) - 1.5707963267948966
        positions[node_id] = (core_radius * math.cos(angle),
                              core_radius * math.sin(angle))

    outer_radius = core_radius + 210
    isolated_count = max(len(isolated_nodes), 1)
    for i, node_id in enumerate(isolated_nodes):
        angle = (2 * 3.141592653589793 * i / isolated_count) - 1.5707963267948966
        positions[node_id] = (outer_radius * math.cos(angle),
                              outer_radius * math.sin(angle))

    for node_id, data in filtered.nodes(data=True):
        name = str(data.get("canonical_name", node_id))
        entity_type = str(data.get("entity_type", "UNKNOWN")).upper()
        mentions = data.get("mentions", [])
        mention_count = len(mentions) if isinstance(mentions, (list, tuple, set)) else 0
        tooltip = (
            f"<b>{escape(name)}</b><br>"
            f"Type: {escape(entity_type)}<br>"
            f"Mentions: {mention_count}"
        )
        x, y = positions[node_id]
        is_connected = degree.get(node_id, 0) > 0
        color = ENTITY_COLORS.get(entity_type, ENTITY_COLORS["UNKNOWN"])

        network.add_node(
            str(node_id),
            label=name,
            title=tooltip,
            group=entity_type,
            color={
                "background": color,
                "border": "#E2E8F0",
                "highlight": {"background": color, "border": "#FFFFFF"},
            },
            shape="dot",
            size=(29 if entity_type == "ORG" else 23) if is_connected else 17,
            borderWidth=2,
            x=x,
            y=y,
            physics=is_connected,
            fixed={"x": False, "y": False},
            font={
                "size": 16 if is_connected else 13,
                "face": "Arial",
                "color": "#F3F4F6",
                "strokeWidth": 3,
                "strokeColor": BACKGROUND,
            },
        )

    if filtered.is_multigraph():
        visible_edges = filtered.edges(keys=True, data=True)
        edge_iterator = (
            (source, target, key, data)
            for source, target, key, data in visible_edges
        )
    else:
        visible_edges = filtered.edges(data=True)
        edge_iterator = (
            (source, target, None, data)
            for source, target, data in visible_edges
        )

    for source, target, key, data in edge_iterator:
        relationship_type = str(data.get("relationship_type", "RELATED_TO"))
        full_label = _format_relationship(relationship_type)
        edge_label = full_label if len(full_label) <= 22 else full_label[:19].rstrip() + "..."
        evidence = str(data.get("evidence", "No evidence recorded"))
        filename = str(data.get("filename", "Unknown document"))
        tooltip = (
            f"<b>{escape(full_label)}</b><br>"
            f"Source document: {escape(filename)}<br>"
            f"Evidence: {escape(evidence)}"
        )

        network.add_edge(
            str(source),
            str(target),
            title=tooltip,
            label=edge_label,
            arrows="to",
            width=2,
            color={"color": "#64748B", "highlight": "#F8FAFC", "hover": "#CBD5E1"},
            smooth={"enabled": True, "type": "dynamic"},
            font={
                "size": 11,
                "face": "Arial",
                "color": "#E5E7EB",
                "strokeWidth": 4,
                "strokeColor": BACKGROUND,
                "align": "middle",
                "background": BACKGROUND,
            },
        )

    network.set_options(
        """
        {
          "autoResize": true,
          "layout": {
            "improvedLayout": true,
            "randomSeed": 23
          },
          "interaction": {
            "hover": true,
            "navigationButtons": true,
            "keyboard": {"enabled": true},
            "tooltipDelay": 120,
            "hideEdgesOnDrag": true,
            "zoomView": true,
            "dragNodes": true,
            "dragView": true
          },
          "physics": {
            "enabled": true,
            "solver": "forceAtlas2Based",
            "forceAtlas2Based": {
              "gravitationalConstant": -65,
              "centralGravity": 0.008,
              "springLength": 175,
              "springConstant": 0.035,
              "damping": 0.72,
              "avoidOverlap": 1
            },
            "minVelocity": 0.5,
            "stabilization": {
              "enabled": true,
              "iterations": 350,
              "updateInterval": 25,
              "fit": true
            }
          },
          "nodes": {
            "scaling": {"min": 18, "max": 31},
            "shadow": {"enabled": true, "size": 6, "x": 0, "y": 2}
          },
          "edges": {
            "selectionWidth": 2,
            "hoverWidth": 3
          }
        }
        """
    )

    html_content = network.generate_html()
    components.html(html_content, height=height_px + 20, scrolling=False)
