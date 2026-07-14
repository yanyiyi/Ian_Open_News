import json
import tempfile
import unittest
from pathlib import Path

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
