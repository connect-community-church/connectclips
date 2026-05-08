# ConnectClips — Install video script

**Target length: 10-12 min finished video.** Real-world install takes ~30 min wall-clock; you'll fast-forward through three download / build segments.

**Audience:** Mike or another tech-comfortable person setting up a fresh Windows 11 box for ConnectClips. Assumes basic Windows / PowerShell familiarity but nothing more.

**Recording setup:**
- Record at 1080p or 1440p, browser + PowerShell windows side by side or full-screen with brief switches.
- Use a fresh Windows 11 box if possible (or roll back the Bosgame for the recording, then restore).
- Have your Anthropic API key, admin password, and church Tailscale account ready off-camera.

---

## Scene 1 — Cold open / hook (0:00 - 0:30)

**ACTION:** Title card "ConnectClips — Windows install" over a still of the ConnectClips home page (`01-sermon-list.png`).

**SAY:**
> "This video walks you through installing ConnectClips on a Windows 11 PC end-to-end. It's about 30 minutes of total time, but only 5 minutes of it is hands-on — the rest is downloads. I'll fast-forward those parts. By the end you'll have a Windows Service running ConnectClips, reachable from any volunteer's laptop or phone over Tailscale."

---

## Scene 2 — What you need before starting (0:30 - 1:30)

**ACTION:** Cut to a slide / on-screen list while you talk.

**SAY:**
> "Before you start, gather four things:
>
> One — a Windows 11 PC. Doesn't have to be powerful. The box I tested on is a small Bosgame mini-PC with an AMD Ryzen 9 and a built-in Radeon GPU. About $400. Any AMD or Intel GPU will do, even integrated graphics.
>
> Two — your Anthropic API key. If you haven't set one up yet, there's a separate walkthrough linked in the GitHub readme — takes about ten minutes including funding the account with five bucks.
>
> Three — an admin password you'll use to manage the app. Pick something now; you'll be prompted for it in a couple of minutes.
>
> Four — about 10 gigabytes of free disk space. The install pulls Python, Node, ffmpeg, and a 1.5 gigabyte AI model.
>
> Optional but recommended: a Tailscale account. We'll set that up at the end so volunteers can access the app from their own laptops without exposing anything to the public internet."

---

## Scene 3 — Open elevated PowerShell + run the bootstrap (1:30 - 3:00)

**ACTION:**
- Right-click the PowerShell icon → **Run as administrator**. Click Yes on UAC.
- Paste:
  ```
  irm https://raw.githubusercontent.com/connect-community-church/connectclips/main/scripts/bootstrap.ps1 | iex
  ```
- Press Enter.

**SAY:**
> "Open PowerShell as Administrator — right-click and pick 'Run as administrator'. The whole install needs admin rights for the Windows Service step at the end, so we just elevate now and stay there.
>
> Then paste this one command. I'll put it in the video description below — you don't have to type it. This downloads our bootstrap script and runs it. The bootstrap installs git if it isn't already on the box, clones the ConnectClips repo to C:\\ConnectClips, and then chains into the main install script."

**ACTION:** Show the bootstrap output: "[bootstrap] using git: ...", "[bootstrap] cloning into C:\ConnectClips", then handing off.

**SAY:**
> "If git wasn't installed, the bootstrap pulls it via winget — that's about a thirty-second sub-step the first time. Then it clones the repo and immediately starts the main install script."

---

## Scene 4 — Watch the install run (3:00 - 5:00)

**ACTION:** Show step headers as the install script runs — `[1/11] Tooling via winget`, downloads beginning.

**SAY:**
> "The main install script runs eleven steps. The first one uses winget to install Python 3.12, Node.js, ffmpeg, and NSSM — a tool that wraps Python applications as proper Windows Services. Each install will pop a UAC prompt, click Yes on each one."

**[FAST-FORWARD CUE]** Speed up to 4x or cut to a "winget downloads, ~5 minutes" overlay until step 1 finishes.

**ACTION:** Show step 2 — `[2/11] Hardware accelerator probe`.

**SAY:**
> "Step two probes for hardware accelerators. On this AMD box, it confirms `h264_amf` is available, which means hardware video encoding is going to work. Different machine, different message — Intel boxes will say h264_qsv. NVIDIA boxes won't see this script; they use the Linux/WSL deployment path instead."

**ACTION:** Step 3, venv creation, then pip install.

**SAY:**
> "Step three creates the Python environment for the backend and installs the dependencies. Few hundred megabytes of downloads. Fast-forward through this."

**[FAST-FORWARD CUE]** ~3-5 minutes of pip output. Speed to 8x.

---

## Scene 5 — The bundle download (5:00 - 6:30)

**ACTION:** Step 5 — `[5/11] whisper-cli (Vulkan whisper.cpp) bundle`. Then the model download (1.5 GB, several minutes).

