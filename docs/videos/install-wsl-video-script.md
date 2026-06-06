# ConnectClips — WSL2 / NVIDIA install video script

**Target length: 10-12 min finished video.** Real-world install takes ~25-40 min wall-clock; you'll fast-forward through three download / build segments (apt + node + ffmpeg, pip CUDA wheels, frontend build).

**Audience:** Someone with a Windows 10/11 PC that already has an NVIDIA GPU (8 GB+ VRAM), WSL2 enabled, and a working Ubuntu 24.04 distro. They've installed the NVIDIA Game Ready or Studio driver on the Windows side, but they have nothing else set up. Tech-comfortable but not a developer.

This is the **Linux/NVIDIA path**. If your hardware is AMD or Intel, watch the Windows-native install video instead — totally different script, different deployment shape.

**Recording setup:**
- Record at 1080p or 1440p. Plan to switch between an Ubuntu shell and a PowerShell window — at least once for the WSL idle-timeout config, once for Task Scheduler, once for Tailscale.
- Use a freshly-imported Ubuntu 24.04 distro for recording. There's a "fresh WSL" recipe in `docs/DEPLOYING-wsl.md` that gets you a clean environment without disturbing your dev distro.
- Have your Anthropic API key, an admin password, and the church's Tailscale account ready off-camera.
- Verify the Windows-side NVIDIA driver is current before recording — the install script's CUDA passthrough check is the first thing that can fail and embarrass you on camera.

---

## Scene 1 — Cold open / hook (0:00 - 0:30)

**ACTION:** Title card "ConnectClips — WSL + NVIDIA install" over a still of the ConnectClips home page (`01-sermon-list.png`).

**SAY:**
> "This video walks you through installing ConnectClips on a Windows 11 PC that has an NVIDIA GPU. We'll be working inside a Linux environment called WSL — Windows Subsystem for Linux — because the NVIDIA tooling for AI transcription works better there than on Windows directly. Total time is about 30-40 minutes; only 5 minutes of that is hands-on, the rest is downloads. By the end you'll have ConnectClips running automatically every time the PC boots, reachable from anywhere on your tailnet."

---

## Scene 2 — Prerequisites (0:30 - 1:30)

**ACTION:** Cut to a slide / on-screen list while you talk.

**SAY:**
> "Before you start, make sure four things are true:
>
> One — your Windows PC has an NVIDIA GPU with at least 8 gigabytes of VRAM. An RTX 3060 Ti or better is what we test on.
>
> Two — the NVIDIA Game Ready or Studio driver is installed and current on the Windows side. CUDA is going to pass through to Linux from this driver — there's no separate CUDA install. If you're not sure how recent yours is, open GeForce Experience and let it update before you start.
>
> Three — WSL2 is enabled and you have an Ubuntu 24.04 distribution running. There's a separate one-page guide in the repo for getting WSL set up if you don't have it yet — link below.
>
> Four — your Anthropic API key, an admin password you'll choose now, and a Tailscale account ready. The walkthrough for getting an Anthropic key is also linked in the description."

---

## Scene 3 — Open Ubuntu, confirm it sees the GPU (1:30 - 2:30)

**ACTION:** Open the Ubuntu shell. At the prompt, run:
```bash
lsb_release -a
nvidia-smi
```

**SAY:**
> "Open your Ubuntu terminal — Start menu, type Ubuntu, hit Enter. You should be at a normal shell prompt as your user, not root.
>
> Quick sanity check: run `lsb_release -a` to confirm you're on Ubuntu 24.04. Then run `nvidia-smi`. If you get a table showing your GPU's name and driver version, the CUDA passthrough is working — that's everything you need from the Windows side. If `nvidia-smi` says 'command not found' or 'driver not loaded,' update the NVIDIA driver on the Windows side and try again. The install won't proceed without this."

**ACTION:** Confirm `nvidia-smi` shows the GPU. Brief "perfect" reaction beat.

---

## Scene 4 — Run the bootstrap one-liner (2:30 - 3:30)

**ACTION:** Inside the Ubuntu shell, paste:
```bash
curl -fsSL https://raw.githubusercontent.com/connect-community-church/connectclips/main/scripts/bootstrap.sh | bash
```

Press Enter.

**SAY:**
> "Now paste this one command. I'll put it in the video description below — you don't have to type it. This downloads our bootstrap script and runs it. The bootstrap installs git if it isn't already on the box, clones the ConnectClips repo to your home directory under `~/ConnectClips`, and then hands off to the main install script."

**ACTION:** Show the bootstrap output: `[bootstrap] detected: Linux (WSL2)`, `[bootstrap] using git: …`, `[bootstrap] cloning into /home/<user>/ConnectClips`, then the handoff to `install-wsl.sh`.

