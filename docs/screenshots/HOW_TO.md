# Screenshot capture guide

The operator manual references 11 screenshots. The easiest way to refresh them is to run the included Playwright script (`capture_screens.py`), which drives the SPA through every state and saves the PNGs in the right place. Manual capture is also fine if you want to tweak a single shot.

## Automated capture (preferred)

```bash
# One-time setup if you don't already have a playwright venv
python3 -m venv /tmp/pw-venv
/tmp/pw-venv/bin/pip install playwright
/tmp/pw-venv/bin/playwright install chromium

# Capture all 11 screenshots
/tmp/pw-venv/bin/python docs/screenshots/capture_screens.py
```

Make sure the backend (port 8765) and the SPA build are both up before running. The script:

- Injects `Tailscale-User-Login: br8kpoint@gmail.com` and `Tailscale-User-Name: Michael Fair` headers so the identity badge and identity-based admin engage automatically (matches what you'd see hitting the app via Tailscale).
- Falls back to a separate browser context with no headers for the admin password-prompt shot, since that prompt only appears when there's no Tailscale identity.

## Manual capture tips

- Use a desktop browser at a normal window size (not full-screen or stretched).
- Crop to just the app's content area when possible (trim away your taskbar / browser chrome). Windows: Snipping Tool with `Win+Shift+S`. Mac: `Cmd+Shift+4`.
- Save as PNG (sharper for UI screenshots than JPEG).
- Don't capture any real personal data — the existing test sermon is fine.

## The 11 shots, in order

| File | What to capture |
|---|---|
| `01-sermon-list.png` | The home page — header at top with `Hi, *Name*` badge, Activity button, ADMIN MODE pill, "Add a sermon" panel below, and one or two existing sermons. |
| `02-add-from-youtube.png` | Just the "Add a sermon" panel, with a YouTube URL pasted into the input (any URL is fine — capture before clicking Download). |
| `03-sermon-detail.png` | Sermon detail view at the top — back button, sermon name, both pipeline steps visible (with the new Range controls). Use a sermon that's already transcribed and clipped so all badges are green. |
| `04-pick-clips.png` | Close-up of just Step 2 ("Pick clips") — Range inputs, ✓ N clips badge, Re-run button. |
| `05-clip-cards.png` | The list of clip cards under "Suggested clips" — three or four cards visible, with title, range, rationale, attribution line, and Preview/trim/export button. |
| `06-trim-view.png` | The full trim view — source video left, controls below (including the **caption-style picker dropdown**), output area right (empty is fine). |
| `07-export-preview.png` | Trim view after a successful export — exported clip preview on the right, Publish panel below. |
| `08-publish-panel.png` | Just the Publish panel — Download / Copy title / Copy full-sermon link buttons, four colored platform buttons. |
| `09-admin-prompt.png` | The header with the password input field showing (the fallback path — only visible without Tailscale identity). |
| `10-admin-active.png` | Sermon list view in admin mode — ADMIN MODE pill in header, red Delete buttons on every row. |
| `11-activity.png` | The Activity (admin-only) page with the table of recent jobs. Long-running jobs show a progress bar in the Status column. |

## Swapping a single shot

Save a new PNG over the old one with the same filename. The manual references images by relative path; nothing else needs to change.
