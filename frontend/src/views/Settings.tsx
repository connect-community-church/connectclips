import { useEffect, useState } from 'react'
import { api } from '../api'

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
  const [loaded, setLoaded] = useState(false)
  const [youtube, setYoutube] = useState('')
  const [facebook, setFacebook] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [savedAt, setSavedAt] = useState<number | null>(null)

  useEffect(() => {
    api.getPublishTargets()
      .then((t: Targets) => {
        setYoutube(t.youtube_channel_id ?? '')
        setFacebook(t.facebook_page_id ?? '')
      })
      .catch((e) => setError(`Couldn't load: ${e}`))
      .finally(() => setLoaded(true))
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

  if (!loaded) {
    return <div className="muted" style={{ padding: 24 }}>Loading…</div>
  }

  return (
    <div className="settings-page">
      <button className="secondary" onClick={onBack}>← Back</button>

      <h2>Settings</h2>

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