**SAY:**
> "If git wasn't already installed, the bootstrap pulls it via apt — that's about a thirty-second sub-step the first time. Then it clones the repo and immediately starts the main install script.
>
> The install script does eleven steps end-to-end. It'll prompt you for your sudo password once near the start — that's so it can install system packages and configure the systemd service that runs ConnectClips at boot."

**ACTION:** Show the prompt for the sudo password. Type it (off-camera or blurred). Show the script entering step 1.

**SAY:**
> "Once you give it your password, you can walk away for the next chunk."

---

## Scene 5 — Watch the install run (3:30 - 5:30)

**ACTION:** Show step headers as the install runs:
- `[1/11] APT packages`
- `[2/11] ffmpeg NVENC encoder`
- `[3/11] CUDA passthrough (nvidia-smi)`
- `[4/11] Node.js`

**SAY:**
> "The first step grabs apt packages — Python 3.12, ffmpeg, yt-dlp, a few build tools.
>
> Step two is the encoder check. If your apt-installed ffmpeg already has NVENC compiled in, you're done in a second. If it doesn't, the script downloads a static ffmpeg build that does, and drops it into the right place automatically. No interaction needed.
>
> Step three runs `nvidia-smi` again as a final safety check that CUDA is reachable from inside Linux.
>
> Step four installs Node.js, which is what builds the web interface."

**[FAST-FORWARD CUE]** Speed up to 6x or cut to a "system packages, ~3 minutes" overlay.

**ACTION:** Show step 5 — `[5/11] Backend venv + pip install`. Show the warning about the CUDA wheels download.

**SAY:**
> "Step five is the big download. The Python AI libraries plus their CUDA wheels are about 2 gigabytes. On a slow connection this is 10-15 minutes."

**[FAST-FORWARD CUE]** Heavy speed-up over the pip install. Show a progress indicator climbing.

---

## Scene 6 — The face-detection model + data dirs (5:30 - 6:00)

**ACTION:** Step 6 — `[6/11] YuNet face detector` (small, ~228 KB). Step 7 — `[7/11] Data directories`.

**SAY:**
> "Step six grabs the small face-detection model — a couple hundred kilobytes. Step seven creates the folders where your sermon files, transcripts, and exported clips will live. By default that's a folder under `C:\ConnectClips-data` on your Windows drive, so you can easily back it up or copy clips off to another machine."

---

## Scene 7 — Enter the secrets (6:00 - 7:00)

**ACTION:** Script reaches step 8, which writes `backend/.env`. It pauses at the API key prompt. Type the key (off-camera or blurred). Press Enter. Then the admin password prompt — type it (also blurred). Press Enter.

**SAY:**
> "Step eight writes the configuration file. The script will pause for two prompts.
>
> First, paste your Anthropic API key — the one that starts with `sk-ant-`. The screen won't echo what you type — that's intentional, like a Linux password prompt. Press Enter when you're done.
>
> Second, choose your admin password. This is what you'll use later to access admin features in the app. Same deal — invisible as you type, press Enter to confirm.
>
> Note: if you skip these prompts by pressing Enter, the script will leave placeholders in the env file and you can edit them later. But you can't actually use the app until those values are set."

---

## Scene 8 — Frontend build + smoke test + service install (7:00 - 8:30)

**ACTION:** Step 9 — npm install + build (3-5 min). Step 10 — smoke test (uvicorn briefly starts, hits /api/health, shuts down). Step 11 — systemd unit install + enable.

**SAY:**
> "Step nine builds the user interface — npm install, then a Vite build. Another fast-forward."

**[FAST-FORWARD CUE]** ~3-5 min of npm install + build output.

**SAY:**
> "Step ten is a smoke test — the script briefly starts the backend, hits the health endpoint, and shuts it back down. If you see 'health 200 OK' you're good.
>
> Step eleven installs the systemd service inside WSL. That's what keeps ConnectClips running. Whenever WSL is up, the service is up. The very last thing you should see is 'connectclips.service: active' in green."

**ACTION:** Show "Install complete. Open http://localhost:8765/" and the systemd status.

---

## Scene 9 — Verify in the browser (8:30 - 9:00)

**ACTION:** Open a browser on Windows, type `http://localhost:8765`. The ConnectClips home page loads.

**SAY:**
> "Open a browser on Windows — yes, just regular Chrome or Edge — and go to localhost colon eight-seven-six-five. WSL forwards that port to Windows automatically. You should see the ConnectClips banner and an empty sermon list."

---

## Scene 10 — Make WSL stay alive across reboots (9:00 - 10:30)

**ACTION:** Switch to a PowerShell window. Show two things:

**Part A — `.wslconfig`:**
```powershell
notepad $env:USERPROFILE\.wslconfig
```

