import { useState } from 'react'
import { api } from '../api'

type Props = {
  admin: boolean
  identityAdmin: boolean  // admin came from Tailscale identity, not password
  onChange: () => void    // tell parent to re-fetch /me
}

export function AdminControls({ admin, identityAdmin, onChange }: Props) {
  const [showPrompt, setShowPrompt] = useState(false)
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (admin) {
    return (
      <div className="admin-controls">
        <span className="badge admin">ADMIN MODE</span>
        {/* Only show Exit when admin came from the password (it can be revoked).
            Identity-based admin can't be "exited" without leaving the tailnet. */}
        {!identityAdmin && (
          <button
            className="secondary"
            onClick={async () => {
              setBusy(true)
              try {
                await api.exitAdmin()
                onChange()
              } finally {
                setBusy(false)
              }
            }}
            disabled={busy}
          >
            Exit
          </button>
        )}
      </div>
    )
  }

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      const r = await api.enterAdmin(password)
      if (r.admin) {
        setPassword('')
        setShowPrompt(false)
        onChange()
      } else {
        setError('Incorrect password.')
      }
    } catch (err) {
      setError(String(err))
    } finally {
      setBusy(false)
    }
  }

  if (!showPrompt) {
    return (
      <button className="secondary" onClick={() => setShowPrompt(true)}>
        Enter admin mode
      </button>
    )
  }

  return (
    <form className="admin-prompt" onSubmit={onSubmit}>
      <input
        type="password"
        autoFocus
        placeholder="Admin password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button type="submit" className="primary" disabled={busy || !password}>
        {busy ? '…' : 'Enter'}
      </button>
      <button
        type="button"
        className="secondary"
        onClick={() => {
          setShowPrompt(false)
          setPassword('')
          setError(null)
        }}
      >
        Cancel
      </button>
      {error && <span className="error-inline">{error}</span>}
    </form>
  )
}
