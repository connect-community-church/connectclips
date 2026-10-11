import { useEffect, useState } from 'react'
import { api } from '../api'
import type { AppSettings, ThinkingEffort } from '../types'

type Props = {
  onBack: () => void
}

// Per-deployment publish targets. Both fields optional -- if blank, the
// Publish view falls back to today's generic upload-page links (which work
// for whatever account is signed into that browser).
type Targets = {
  youtube_channel_id?: string
  facebook_page_id?: string
}

export function Settings({ onBack }: Props) {
  // --- Publish targets ---
  const [loaded, setLoaded] = useState(false)
  const [youtube, setYoutube] = useState('')
  const [facebook, setFacebook] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  // --- Clip selection ---
  const [csLoaded, setCsLoaded] = useState(false)
  const [effort, setEffort] = useState<ThinkingEffort>('medium')
  const [maxTokens, setMaxTokens] = useState(24000)
  const [clipsMin, setClipsMin] = useState(7)
  const [clipsMax, setClipsMax] = useState(10)
  const [csBusy, setCsBusy] = useState(false)
  const [csError, setCsError] = useState<string | null>(null)
  const [csSavedAt, setCsSavedAt] = useState<number | null>(null)

  useEffect(() => {
    api.getPublishTargets()
      .then((t: Targets) => {
        setYoutube(t.youtube_channel_id ?? '')
        setFacebook(t.facebook_page_id ?? '')
      })
      .catch((e) => setError(`Couldn't load: ${e}`))
      .finally(() => setLoaded(true))
  }, [])

  useEffect(() => {
    api.getAppSettings()
      .then((s: AppSettings) => {
        setEffort(s.clip_thinking_effort)
        setMaxTokens(s.clip_max_output_tokens)
        setClipsMin(s.num_clips_min)
        setClipsMax(s.num_clips_max)
      })
      .catch((e) => setCsError(`Couldn't load: ${e}`))
      .finally(() => setCsLoaded(true))
  }, [])

  const onSave = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.savePublishTargets({
        youtube_channel_id: youtube.trim() || undefined,
        facebook_page_id: facebook.trim() || undefined,
      })
      setSavedAt(Date.now())
      setTimeout(() => setSavedAt(null), 2500)
    } catch (e) {
      setError(`Save failed: ${e}`)
    } finally {
      setBusy(false)
    }
  }

  const onSaveClipSettings = async (e: React.FormEvent) => {
    e.preventDefault()
    setCsBusy(true)
    setCsError(null)
    try {
      // Server validates + clamps; reflect what it actually stored back into
      // the form so the user sees any coercion (e.g. min > max).
      const saved = await api.saveAppSettings({
        clip_thinking_effort: effort,
        clip_max_output_tokens: maxTokens,
        num_clips_min: clipsMin,
        num_clips_max: clipsMax,
      })
      setEffort(saved.clip_thinking_effort)
      setMaxTokens(saved.clip_max_output_tokens)
      setClipsMin(saved.num_clips_min)
      setClipsMax(saved.num_clips_max)
      setCsSavedAt(Date.now())
      setTimeout(() => setCsSavedAt(null), 2500)
    } catch (e) {
      setCsError(`Save failed: ${e}`)
    } finally {
      setCsBusy(false)
    }
  }

  if (!loaded || !csLoaded) {
    return <div className="muted" style={{ padding: 24 }}>Loading…</div>
  }

  return (
    <div className="settings-page">
      <button className="secondary" onClick={onBack}>← Back</button>

      <h2>Settings</h2>

      <form onSubmit={onSaveClipSettings} className="settings-form">
        <h3>Clip selection</h3>
        <p className="muted">
          Controls how Claude picks candidate clips from each sermon. Admin only —
          changes apply to the next Pick clips run.
        </p>

        <label>
          <span>Thinking effort</span>
          <select value={effort} onChange={(e) => setEffort(e.target.value as ThinkingEffort)}>
            <option value="low">Low — fastest &amp; cheapest</option>
            <option value="medium">Medium — balanced (recommended)</option>
            <option value="high">High — most thorough, slower &amp; pricier</option>
          </select>
          <small className="muted">
            The quality dial. Higher effort makes Claude reason harder about which
            moments will hook a cold viewer, at more cost and latency. Most sermons
            do well on Medium.
          </small>
        </label>

        <label>
          <span>Max output tokens</span>
          <input
            type="number"
            min={4000}
            max={64000}
            step={1000}
            value={maxTokens}
            onChange={(e) => setMaxTokens(Number(e.target.value))}
          />
          <small className="muted">
            Safety ceiling for the pick-clips call (covers thinking + the clip
            list). Raising it doesn't improve clips — it prevents the output from
            being cut off on long, dense sermons. Default 24000; if a pick ever
            fails with a truncation error, raise this. (Clamped to 4000–64000.)
          </small>
        </label>

        <div style={{ display: 'flex', gap: 16 }}>
          <label style={{ flex: 1 }}>
            <span>Clips — minimum</span>
            <input
              type="number" min={1} max={20} value={clipsMin}
              onChange={(e) => setClipsMin(Number(e.target.value))}
            />
          </label>
          <label style={{ flex: 1 }}>
            <span>Clips — maximum</span>
            <input
              type="number" min={1} max={20} value={clipsMax}
              onChange={(e) => setClipsMax(Number(e.target.value))}
            />
          </label>
        </div>
        <small className="muted">
          How many candidate clips the automatic pipeline requests. A manual
          Pick clips run can still override these per sermon.
        </small>

        <div className="settings-actions">
          <button type="submit" className="primary" disabled={csBusy}>
            {csBusy ? 'Saving…' : 'Save'}
          </button>
          {csSavedAt && <span className="muted">✓ saved</span>}
        </div>

        {csError && <div className="error">{csError}</div>}
      </form>

      <form onSubmit={onSave} className="settings-form">
        <h3>Publish targets</h3>
        <p className="muted">
          Optional. When set, the Publish view's YouTube and Facebook buttons
          deep-link straight to the right channel / Page. When blank, those
          buttons fall back to generic upload pages (post lands wherever the
          volunteer's signed in).
        </p>

        <label>
          <span>YouTube channel ID</span>
          <input
            type="text"
            placeholder="UC..."
            value={youtube}
            onChange={(e) => setYoutube(e.target.value)}
          />
          <small className="muted">
            Find it in <a href="https://www.youtube.com/account_advanced" target="_blank" rel="noopener noreferrer">
              YouTube account → Advanced settings
            </a> (starts with <code>UC</code>, 24 characters).
          </small>
        </label>

        <label>
          <span>Facebook Page ID</span>
          <input
            type="text"
            placeholder="123456789012345"
            value={facebook}
            onChange={(e) => setFacebook(e.target.value)}
          />
          <small className="muted">
            Visit your Page → <strong>About</strong> → <strong>Page transparency</strong> → <strong>Page ID</strong>.
            Numeric, ~15 digits.
          </small>
        </label>

        <div className="settings-actions">
          <button type="submit" className="primary" disabled={busy}>
            {busy ? 'Saving…' : 'Save'}
          </button>
          {savedAt && <span className="muted">✓ saved</span>}
        </div>

        {error && <div className="error">{error}</div>}
      </form>

      <div className="muted" style={{ marginTop: 24, fontSize: '0.9em' }}>
        TikTok and Instagram don't expose channel-specific upload URLs that
        work from a browser session, so those buttons stay generic regardless
        of what's set here.
      </div>
    </div>
  )
}
