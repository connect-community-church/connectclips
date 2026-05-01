<p align="center">
  <img src="frontend/src/assets/connectclips-banner.png" alt="ConnectClips" width="900">
</p>

# ConnectClips

Self-hosted, AI-driven sermon-to-clips pipeline. Drop in a sermon recording; get back ready-to-post short-form vertical clips for TikTok, Instagram Reels, YouTube Shorts, and Facebook Reels.

Built for Connect Community Church (Hamilton, Ontario). Open-sourced because no church should have to choose between paying a recurring SaaS fee and not posting clips.

---

## Why this exists

The going rate for AI clip-selection SaaS (Opus Clip et al.) is roughly $20–50 / month — a non-starter for a once-a-week workflow at a small church. We had hardware sitting idle six days a week (the streaming PC). So we put it to work.

Recurring cost: a few cents of Anthropic Claude API per sermon (~$0.05). No subscription, no per-seat pricing, no "we changed our pricing model" emails. Sermon files never leave the building.

## What it does

1. **Ingest** — paste a YouTube link or upload a sermon file
2. **Transcribe** — `faster-whisper large-v3` on the GPU with word-level timestamps
3. **Pick clips** — Claude Sonnet picks 5–10 candidate moments, writes a 4–8 word hook title for each, and rates the opening's hook strength 0–100
4. **Reframe** — vertical 9:16 reframe with face tracking and per-shot smoothing (handles ATEM PiP layouts and scene cuts so the speaker stays centered)
5. **Caption** — word-by-word karaoke-style captions in the style of your choice
6. **Export** — 1080×1920 MP4, ready to upload to any short-form platform

The volunteer's flow: paste a YouTube link, walk away while the pipeline runs (~15 min for a 50-minute sermon), come back to a list of clip suggestions, trim if needed, export, schedule on each platform.

See [`docs/operator-manual.md`](docs/operator-manual.md) for the full volunteer workflow with screenshots.

## Hardware requirements

This release targets **NVIDIA GPUs**. AMD / Intel / Apple Silicon support is on the roadmap (see [Status](#status) below); for now look for:

| Component | Minimum | Notes |
|---|---|---|
| GPU | NVIDIA, **8 GB+ VRAM** | RTX 3060 Ti tested daily; GTX 1080 / RTX 2060 family work at lower throughput |
| CPU | Modern x86_64 | Ryzen 5 / Core i5 era or newer |
| RAM | 16 GB | 32 GB is comfortable if you also use the box for other work |
| Disk | 100 GB free | Sermon files are large; clips are small |
| OS | Windows 10/11 + WSL2 (Ubuntu 24.04) | Pure Linux works the same; macOS / native Windows not yet supported |

Tested on a Ryzen 7 5700X + RTX 3060 Ti running WSL2 / Ubuntu 24.04.

## Quick start

For a real install with autostart, follow [`docs/DEPLOYING-wsl.md`](docs/DEPLOYING-wsl.md). The 30-second version:

```bash
git clone https://github.com/connect-community-church/connectclips.git
cd connectclips

# Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in ANTHROPIC_API_KEY, ADMIN_PASSWORD, SESSION_SECRET

# Pre-fetch the YuNet face-detection model
mkdir -p ~/.cache/connectclips
curl -L -o ~/.cache/connectclips/face_detection_yunet_2023mar.onnx \
  https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/face_detection_yunet_2023mar.onnx

# Frontend
cd ../frontend
npm install
npm run build

# Run
cd ../backend
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765
```

Browse to <http://localhost:8765>.

## How it works

```
┌──────────┐   ┌────────────┐   ┌─────────────┐   ┌────────────┐
│ Ingest   │──▶│ Transcribe │──▶│ Pick clips  │──▶│ Pre-scan   │
│ yt-dlp / │   │ faster-    │   │ Claude      │   │ faces      │
│ upload   │   │ whisper    │   │ Sonnet      │   │ (YuNet/ORT)│
└──────────┘   └────────────┘   └─────────────┘   └─────┬──────┘
                                                        │
                                                        ▼
   ┌──────────────────┐    ┌─────────────────┐   ┌─────────────────┐
   │ Reframe + caption│◀───│ Volunteer trims │◀──│ Auto-suggested  │
   │ encode (NVENC)   │    │ + picks face    │   │ clips, hook     │
   │                  │    │                 │   │ scores, titles  │
   └──────────────────┘    └─────────────────┘   └─────────────────┘
```

### Stack

- **Backend**: Python 3.12 / FastAPI / SQLite (jobs persistence) / asyncio (in-process pipeline)
- **Frontend**: Vite + React (single-page app, served as static dist by the backend)
- **AI**: `faster-whisper` (transcription), Anthropic Claude API (clip selection + hook scoring), YuNet via ONNX Runtime (face detection)
- **Video**: PyAV (decode) + FFmpeg + `h264_nvenc` (encode); ASS subtitles for captions
- **Auth**: Tailscale Serve identity headers, with an `ADMIN_PASSWORD` fallback. No public exposure required.

### Pipeline auto-chains

`upload` → `transcribe` → (`select_clips` + `prescan_faces` in parallel) → `export_clip` (volunteer-triggered).

The pre-scan runs YuNet over the entire source once at ingest time. Trim adjustments and exports later reuse the cached scan, so a face-tracked preview opens in milliseconds instead of spending 25 seconds re-scanning each clip range.

## Status

**v0.1 — pre-release.** Working end-to-end and in real use at one church. Two sermons fully through the pipeline.

Known limitations:

- **NVIDIA GPU required** — CPU fallback is on the roadmap. Without it, transcription takes 5–10× longer.
- **Multi-speaker face picker** — fragments across ATEM full-frame ↔ PiP layout switches because the matcher doesn't use face embeddings yet. Auto-pick (highest-score live face per sample) handles single-pastor sermons correctly, which covers the common case.
- **macOS / native-Windows deployment** — not documented yet. WSL2 is the supported path.

See the [issues](../../issues) for what's actively tracked.

## Roadmap

- CPU-only fallback for transcribe + face scan, so people without an NVIDIA GPU can at least try it
- Face-embedding-based re-identification (drop-in InsightFace ONNX) so the multi-face picker works across layout shifts
- Native macOS deployment guide (Apple Silicon: `whisper.cpp` + Metal + VideoToolbox)
- Native Windows / AMD / Intel paths via DirectML execution provider + `h264_amf` / `h264_qsv`
- Multiple ingest sources beyond YouTube and direct upload (Vimeo, raw stream archives, RTMP capture)

## Contributing

Issues and PRs welcome. For substantial changes, please open an issue first to discuss.

Useful low-effort contributions:

- New caption styles — see [`backend/app/services/captions.py`](backend/app/services/captions.py) `STYLES` dict and the matching `.cap-live.style-*` rules in [`frontend/src/App.css`](frontend/src/App.css).
- Operator-manual edits — see [`docs/operator-manual.md`](docs/operator-manual.md).
- Cross-platform deployment notes from your own setup.

## License

MIT — see [LICENSE](LICENSE).

## Acknowledgments

Caption rendering technique borrows ideas from [captacity](https://github.com/unconv/captacity). Face detection model: [YuNet 2023mar](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) via ONNX Runtime. Built primarily with Claude Code.
