import unittest
from core.config import load_settings
from pydantic import ValidationError

class TestConfigurationHardening(unittest.TestCase):
    def test_env_variable_injection_security(self):
        """Ensures the system throws an EnvironmentError if SMTP secrets are missing."""
        # Simulate missing .env variables
        with unittest.mock.patch.dict('os.environ', {'SMTP_EMAIL': ''}):
            with self.assertRaises(EnvironmentError):
                load_settings("config.yaml")