In notepad, ensure the file contains:
```ini
[wsl2]
vmIdleTimeout=-1
```

**SAY:**
> "ConnectClips is now running inside Linux, but Windows by default shuts down WSL after about 60 seconds of idle. We need to disable that, otherwise the service stops every time you stop using the box.
>
> Open Notepad and create or edit the file `.wslconfig` in your Windows user profile. Add a `[wsl2]` section with `vmIdleTimeout` equals minus one. Save. Then in PowerShell run `wsl --shutdown` to force WSL to reload that config the next time it starts."

**Part B — Task Scheduler:**

**ACTION:** Open Task Scheduler. Walk through creating a task that runs `wsl.exe -d Ubuntu-24.04 --exec /bin/true` at startup. Briefly cover the New Task dialog: name, trigger "At startup," action that command, run whether logged in or not.

**SAY:**
> "And one more piece. WSL doesn't automatically start when the Windows PC boots. We need a Task Scheduler entry that pokes WSL on startup so the systemd service inside it kicks in.
>
> Open Task Scheduler. Create a new task — not 'Basic Task,' the full one. Give it a name, set 'Run whether user is logged on or not.' Add a trigger 'At startup.' Add an action that runs `wsl.exe -d Ubuntu-24.04 --exec /bin/true` — that's a no-op command whose only job is to wake WSL up. Save the task; it'll prompt for the user password.
>
> Combined with the `vmIdleTimeout=-1` we just set, this means: at boot, Task Scheduler wakes WSL, systemd starts ConnectClips, and the WSL VM never idles out. Service stays running until you reboot or `wsl --shutdown`."

---

## Scene 11 — Tailscale for remote access (10:30 - 11:30)

**ACTION:** Install Tailscale on the Windows side via winget (in PowerShell):
```powershell
winget install --id tailscale.tailscale
```

**SAY:**
> "Last big thing. To make ConnectClips reachable from volunteers' laptops and phones, install Tailscale on Windows. Tailscale creates a private network just between your devices. Free tier is plenty."

**ACTION:** Open the Tailscale tray icon, sign in with the church account.

**ACTION:** Then in PowerShell:
```powershell
tailscale serve --bg --https=443 http://localhost:8765
tailscale serve status
```

**SAY:**
> "After signing in, run `tailscale serve --bg --https=443 http://localhost:8765`. That tells Tailscale to expose ConnectClips at a private HTTPS URL. Then `tailscale serve status` to confirm — you'll see a URL ending in `.ts.net`. That's what you send your volunteers."

---

## Scene 12 — Optional: configure publish targets (11:30 - 11:45)

**ACTION:** Open the Tailscale URL on a phone or laptop, click into admin mode (it auto-engages on a tailnet user), open **Settings**.

**SAY:**
> "If you click into Settings as admin, there are two fields for your YouTube channel ID and your Facebook Page ID. Filling these in makes the publish buttons in the app deep-link straight to the right account, so volunteers don't accidentally cross-post to their personal channels. Page itself has links explaining where to find each ID. You can do this now or later."

---

## Scene 13 — Wrap (11:45 - 12:00)

**ACTION:** Cut back to the home page or a closing card.

**SAY:**
> "That's the WSL plus NVIDIA install. Next videos: the operator workflow — how a volunteer turns a sermon into clips — and how to add Tailscale users so volunteers can actually open the app. If anything went wrong, every step the install script ran is also documented in `docs/DEPLOYING-wsl.md` with troubleshooting for common issues. Thanks for watching."

---

## Production notes

- Total runtime budget: 10-12 min finished.
- Three FAST-FORWARD cues (apt + node + ffmpeg, pip CUDA wheels, npm install + build) compress ~25 min of real time into ~30 sec of finished video.
- Hide the Anthropic API key + admin password during the prompt scenes — type off-camera and cut back, or blur in post.
- Keep the test machine's data directory empty before recording so the home page shows no sermons (matches `01-sermon-list.png`).
- Keep your existing dev WSL distro out of frame. Recording in a freshly imported `UbuntuVideo` distro (per `docs/DEPLOYING-wsl.md`) avoids accidental "wait, my system already has ConnectClips installed" moments.
- The Task Scheduler scene is fiddly to record cleanly. Consider doing a separate cleaner take of just that, then cutting it in. Don't worry if your full task creation flow takes 2-3 minutes in real time — you only need to show the *result*: the task exists and runs at startup. A 20-second cut is fine.
- For the `tailscale serve` scene, blur your tailnet name (the `.ts.net` URL) if you don't want it broadly indexed, even though Tailscale itself gates access.
- End-of-video CTA: link to `docs/DEPLOYING-wsl.md` for manual / troubleshooting and to the operator workflow video for the next steps.
