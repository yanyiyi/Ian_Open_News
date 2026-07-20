import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ai_model_settings as settings


class AiModelSettingsTest(unittest.TestCase):
    def test_defaults_never_select_premium(self) -> None:
        config = settings.load_settings(Path("/nonexistent/ai-model-settings.json"))
        self.assertEqual([], settings.validate_settings(config))
        for task in config["tasks"].values():
            provider = task["provider"]
            self.assertNotEqual("premium", settings.model_tier(provider, task["models"][provider]))

    def test_task_model_respects_override(self) -> None:
        self.assertEqual("manual-model", settings.task_model("translation", "codex", "manual-model"))

    def test_known_codex_model_missing_from_cli_falls_back_within_tier(self) -> None:
        config = settings.load_settings(Path("/nonexistent/ai-model-settings.json"))
        config["tasks"]["translation"]["models"]["codex"] = "gpt-5.6-luna"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(settings, "_codex_models", return_value=(["gpt-5.4-mini", "gpt-5.4"], "gpt-5.4")):
                self.assertEqual("gpt-5.4-mini", settings.task_model("translation", "codex", path=path))

    def test_older_codex_model_is_not_promoted_by_newer_desktop_cache(self) -> None:
        config = settings.load_settings(Path("/nonexistent/ai-model-settings.json"))
        config["tasks"]["translation"]["models"]["codex"] = "gpt-5.4"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(settings, "_codex_models", return_value=(["gpt-5.6-terra"], "gpt-5.6-terra")):
                self.assertEqual("gpt-5.4", settings.task_model("translation", "codex", path=path))

    def test_custom_codex_model_is_not_replaced(self) -> None:
        config = settings.load_settings(Path("/nonexistent/ai-model-settings.json"))
        config["tasks"]["translation"]["models"]["codex"] = "company-custom-model"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps(config), encoding="utf-8")
            with patch.object(settings, "_codex_models", return_value=(["gpt-5.4-mini"], "gpt-5.4-mini")):
                self.assertEqual("company-custom-model", settings.task_model("translation", "codex", path=path))

    def test_discovery_does_not_mix_unavailable_static_codex_models(self) -> None:
        with patch.object(settings, "_codex_models", return_value=(["gpt-5.4-mini"], "gpt-5.4-mini")), \
             patch.object(settings, "_cli_path", return_value="/tmp/fake-cli"), \
             patch.object(settings, "_run", return_value="codex-cli test"):
            discovered = settings.discover_cli_models(refresh=True)
        self.assertEqual(["gpt-5.4-mini"], discovered["codex"]["models"])

    def test_codex_new_model_falls_back_to_older_model_in_same_tier(self) -> None:
        self.assertEqual("gpt-5.4-mini", settings.codex_compatibility_fallback("gpt-5.6-luna"))
        self.assertEqual("gpt-5.4", settings.codex_compatibility_fallback("gpt-5.6-terra"))
        self.assertEqual("gpt-5.5", settings.codex_compatibility_fallback("gpt-5.6-sol"))

    def test_codex_upgrade_error_is_recognized(self) -> None:
        self.assertTrue(
            settings.codex_requires_newer_version(
                "The 'gpt-5.6-luna' model requires a newer version of Codex."
            )
        )

    def test_rejects_premium_as_default_when_policy_forbids_it(self) -> None:
        config = settings.load_settings(Path("/nonexistent/ai-model-settings.json"))
        config["tasks"]["translation"]["provider"] = "codex"
        config["tasks"]["translation"]["models"]["codex"] = "gpt-5.6-sol"
        self.assertTrue(any("premium" in error for error in settings.validate_settings(config)))

    def test_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            config = settings.load_settings(path)
            config["tasks"]["translation"]["provider"] = "claude"
            settings.save_settings(config, path)
            loaded = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual("claude", loaded["tasks"]["translation"]["provider"])


if __name__ == "__main__":
    unittest.main()
