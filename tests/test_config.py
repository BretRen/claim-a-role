import os
import unittest
from unittest.mock import patch

from config import Config


class TestConfig(unittest.TestCase):
    def test_admin_parsing(self):
        with patch.dict(os.environ, {
            "FLUXER_BOT_TOKEN": "test_app_id.test_secret",
            "ADMIN_USER_IDS": "111, 222 , 333",
            "FLUXER_API_BASE": "https://custom.fluxer.app/"
        }):
            cfg = Config()
            self.assertEqual(cfg.bot_token, "test_app_id.test_secret")
            self.assertEqual(cfg.api_base, "https://custom.fluxer.app")
            self.assertTrue(cfg.is_admin("111"))
            self.assertTrue(cfg.is_admin(222))
            self.assertTrue(cfg.is_admin("333"))
            self.assertFalse(cfg.is_admin("444"))
            self.assertFalse(cfg.is_admin(""))

    def test_validation_missing_token(self):
        with patch.dict(os.environ, {"FLUXER_BOT_TOKEN": ""}):
            cfg = Config()
            with self.assertRaises(ValueError):
                cfg.validate()


if __name__ == "__main__":
    unittest.main()
