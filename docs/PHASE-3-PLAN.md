# Phase 3 plan — AMD GPU + general CPU support

Working document. Will be deleted when Phase 3 lands on `main` as a squashed commit.
This file exists to carry context across Claude Code sessions and dev-environment
moves (e.g. switching from WSL2 dev to Windows-native dev mid-phase).

## Goal

Make ConnectClips deploy and run well on AMD-GPU and CPU-only hardware, in the
same shape Phase 2 delivered for Apple Silicon: a one-shot install script, a
deployment doc, and a working end-to-end pipeline on the target box.

## Target hardware (production presentation PC)

- Box: Bosgame EffiZen mini PC
- CPU: AMD Ryzen 9 6900HX, 8C / 16T
- GPU: Radeon 680M iGPU (RDNA2, ~3 GB shared VRAM)
- RAM: 32 GB
- OS: Windows 11 Pro 24H2 (build 26200), with WSL2 v2.6.3 + Ubuntu also installed
- Disk: C: 951 GB total, 727 GB free
- Role: drives the projector and Presenter by WorshipTools during services.
  ConnectClips must coexist with that workload, not fight it.

## Key architectural decision: native Windows is the primary path

WSL2 was the right answer for the original NVIDIA streaming PC because WSL2
exposes CUDA cleanly. WSL2 + an AMD iGPU is a different story:

| Acceleration path | WSL2 + 680M | Windows native + 680M |
|---|---|---|
| `h264_amf` ffmpeg encoder | not available (AMF runtime is Windows-only) | available |
| `DmlExecutionProvider` (DirectML) | not available (Windows user-space only) | available |
| `ROCMExecutionProvider` / ROCm faster-whisper | not supported on iGPU + WSL2 | not supported on iGPU |
| `whisper.cpp` Vulkan backend | works via /dev/dxg paravirt (~10–20% slower) | works natively |

Estimated end-to-end time for a 60-minute sermon: ~25–30 min on WSL2 (CPU encode)
vs. ~6–8 min on Windows native (AMF + DirectML + Vulkan). That gap is the
difference between volunteer-friendly and volunteer-hostile.

So Phase 3's primary deliverable is a **native Windows install**, with a
**WSL2 CPU-only fallback** added afterward for AMD boxes where Windows native
isn't an option.

## Design decisions

### Service-window gate (admin-configurable, schedule-based)

ConnectClips is CPU-heavy. On the production PC it must not run jobs while a
service is happening. The gate is **schedule-based**, not process-detection-based:

- Admin UI manages recurring weekly windows (e.g. Sun 09:00–12:30, Wed 18:30–21:00).
- Plus an ad-hoc "block all jobs from now" toggle for special events.
- Plus an admin-editable banner message shown to volunteers during a block.
- New jobs during a block: API returns 423 Locked + the message; UI shows a banner
  and disables the action.
- In-flight jobs continue to completion (killing them creates a worse problem).
- Default schedule is empty on NVIDIA / Apple Silicon installs; pre-populated
  with a sensible Sunday morning window on CPU-only / AMD installs.

Schedule beats detection because process names rebrand, multiple Presenter
editions exist, and admins can also block rehearsals / Wednesday services that
detection would miss.

### Auto-tune Whisper model at install time

`scripts/benchmark.sh` / `.ps1`:

- Bundled ~30 s test clip in `tests/fixtures/`.
- Try `large-v3` first; if RTR ≥ 1.5, done.
- Else try `medium`; if RTR ≥ 1.5, done.
- Else `small`. Floor here — `base`/`tiny` mistranscribe names and Bible
  references enough that volunteer adoption suffers.
- Writes the chosen model to `.env` as `WHISPER_MODEL`.
- Re-runnable later if hardware or drivers change.

Same script runs cross-platform; replaces the hand-tuned per-platform default.

### Backend changes (cross-platform)

- `backend/app/platform.py` — add Vulkan-availability detection (vulkaninfo
  + presence of /dev/dxg on Linux; vulkan-1.dll on Windows). Extend the auto
  whisper-backend dispatch: NVIDIA → faster-whisper, AMD-with-Vulkan → whispercpp,
  CPU-only → faster-whisper int8.
- `backend/requirements.txt` — pull NVIDIA CUDA wheels out and into install-wsl.sh
  only (currently they install on every Linux box, ~2 GB wasted on AMD/CPU).
- Service-window gate: persisted config + admin endpoints + UI.

### What is NOT in scope

- Calling Windows-side ffmpeg.exe across the WSL boundary to fake AMF in WSL2.
- ROCm bare-metal Linux variant.
- Process-detection of Presenter binaries.
- A WSL2-AMD path that pretends to use the GPU.

## Task list (live in TaskList; mirrored here for portability)

1. Probe Windows native dev environment (git, Python, Node, ffmpeg, VS Build Tools, Vulkan SDK)
2. Smoke-test whisper.cpp Vulkan on Radeon 680M, native Windows
3. Move NVIDIA CUDA wheels out of requirements.txt into install-wsl.sh
4. Add Vulkan / AMD detection + whisper backend dispatch in platform.py
5. Build admin-configurable service-window gate
6. Write `scripts/install-windows.ps1` (PowerShell port of install-mac.sh's structure)
7. Write `docs/DEPLOYING-windows.md`
8. End-to-end smoke test on Windows native (real sermon, real export, NSSM autostart)
9. WSL2 CPU-only fallback install + doc (blocked by 8)
10. Add auto-tune Whisper model benchmarker (cross-platform)
11. Squashed commit + PR for Phase 3

## Dev environment

Code lives at `C:\ConnectClips\` on the production PC for native-Windows dev.
The existing WSL2 clone at `~/ConnectClips/` stays in place — it's harmless and
will be used to build/test the WSL2 CPU fallback at the end.

VS Code on Windows opens `C:\ConnectClips\` directly (not via the WSL extension).
Integrated terminal is PowerShell. Claude Code is launched from that terminal so
its working directory is the Windows checkout.

## Resume marker

When restarting Claude Code in a new working directory, read this file plus
`CLAUDE.md` to pick up where the previous session left off. Then re-mirror
the task list above into the current TaskList.
