from __future__ import annotations

import os
import tempfile
from pathlib import Path
import unittest

_BASE = Path(tempfile.gettempdir()) / "connectclips-clip-set-storage-test-env"
os.environ.setdefault("DATA_SOURCES_DIR", str(_BASE / "sources"))
os.environ.setdefault("DATA_WORK_DIR", str(_BASE / "work"))
os.environ.setdefault("DATA_CLIPS_DIR", str(_BASE / "clips"))
os.environ.setdefault("SESSION_SECRET", "test-secret")
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")

from app.config import settings
from app.services import clip_selection


class ClipSetStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        settings.data_work_dir = self.root / "work"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_shorts_and_deeper_clip_sets_have_separate_paths(self) -> None:
        source = "sermon.mp4"
        self.assertEqual(clip_selection.clips_path_for(source, "shorts").name, "clips.json")
        self.assertEqual(clip_selection.clips_path_for(source, "deeper").name, "clips.deeper.json")

    def test_write_clips_uses_selection_mode_to_preserve_both_sets(self) -> None:
        base = {"source": "sermon.mp4", "model": "fake", "created_at": "now", "usage": {}, "clips": []}
        shorts = clip_selection.write_clips({**base, "selection_mode": "shorts"})
        deeper = clip_selection.write_clips({**base, "selection_mode": "deeper"})

        self.assertNotEqual(shorts, deeper)
        self.assertTrue(shorts.exists())
        self.assertTrue(deeper.exists())


if __name__ == "__main__":
    unittest.main()
