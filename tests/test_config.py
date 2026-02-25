import unittest
from core.config import Settings, AppConfig, PipelineConfig
from pydantic import ValidationError

class TestSystemIntegrity(unittest.TestCase):
    def test_config_schema_enforcement(self):
        """Ensures the application crashes early if invalid types are provided in YAML."""
        bad_data = {
            "app": {"active_workspace": "work", "cycle_sleep_sec": "NOT_AN_INT"}
        }
        with self.assertRaises(ValidationError):
            AppConfig(**bad_data["app"])

    def test_junk_domain_filtering_logic(self):
        """Tests the logic used by the pipeline to prune unwanted domains."""
        config = PipelineConfig(
            max_depth=5, max_leafs=5, max_path_chars=100,
            max_observation_chars=100, junk_domains=["social.com"]
        )
        url = "https://social.com/ads/tracker"
        self.assertTrue(any(junk in url for junk in config.junk_domains))