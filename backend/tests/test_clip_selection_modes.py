from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
import unittest

_BASE = Path(tempfile.gettempdir()) / "connectclips-clip-selection-mode-test-env"
os.environ.setdefault("DATA_SOURCES_DIR", str(_BASE / "sources"))
os.environ.setdefault("DATA_WORK_DIR", str(_BASE / "work"))
os.environ.setdefault("DATA_CLIPS_DIR", str(_BASE / "clips"))
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings
from app.services import clip_selection


class _Usage:
    input_tokens = 1
    output_tokens = 1
    cache_creation_input_tokens = 0
    cache_read_input_tokens = 0


class _Response:
    model = "fake-claude"
    usage = _Usage()
    stop_reason = "end_turn"

    def __init__(self, parsed_output):
        self.parsed_output = parsed_output


class _Messages:
    def __init__(self):
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(clip_selection.ClipSelection(clips=[
            clip_selection.ClipCandidate(
                start=60.0,
                end=250.0,
                title="A Deeper Midweek Moment",
                rationale="This section develops one complete sermon idea.",
                hook_score=72,
                hook_rationale="The first line names a real struggle.",
            )
        ]))


class _Client:
    def __init__(self):
        self.messages = _Messages()


class ClipSelectionModeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        settings.data_work_dir = self.root / "work"
        settings.data_work_dir.mkdir(parents=True)
        self.transcript = self.root / "sermon.transcript.json"
        self.transcript.write_text(json.dumps({
            "source": "sermon.mp4",
            "duration": 1800,
            "segments": [
                {"start": 60.0, "end": 250.0, "text": "This is a longer sermon section with one complete idea.",
                 "words": [
                    {"start": 60.0, "end": 60.5, "word": "This"},
                    {"start": 249.0, "end": 250.0, "word": "idea"},
                 ]},
            ],
        }))
        self.client = _Client()
        self.orig_get_client = clip_selection._get_client
        clip_selection._client = None
        clip_selection._get_client = lambda: self.client

    def tearDown(self) -> None:
        clip_selection._get_client = self.orig_get_client
        self.tmp.cleanup()

    def test_deeper_mode_asks_for_midweek_length_clips_from_whole_transcript(self) -> None:
        result = clip_selection.select_clips(self.transcript, 1, 2, selection_mode="deeper")

        call = self.client.messages.calls[0]
        system_prompt = call["system"]
        user_text = call["messages"][0]["content"][0]["text"]
        self.assertEqual(result["selection_mode"], "deeper")
        self.assertIn("Deeper Clips", system_prompt)
        self.assertIn("2:30 to 5:00", system_prompt)
        self.assertIn("full sermon transcript", system_prompt)
        self.assertIn("Pick 1 to 2 Deeper Clips", user_text)

    def test_default_mode_remains_shorts(self) -> None:
        result = clip_selection.select_clips(self.transcript, 3, 8)

        call = self.client.messages.calls[0]
        self.assertEqual(result["selection_mode"], "shorts")
        self.assertIn("30 to 90 seconds", call["system"])


if __name__ == "__main__":
    unittest.main()