**SAY:**
> "Step five is the big one. The script downloads our pre-built whisper-cli binary — that's the AI model that does transcription — plus the model weights, which is about 1.5 gigabytes. On a slow connection this can take 10-15 minutes. Fast-forward."

**[FAST-FORWARD CUE]** Heavy speed-up over the model download. Show a progress bar climbing.

**ACTION:** Steps 6-7 finish quickly (data dirs, env file).

**SAY:**
> "Steps six and seven are quick — making the data directories and writing the configuration file."

---

## Scene 6 — Enter the secrets (6:30 - 7:30)

**ACTION:** Script pauses at the API key prompt. Type the key (off-camera or blurred). Press Enter. Then the admin password prompt — type it (also blurred). Press Enter.

**SAY:**
> "The script pauses here for two prompts. First, paste your Anthropic API key — the one that starts with `sk-ant-`. The screen won't show anything as you type — that's intentional, like a Linux password prompt. Press Enter when you're done.
>
> Second, choose your admin password. This is what you'll use later to access admin features in the app. Same deal — invisible as you type."

---

## Scene 7 — Frontend build + service install (7:30 - 9:00)

**ACTION:** Step 8 — npm install + build (3-5 min). Step 9 — smoke test (uvicorn briefly starts, hits /api/health, shuts down). Step 10 — NSSM install.

**SAY:**
> "Step eight builds the user interface — npm install, then the build. Another fast-forward.
>
> Step nine is a smoke test — the script briefly starts the backend, confirms it answers, and shuts it down. If you see 'health 200 OK,' you're good.
>
> Step ten installs the Windows Service through NSSM. Now the app will run automatically every time the computer boots. No login required."

**ACTION:** Show "[11/11] All done" and the service status.

**SAY:**
> "Step eleven is the wrap-up. You should see 'ConnectClips service: Running' in green. That's it for the install."

---

## Scene 8 — Verify in the browser (9:00 - 9:45)

**ACTION:** Open a browser, type `http://localhost:8765`. The ConnectClips home page loads.

**SAY:**
> "Open a browser, go to localhost colon eight-seven-six-five — that's the port ConnectClips runs on by default. You should see the ConnectClips banner and an empty sermon list. The app is now running and will keep running across restarts of this machine."

---

## Scene 9 — Tailscale for remote access (9:45 - 11:00)

**ACTION:** In PowerShell, type:
```
winget install --id tailscale.tailscale
```

**SAY:**
> "Now to make the app reachable from volunteers' laptops and phones, we use Tailscale. It's a free service that creates a private network just between your devices. Install Tailscale via winget."

**ACTION:** Open the Tailscale tray icon, sign in. Then in PowerShell:
```
tailscale serve --bg --https=443 http://localhost:8765
```

**SAY:**
> "Open the Tailscale tray icon and sign in with the church account.
>
> Then back in PowerShell, run `tailscale serve --bg --https=443 http://localhost:8765`. That tells Tailscale to expose ConnectClips at a private HTTPS URL."

**ACTION:** Run `tailscale serve status` and show the URL.

**SAY:**
> "Run `tailscale serve status` to confirm — you'll see a URL ending in `.ts.net`. That's what you send your volunteers. Anyone with access to your Tailscale network can open that URL and use ConnectClips. Anyone without access to your network can't see it at all."

---

## Scene 10 — Optional: configure publish targets (11:00 - 11:30)

**ACTION:** Open the URL, click into admin mode (the prompt or auto-admin engages). Click **Settings**.

**SAY:**
> "One last optional step. If you click into admin mode and open Settings, there are two fields for your YouTube channel ID and your Facebook Page ID. Filling these in makes the publish buttons in the app deep-link straight to the right account, so volunteers don't accidentally cross-post to their personal channels. The page itself has links to where you find each ID. You can do this now or later."

---

## Scene 11 — Wrap (11:30 - 12:00)

**ACTION:** Cut back to home page or a closing card.

**SAY:**
> "That's it. Your ConnectClips install is up and running. To add a volunteer, share the streaming-pc with their email from your Tailscale admin console — there's a separate walkthrough for that. To use the app, watch the operator video.
>
> If anything goes wrong, every step the install script just ran is also documented in `docs/DEPLOYING-windows.md` in the repository, so you can do it manually or troubleshoot a single step. Thanks for watching."

---

## Production notes

- Total runtime budget: 10-12 min finished.
- Three FAST-FORWARD cues (winget, pip install, model download) trim ~25 min of real time into ~30 sec of finished video.
- Hide the Anthropic API key + admin password during the prompt scenes — either type off-camera and cut back, or use a blur in post.
- Keep the test machine's data directory empty before recording so the home page shows no sermons (matches `01-sermon-list.png`).
