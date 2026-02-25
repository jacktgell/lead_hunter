import unittest
from unittest.mock import MagicMock, patch
from infrastructure.compute_gcp import GcpOllamaManager
from core.config import GcpConfig


class TestGcpComputeLifecycle(unittest.TestCase):
    def setUp(self):
        self.config = GcpConfig(
            project_id="test-proj", zone="us-east1", instance_name="test-vm",
            default_port=11434, boot_settle_time_sec=0, tunnel_warmup_sec=0,
            api_max_retries=2, api_poll_delay_sec=0
        )
        # Mock the logger to prevent external API calls during test
        patchER = patch("infrastructure.compute_gcp.logger")
        self.mock_logger = patchER.start()
        self.addCleanup(patchER.stop)

        self.manager = GcpOllamaManager(self.config)

    @patch("google.cloud.compute_v1.InstancesClient")
    def test_wait_for_running_state_timeout(self, mock_client_cls):
        """Ensures the manager throws a TimeoutError if the VM hangs in PROVISIONING."""
        mock_client = mock_client_cls.return_value
        mock_instance = MagicMock()
        mock_instance.status = "PROVISIONING"
        mock_client.get.return_value = mock_instance

        self.manager.instances_client = mock_client

        # Fix: Mock time.sleep to raise an error to break the loop efficiently
        # OR mock time.time to simulate passage of time
        with patch("time.time", side_effect=[100, 100, 100, 5000]):
            with self.assertRaises(TimeoutError):
                self.manager.ensure_infrastructure_ready()

    @patch("requests.get")
    def test_ollama_api_polling_resilience(self, mock_requests):
        """Tests that the manager retries on ConnectionErrors (common during boot)."""
        import requests
        # Fail once, then succeed
        mock_requests.side_effect = [requests.exceptions.ConnectionError, MagicMock(status_code=200)]

        # Should not raise exception because the second call succeeds
        self.manager._wait_for_ollama("http://127.0.0.1:11434")
        self.assertEqual(mock_requests.call_count, 2)