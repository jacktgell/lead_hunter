import threading
from typing import Optional, Dict, Final
from urllib.parse import urlparse
from core.interfaces import IGraphVisualizer

# Standardized visualization themes for the lead discovery graph
NODE_THEME: Final[Dict[str, str]] = {
    "query": "#8A2BE2",  # Purple
    "pending": "#FFD700",  # Gold
    "prune": "#FF4500",  # Orange-Red
    "convert": "#32CD32",  # Lime-Green
    "skip": "#A9A9A9"  # Gray
}


class GraphTracker:
    """
    Thread-safe manager for real-time lead discovery visualization.
    Coordinates between the pipeline logic and the visual rendering engine.
    """

    def __init__(self, visualizer: IGraphVisualizer):
        self.visualizer = visualizer
        self._lock = threading.Lock()
        # Track previous states to minimize redundant render calls
        self._state_cache: Dict[str, str] = {}

    def _generate_label(self, node_id: str) -> str:
        """Creates a human-readable label for the graph node."""
        if node_id.startswith("QUERY:"):
            return node_id

        try:
            parsed = urlparse(node_id)
            # Display domain and a snippet of the path for context
            path_snippet = parsed.path[:15]
            return f"{parsed.netloc}{path_snippet}..." if path_snippet else parsed.netloc
        except Exception:
            return node_id[:30]

    def update_node(
            self,
            node_id: str,
            state: str,
            status_text: str,
            parent_id: Optional[str] = None
    ) -> None:
        """
        Atomically updates a node's visual state and hierarchy.

        Args:
            node_id: Unique identifier (URL or Query string).
            state: The logical state (must match keys in NODE_THEME).
            status_text: Detailed tooltip/title for the node.
            parent_id: Optional ID of the caller node to create an edge.
        """
        color = NODE_THEME.get(state, NODE_THEME["prune"])
        label = self._generate_label(node_id)

        with self._lock:
            # Check cache to avoid unnecessary visual updates if nothing changed
            cache_key = f"{node_id}-{state}-{status_text}"
            if self._state_cache.get(node_id) == cache_key:
                return

            self.visualizer.add_node(
                node_id,
                label=label,
                color=color,
                title=status_text
            )

            if parent_id and parent_id != node_id:
                self.visualizer.add_edge(parent_id, node_id)

            self._state_cache[node_id] = cache_key

            # Note: Depending on visualizer implementation, render() might
            # need to be debounced if this is called in a tight loop.
            self.visualizer.render()