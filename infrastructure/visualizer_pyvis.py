import os
import html
from typing import Set, Final, Optional
from pyvis.network import Network

from core.interfaces import IGraphVisualizer
from core.config import VisualizerConfig
from core.logger import get_logger

logger = get_logger(__name__)


class GraphConstants:
    """Aesthetic and UI configuration for the Spider Graph."""
    BG_COLOR: Final[str] = "#121212"
    FONT_COLOR: Final[str] = "white"
    NODE_SHAPE: Final[str] = "dot"
    NODE_SIZE: Final[int] = 20
    LABEL_MAX_LENGTH: Final[int] = 35

    # Custom CSS/HTML Overlay for the live dashboard
    LEGEND_TEMPLATE: Final[str] = """
    <div id="hunt-legend" style="position: absolute; top: 20px; left: 20px; z-index: 1000; 
                background-color: rgba(25, 25, 25, 0.95); padding: 15px; 
                border-radius: 8px; border: 1px solid #444; color: #ddd; 
                font-family: 'Segoe UI', sans-serif; box-shadow: 0 4px 12px rgba(0,0,0,0.6);">
        <h3 style="margin: 0 0 12px 0; color: #fff; font-size: 14px; border-bottom: 1px solid #444; padding-bottom: 5px;">
            Agent Discovery States
        </h3>
        <style>
            .legend-item { margin-bottom: 8px; font-size: 13px; display: flex; align-items: center; }
            .dot { width: 12px; height: 12px; border-radius: 50%; margin-right: 10px; }
        </style>
        <div class="legend-item"><span class="dot" style="background-color: #8A2BE2;"></span>Search Query</div>
        <div class="legend-item"><span class="dot" style="background-color: #FFD700;"></span>Pending Investigation</div>
        <div class="legend-item"><span class="dot" style="background-color: #1E90FF;"></span>Branch Followed</div>
        <div class="legend-item"><span class="dot" style="background-color: #32CD32;"></span>Converted Lead</div>
        <div class="legend-item"><span class="dot" style="background-color: #FF4500;"></span>Pruned / Rejected</div>
        <div class="legend-item"><span class="dot" style="background-color: #A9A9A9;"></span>Skipped / Duplicate</div>
    </div>
    """


class PyvisGraphVisualizer(IGraphVisualizer):
    """
    Generates and updates a high-fidelity interactive Spider Graph.
    Uses Pyvis for physics-based layout and custom HTML injection for the UI dashboard.
    """

    def __init__(self, config: VisualizerConfig):
        self.output_file = config.output_file
        self._node_registry: Set[str] = set()
        self._edge_registry: Set[str] = set()

        self._purge_legacy_file()

        # Initialize Pyvis Network with remote CDN to ensure reliability in isolated environments
        self.net = Network(
            directed=True,
            height="100vh",
            width="100%",
            bgcolor=GraphConstants.BG_COLOR,
            font_color=GraphConstants.FONT_COLOR,
            cdn_resources="remote"
        )

        self._configure_physics()
        self._rendered_once = False

    def _purge_legacy_file(self) -> None:
        """Attempts to clear previous hunt data from disk."""
        if os.path.exists(self.output_file):
            try:
                os.remove(self.output_file)
                logger.info(f"Cleaned legacy graph at: {self.output_file}")
            except OSError as e:
                logger.warning(f"Legacy graph file locked by browser. Updates will overwrite. Error: {e}")

    def _configure_physics(self) -> None:
        """Injects custom Vis.js physics and interaction options."""
        options = {
            "nodes": {
                "borderWidth": 2,
                "shadow": {"enabled": True, "color": "rgba(0,0,0,0.5)"},
                "font": {"size": 14, "face": "Tahoma", "background": "rgba(0,0,0,0.3)"}
            },
            "edges": {
                "color": {"inherit": "from"},
                "smooth": {"enabled": True, "type": "dynamic"}
            },
            "physics": {
                "barnesHut": {
                    "gravitationalConstant": -20000,
                    "centralGravity": 0.3,
                    "springLength": 150,
                    "springConstant": 0.04
                },
                "stabilization": {"enabled": True, "iterations": 100}
            },
            "interaction": {"hover": True, "navigationButtons": True}
        }
        import json
        self.net.set_options(json.dumps(options))

    def add_node(self, node_id: str, label: str, color: str, title: Optional[str] = None) -> None:
        """
        Idempotently adds or updates a node in the graph.

        Args:
            node_id: Unique identifier (URL or Query string).
            label: Text displayed on the graph node.
            color: Hex color string.
            title: Tooltip content (supports basic HTML).
        """
        # Truncate labels to keep the graph readable
        display_label = label if len(label) <= GraphConstants.LABEL_MAX_LENGTH else f"{label[:32]}..."

        # Sanitize HTML tooltips to prevent JS breakage
        safe_title = html.escape(title) if title else node_id

        if node_id in self._node_registry:
            # Update existing node attributes
            for node in self.net.nodes:
                if node['id'] == node_id:
                    node['color'] = color
                    node['title'] = safe_title
                    break
        else:
            # Register new node
            self.net.add_node(
                n_id=node_id,
                label=display_label,
                color=color,
                title=safe_title,
                shape=GraphConstants.NODE_SHAPE,
                size=GraphConstants.NODE_SIZE
            )
            self._node_registry.add(node_id)

    def add_edge(self, source_id: str, target_id: str) -> None:
        """Creates a directional link between two nodes if not already present."""
        edge_key = f"{source_id}->{target_id}"

        if source_id == target_id or edge_key in self._edge_registry:
            return

        # Ensure both nodes exist before drawing edge to prevent Pyvis crash
        if source_id in self._node_registry and target_id in self._node_registry:
            try:
                self.net.add_edge(source_id, target_id)
                self._edge_registry.add(edge_key)
            except (AssertionError, ValueError):
                pass

    def render(self) -> None:
        """Persists the current state to HTML and injects the UI overlay."""
        try:
            self.net.save_graph(self.output_file)
            self._apply_ui_overlay()

            if not self._rendered_once:
                logger.info(f"Spider Graph is live. Access via: {os.path.abspath(self.output_file)}")
                self._rendered_once = True
        except Exception as e:
            logger.error(f"Render engine failure: {str(e)}", exc_info=True)

    def _apply_ui_overlay(self) -> None:
        """Injects custom HTML legend and responsive meta-tags into the Pyvis output."""
        if not os.path.exists(self.output_file):
            return

        try:
            with open(self.output_file, "r", encoding="utf-8") as f:
                content = f.read()

            if "</body>" in content and "hunt-legend" not in content:
                # Add Legend and ensure the view is responsive on mobile
                meta_tags = '<meta name="viewport" content="width=device-width, initial-scale=1.0">'
                updated_content = content.replace("<head>", f"<head>{meta_tags}")
                updated_content = updated_content.replace("</body>", f"{GraphConstants.LEGEND_TEMPLATE}</body>")

                with open(self.output_file, "w", encoding="utf-8") as f:
                    f.write(updated_content)
        except Exception as e:
            logger.warning(f"UI Overlay injection failed: {str(e)}")