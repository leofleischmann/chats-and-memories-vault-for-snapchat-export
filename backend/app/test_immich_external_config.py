"""Regression tests for external Immich config (no network)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from app.immich_config import (
    CONFIG_KEY_EXTERNAL_API_KEY,
    CONFIG_KEY_EXTERNAL_ENABLED,
    CONFIG_KEY_EXTERNAL_URL,
    get_effective_immich_url,
    save_external_immich_settings,
)


class ImmichExternalConfigTests(unittest.TestCase):
    def test_bundled_url_when_no_file(self):
        with tempfile.TemporaryDirectory() as d:
            with patch("app.immich_config.settings") as mock_settings:
                mock_settings.immich_url = "http://bundled:2283"
                self.assertEqual(get_effective_immich_url(d), "http://bundled:2283")

    def test_external_url_when_active(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "immich_config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        CONFIG_KEY_EXTERNAL_ENABLED: True,
                        CONFIG_KEY_EXTERNAL_URL: "https://immich.example/",
                        CONFIG_KEY_EXTERNAL_API_KEY: "secret",
                    },
                    f,
                )
            with patch("app.immich_config.settings") as mock_settings:
                mock_settings.immich_url = "http://bundled:2283"
                self.assertEqual(get_effective_immich_url(d), "https://immich.example")

    def test_bundled_when_flag_true_but_url_blank(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "immich_config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        CONFIG_KEY_EXTERNAL_ENABLED: True,
                        CONFIG_KEY_EXTERNAL_URL: "   ",
                    },
                    f,
                )
            with patch("app.immich_config.settings") as mock_settings:
                mock_settings.immich_url = "http://bundled:2283"
                self.assertEqual(get_effective_immich_url(d), "http://bundled:2283")

    def test_disable_external_keeps_bundled_api_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "immich_config.json")
            with open(p, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        CONFIG_KEY_EXTERNAL_ENABLED: True,
                        CONFIG_KEY_EXTERNAL_URL: "https://x.example",
                        CONFIG_KEY_EXTERNAL_API_KEY: "ext-key",
                        "api_key": "bundled-key",
                    },
                    f,
                )
            save_external_immich_settings(
                d,
                enabled=False,
                external_immich_url=None,
                external_immich_api_key=None,
            )
            with open(p, encoding="utf-8") as f:
                cfg = json.load(f)
            self.assertFalse(cfg.get(CONFIG_KEY_EXTERNAL_ENABLED))
            self.assertNotIn(CONFIG_KEY_EXTERNAL_API_KEY, cfg)
            self.assertEqual(cfg.get("api_key"), "bundled-key")


if __name__ == "__main__":
    unittest.main()
