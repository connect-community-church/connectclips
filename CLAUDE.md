# ConnectClips

Local open-source alternative to Opus Clip for generating short-form vertical clips from church sermon recordings. Volunteer-facing web app, self-hosted on the church's idle streaming PC.

## Why this exists

The church wants short clips of the sermon for social media without paying for Opus Clip. The user is willing to pay for Claude API usage but wants no other recurring SaaS cost. A go/no-go decision happens at a meeting on **2026-05-02**: either ConnectClips is good enough for volunteers to use, or fall back to Opus Clip.

## What "good enough" means

Two things will make or break volunteer adoption — judge every scope tradeoff against these:
1. **Vertical auto-reframing** that keeps the speaker in frame (face tracking, not naive center-crop) when the clip goes 16:9 → 9:16.
2. **Animated word-by-word captions** in the karaoke-highlight style people expect from short-form video.

If those two feel cheap, volunteers will ask to go back to Opus.

## Hardware & hosting

Runs on **streaming-pc** (Windows + WSL2 Ubuntu 24.04). User RDPs into the box to develop:
- Ryzen 7 5700X, RTX 3060 Ti **8 GB VRAM**, 16 GB RAM
- C: drive ~167 GB free of 954 GB at project start; cleanup in progress to reach ~75 GB free
- Secondary SSD purchased but not yet installed — runtime data lives on `/mnt/c/ConnectClips-data/` for now; move to `/mnt/d/ConnectClips-data/` once SSD is in. Path is env-configurable in backend.
- **Code + venv + node_modules live in the WSL2 ext4 filesystem** (`~/ConnectClips/`), NOT under `/mnt/c/`. DrvFs is too slow for Python venvs and Node installs. Model weights cache (`~/.cache/huggingface`) also stays in WSL2 ext4.
- CUDA reaches WSL2 via the Windows NVIDIA driver — no separate CUDA toolkit install needed. PyTorch and faster-whisper ship their own CUDA libs via pip.
- Behind a UniFi network the user administers; web UI exposed via **Tailscale on the Windows side** (WSL2 reaches the LAN through it). No auth in v1 — Tailscale is the gate.

## Source material

Production switcher is a **Blackmagic ATEM Extreme ISO**. Two possible source modes — design ingest to handle both:
1. **Program feed with picture-in-picture** (current livestream output) — fallback, bad for vertical clips because of the PiP composite.
2. **Per-camera ISO recordings** to USB-C SSD (target state) — clean per-camera feeds, much better source material. Volunteers will need to pick a camera angle per clip.

## Stack (decided)

- **Backend**: Python 3.12 + FastAPI, simple async task queue (no Celery/Redis in v1)
- **Transcription**: `faster-whisper` large-v3 in int8 (~3 GB VRAM), word-level timestamps
- **Clip selection**: Claude API, model `claude-sonnet-4-6`. Send transcript with timestamps, ask for N candidate clips (start, end, hook title, rationale). Use prompt caching on the system prompt.
- **Reframing**: MediaPipe face detection driving a smoothed crop window for 9:16 output
- **Cuts + encode**: FFmpeg with NVENC (h264_nvenc) for hardware-accelerated export
- **Captions**: ASS subtitles generated from Whisper word timings, karaoke-highlight style, burned in by FFmpeg. `captacity` is a reference implementation worth borrowing from.
- **Frontend**: Vite + React, single page. Flow: select sermon → see Claude's suggested clips → preview/trim/approve → export.

## Repo layout

```
~/ConnectClips/                # code (WSL2 ext4) — this repo
├── backend/                   # FastAPI app
├── frontend/                  # Vite + React
├── scripts/                   # one-off utilities, ingest helpers
└── CLAUDE.md

/mnt/c/ConnectClips-data/      # runtime data (temporary — moves to /mnt/d/ once SSD installed)
├── sources/                   # raw sermon files (delete after export)
├── work/                      # transcripts, intermediate artifacts
└── clips/                     # exported clips
```

Path split is configured via backend env vars, not hardcoded. Model weights cache (`~/.cache/huggingface`) stays in WSL2 ext4 for speed. Never put venv, model weights, or working data under OneDrive — sync churn will break things.

## Conventions

- Don't assume a single source video file — the volunteer may have multiple camera angles per sermon.
- Keep the volunteer UI minimal. Every extra control is a support question.
- For a prototype, hardcode reasonable defaults (clip length 30-90s, 3-8 candidate clips per sermon, vertical 1080x1920) and expose them later only if asked.
- Background jobs are fine to be simple in-process asyncio for v1. Don't over-engineer.

## Open questions

- Will volunteers run this from their own laptops via browser (Tailscale), or sit at the streaming PC's touch screen? Both work; UI sizing depends on the answer.
