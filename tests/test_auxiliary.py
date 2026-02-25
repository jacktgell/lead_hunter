import unittest
from unittest.mock import MagicMock, patch, mock_open
from infrastructure.visualizer_pyvis import PyvisGraphVisualizer
from core.config import VisualizerConfig


class TestAuxiliarySystems(unittest.TestCase):
    """
    Coverage Booster: Tests for the UI/Visualizer components.
    These are 'Happy Path' tests to ensure the UI generation logic doesn't crash.
    """

    def test_visualizer_renders_html(self):
        """Ensures the graph visualizer attempts to write to disk."""
        config = VisualizerConfig(output_file="graph.html")

        # Mock the Pyvis Network object so we don't need a real browser/network
        with patch("infrastructure.visualizer_pyvis.Network") as mock_net_cls:
            mock_net = mock_net_cls.return_value
            # Setup the visualizer
            vis = PyvisGraphVisualizer(config)

            # Simulate adding data
            vis.add_node("node1", "label", "red", "title")
            vis.add_edge("node1", "node2")

            # Mock file opening so we don't actually write 'graph.html' to your disk during tests
            with patch("builtins.open", mock_open(read_data="<html><body></body>")) as mock_file:
                vis.render()

            mock_net.add_node.assert_called()
            mock_net.save_graph.assert_called_with("graph.html")

    def test_visualizer_handles_duplicates(self):
        """Ensures adding the same node ID twice updates it instead of crashing."""
        config = VisualizerConfig(output_file="graph.html")

        with patch("infrastructure.visualizer_pyvis.Network") as mock_net_cls:
            vis = PyvisGraphVisualizer(config)

            # Inject existing node state into the mock network
            vis.net.nodes = [{'id': 'A', 'color': 'blue'}]

            # Try to add 'A' again with a new color
            vis.add_node("A", "Label", "red")

            # Should NOT call add_node (it updates in place)
            mock_net_cls.return_value.add_node.assert_not_called()

            # Check manual update logic
            self.assertEqual(vis.net.nodes[0]['color'], 'red')