# Getting an Anthropic API key

ConnectClips uses Claude (Anthropic's model) for the clip-selection step
of the pipeline — Whisper produces the transcript locally, and Claude
reads it to pick the 7-10 hook moments that become candidate clips.
You'll need an Anthropic API key for this to work.

The whole sign-up + key-creation flow takes about 5 minutes if you're
already logged in to a payment method.

## 1. Create the account

Go to [console.anthropic.com](https://console.anthropic.com) and click
**Sign up**. Three things worth doing on the way in:

- **Use a church-owned email**, something like `media@yourchurch.org`,
  not a personal Gmail. This avoids the "what happens when the
  volunteer leaves" succession problem.
- When prompted for organization type, **pick "Workspace"** (or whatever
  the team-billing option is currently called). Solo accounts work too
  but make accounting harder — a workspace lets multiple people manage
  the same billing without sharing a login.
- Verify your email and **enroll in MFA** when offered. Non-technical
  users sometimes skip MFA and regret it later when a key gets exposed
  and they need to rotate it without a recovery flow.

## 2. Add billing

Settings → Billing → **Add payment method**. Three things to know that
demystify the experience:

- **It's prepaid credits, not a subscription.** You add (say) $10 to your
  balance, and API calls draw from it. There's no surprise monthly
  charge — when you run out, calls fail until you top up. The current
  balance always shows in the console.
- **Set a budget alert.** Settings → Limits → Spend limit. For a single
  Sunday-morning church running ConnectClips, **$20/month** is roughly
  10× what you'll actually use, and the alert protects you against
  runaway costs from a misconfigured loop.
- **Realistic cost expectation:** A typical 50-minute sermon costs
  about **15-30 cents** to process through Claude. The audio
  transcription happens locally on your hardware (free); the only paid
  step is the clip selection. You'll spend more on coffee for the
  volunteer than on Claude.

If your church is a registered non-profit, it's worth a 5-minute support
email to `support@anthropic.com` asking about non-profit / educational
pricing — Anthropic has periodically had startup credit programs and
similar discounts.

## 3. Generate the key

Settings → API Keys → **Create Key**.

- **Name it descriptively**: something like `connectclips-streaming-pc`.
  When you eventually rotate keys, you want to know which one
  ConnectClips is using.
- **The key shows once.** Copy it immediately to the church's password
  manager (1Password, Bitwarden, etc.) before navigating away. If you
  lose it, you generate a new one and update the config — minor
  friction, no data loss.
- **Never paste the key into Slack, email, GitHub, screenshots, or
  chat with an AI assistant.** Anthropic auto-revokes keys posted to
  obvious public places and may flag keys that show up in less obvious
  ones. A leaked key means scrambling on a Sunday afternoon to issue a
  new one.

## 4. Paste it into ConnectClips

If you used the install script (`scripts/install-mac.sh` or
`scripts/install-wsl.sh`), it'll prompt:

```
Enter your Anthropic API key (sk-ant-...):
```

Paste the key and press Enter. **Nothing will appear on screen as you
type or paste** — that's not a bug, the script is hiding it for security
the same way `sudo` hides your password.

If you're configuring `backend/.env` manually, the line looks like:

```ini
ANTHROPIC_API_KEY=sk-ant-api03-...
```

Make sure the file's permissions are tight (`chmod 600 backend/.env`) so
other users on the machine can't read it.

## What if it stops working?

The most common failure is `AuthenticationError: 401 invalid x-api-key`
when the clip-selection step runs. Three causes, in order of frequency:

1. **The key was rotated or deleted in the console.** Check
   [console.anthropic.com](https://console.anthropic.com) → Settings →
   API Keys; if your key is missing or marked Disabled, generate a new
   one and update `.env`.
2. **The workspace ran out of credit.** Check the billing page; top up
   if the balance is at $0.
3. **Datacenter / cloud IP block.** If you're running ConnectClips on
   a rented cloud Mac (rentamac.io, MacStadium, etc.), Anthropic's
   abuse heuristics sometimes flag those IP ranges as untrusted. The
   same key works fine from a residential / business ISP. Either move
   the install on-premises or email
   [support@anthropic.com](mailto:support@anthropic.com) to whitelist
   the rental's IP.

After updating `.env`, restart the backend so the new key is picked up:

- **Linux/WSL:** `sudo systemctl restart connectclips.service`
- **macOS:** `launchctl unload ~/Library/LaunchAgents/com.connectclips.plist && launchctl load ~/Library/LaunchAgents/com.connectclips.plist`
