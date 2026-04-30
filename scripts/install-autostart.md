# Auto-start ConnectClips on Windows boot

The backend serves both the API and the built SPA on `0.0.0.0:8765`. We want it up automatically when the streaming PC boots, with no logged-in user required (Tailscale Serve on the Windows side reaches it via localhost).

## Architecture

Three pieces, in three places:

1. **`connectclips.service`** (systemd, inside WSL) — runs uvicorn. This is the actual server.
2. **`ConnectClips-StartWSL`** (Windows Task Scheduler) — boot trigger that runs `wsl.exe -d Ubuntu --exec /bin/true`. Its only job is to nudge the WSL VM into booting; once systemd is up, it takes over.
3. **`vmIdleTimeout=-1`** in `C:\Users\<you>\.wslconfig` — load-bearing. Without it, WSL2 shuts the VM down ~60s after the trip-wire's `/bin/true` exits (no Windows-side handle holding it open) and the systemd services die with it.

`scripts/start-server.sh` is **not** part of the boot path. It exists as a manual helper for ad-hoc runs.

### Why not just run the script from Task Scheduler

That was the original plan and it doesn't survive the no-logged-in-user case: once `wsl.exe ... bash -lc './scripts/start-server.sh'` returns, there is no Windows-side handle and the VM idle-shuts-down regardless of what's running inside Linux. Running uvicorn under systemd plus disabling `vmIdleTimeout` is the simplest way to make autostart genuinely unattended.

## One-time setup

### 1. Confirm WSL is set up for systemd

In WSL:

```bash
cat /etc/wsl.conf
```

Should contain:

```
[boot]
systemd=true
```

If not, add it and `wsl.exe --shutdown` from PowerShell to reload.

### 2. Build the SPA

In WSL:

```bash
cd ~/ConnectClips/frontend
npm run build
```

Drops the bundle in `~/ConnectClips/frontend/dist`, served by the backend at `/`.

### 3. Install the systemd units

`/etc/systemd/system/connectclips.service`:

```ini
[Unit]
Description=ConnectClips backend (FastAPI/uvicorn)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=connectadmin
Group=connectadmin
WorkingDirectory=/home/connectadmin/ConnectClips/backend
ExecStart=/home/connectadmin/ConnectClips/backend/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8765 --log-level warning
Restart=on-failure
RestartSec=5
Environment=HOME=/home/connectadmin
Environment=PATH=/home/connectadmin/ConnectClips/backend/.venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/wsl-anchor.service` (defense in depth — keeps systemd non-idle inside WSL):

```ini
[Unit]
Description=Anchor to keep WSL running
After=multi-user.target

[Service]
Type=simple
ExecStart=/bin/sleep infinity
Restart=always

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now connectclips.service wsl-anchor.service
```

### 4. Set `vmIdleTimeout` in `.wslconfig`

Edit `C:\Users\<you>\.wslconfig` and add `vmIdleTimeout=-1` under `[wsl2]`:

```
[wsl2]
networkingMode=mirrored
dnsTunneling=true
autoProxy=true
vmIdleTimeout=-1
```

`.wslconfig` is read at the next WSL boot. You can edit it without disturbing the running session; it'll apply after the next `wsl.exe --shutdown` or Windows reboot.

### 5. Create the Task Scheduler entry

Open **Task Scheduler** → *Create Task…* (not "Basic Task").

**General**
- Name: `ConnectClips-StartWSL`
- Run whether user is logged on or not.
- Configure for: Windows 10 / 11.

**Triggers** → *New…*
- Begin the task: **At startup**.

**Actions** → *New…*
- Action: **Start a program**
- Program/script: `C:\Windows\System32\wsl.exe`
- Add arguments: `-d Ubuntu --exec /bin/true`
  (substitute your distro name from `wsl -l -v` if not `Ubuntu`)

**Conditions**
- Uncheck *Start the task only if the computer is on AC power*.

**Settings**
- Check *Allow task to be run on demand*.
- *Start the task only if the network connection is available*: leave unchecked (Tailscale comes up later anyway).

Save.

### 6. Test without rebooting

```powershell
# Windows side
wsl --shutdown
# wait a few seconds, then:
Start-ScheduledTask -TaskName 'ConnectClips-StartWSL'
Start-Sleep 10
curl http://localhost:8765/api/health
```

Should return `{"status":"ok",...}`. After two more minutes, `wsl -l -v` should still show the distro `Running` — that proves `vmIdleTimeout=-1` is in effect.

### 7. Tailscale Serve persistence

`tailscale serve --bg ...` rules persist across reboots — Tailscale restores them on its own. No Task Scheduler entry needed for that.

## Updating the app later

After pulling code or changing the frontend:

```bash
cd ~/ConnectClips
git pull
cd frontend && npm run build
sudo systemctl restart connectclips.service
```

Or just reboot — systemd will pick it up.

## Troubleshooting

- **`/api/health` 404s but `/` serves HTML**: backend started before the SPA build completed, or the API import failed. Check `journalctl -u connectclips.service -n 100`.
- **Page loads but admin login 503s**: `ADMIN_PASSWORD` is empty in `backend/.env`. Set it and `sudo systemctl restart connectclips.service`.
- **Page loads on streaming PC but not over Tailscale**: Windows firewall isn't open on 8765:
  ```powershell
  New-NetFirewallRule -DisplayName "ConnectClips (8765)" -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8765
  ```
- **Service runs for 2 minutes after boot, then everything dies**: classic missing-`vmIdleTimeout` symptom. Check `.wslconfig`, then `wsl --shutdown` and let the boot trigger fire again. Confirm with `journalctl --list-boots` — back-to-back short boots are the fingerprint.
- **Stale frontend after `npm run build`**: hard-refresh (Ctrl+Shift+R). Bundle is content-hashed but the browser may still hold an old `index.html`.
- **Task fired but WSL never came up**: in PowerShell, `Get-ScheduledTaskInfo -TaskName 'ConnectClips-StartWSL'` — `LastTaskResult` should be `0`. Anything else, check the History tab in Task Scheduler GUI.