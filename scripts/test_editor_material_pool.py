#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import local_web  # noqa: E402


def accepted_material(index: int) -> dict:
    return {
        "id": f"item-{index:03d}",
        "title": f"Material {index:03d}",
        "summary": f"Summary {index:03d}",
        "status": "triaged",
        "track": "open-tech-open-industry",
        "local_decision": {
            "action": "accepted-for-editing",
            "next_step": "run-writing-skill-before-pr",
            "decided_at": f"2026-06-01T00:00:{400 - index:03d}+00:00",
        },
    }


class EditorMaterialPoolTest(unittest.TestCase):
    def test_editor_material_json_includes_records_after_legacy_350_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            items_path = Path(tmp) / "items.jsonl"
            candidates_path = Path(tmp) / "candidates.jsonl"
            sessions_path = Path(tmp) / "editor-sessions.jsonl"
            viewpoints_path = Path(tmp) / "viewpoints.jsonl"
            local_web.write_jsonl(items_path, [accepted_material(index) for index in range(401)])
            local_web.write_jsonl(candidates_path, [])
            local_web.write_jsonl(sessions_path, [])
            local_web.write_jsonl(viewpoints_path, [])
            originals = (
                local_web.ITEMS,
                local_web.CANDIDATES,
                local_web.EDITOR_SESSIONS,
                local_web.VIEWPOINTS,
            )
            local_web.ITEMS = items_path
            local_web.CANDIDATES = candidates_path
            local_web.EDITOR_SESSIONS = sessions_path
            local_web.VIEWPOINTS = viewpoints_path
            captured: dict[str, str] = {}
            try:
                handler = local_web.Handler.__new__(local_web.Handler)
                handler.headers = {}
                handler.send_html = lambda title, body, status=local_web.HTTPStatus.OK: captured.update(body=body)
                handler.show_editor_console({})
            finally:
                (
                    local_web.ITEMS,
                    local_web.CANDIDATES,
                    local_web.EDITOR_SESSIONS,
                    local_web.VIEWPOINTS,
                ) = originals

        match = re.search(
            r'<script type="application/json" id="editor-available-materials">(.*?)</script>',
            captured["body"],
        )
        self.assertIsNotNone(match)
        payload = json.loads(match.group(1))
        self.assertEqual(len(payload), 401)
        self.assertIn("item-400", {record["id"] for record in payload})


if __name__ == "__main__":
    unittest.main()
