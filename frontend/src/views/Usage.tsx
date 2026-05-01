import { useEffect, useState } from 'react'
import { api } from '../api'
import type { UsageResponse } from '../types'

type Props = {
  onBack: () => void
}

const ANTHROPIC_BILLING_URL = 'https://console.anthropic.com/settings/billing'

function fmtCost(usd: number): string {
  // Below 1¢ show four decimals so single-API-call usage doesn't round to $0.00.
  if (Math.abs(usd) < 0.01) return `$${usd.toFixed(4)}`
  return `$${usd.toFixed(2)}`
}

function fmtTokens(n: number): string {
  return n.toLocaleString()
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', year: 'numeric',
  })
}

function shorten(s: string, n = 50): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

export function Usage({ onBack }: Props) {
  const [data, setData] = useState<UsageResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  // Top-up form state
  const [showTopupForm, setShowTopupForm] = useState(false)
  const [topupAmount, setTopupAmount] = useState('')
  const [topupNote, setTopupNote] = useState('')
  const [topupBusy, setTopupBusy] = useState(false)
  const [topupError, setTopupError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    api.getUsage()
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [tick])

  const refresh = () => setTick((t) => t + 1)

  const submitTopup = async (e: React.FormEvent) => {
    e.preventDefault()
    setTopupError(null)
    const amount = parseFloat(topupAmount)
    if (!isFinite(amount) || amount <= 0) {
      setTopupError('Enter a positive dollar amount.')
      return
    }
    setTopupBusy(true)
    try {
      await api.addTopup(amount, topupNote.trim() || undefined)
      setTopupAmount('')
      setTopupNote('')
      setShowTopupForm(false)
      refresh()
    } catch (e) {
      setTopupError(String(e))
    } finally {
      setTopupBusy(false)
    }
  }

  const removeTopup = async (id: number) => {
    if (!confirm('Remove this top-up record? Balance will recompute.')) return
    try {
      await api.deleteTopup(id)
      refresh()
    } catch (e) {
      alert(`Failed to delete: ${e}`)
    }
  }

  return (
    <div className="usage">
      <div className="header-row">
        <button className="back" onClick={onBack}>← Back</button>
        <button className="secondary" onClick={refresh}>Refresh</button>
      </div>
      <h1>API Usage</h1>
      <div className="muted" style={{ marginBottom: 12 }}>
        Anthropic Claude API usage and estimated cost across all clip-selection runs.
        Numbers reflect what ConnectClips spent on this API key — any other
        usage on the same key is not included. Cost is computed locally from
        the model's published rate card.
      </div>

      {error && <div className="error">{error}</div>}
      {!data && !error && <div className="muted">Loading…</div>}

      {data && (
        <>
          {/* Balance card — first thing the admin sees. Renders red when
              the estimate falls below the configured threshold (default $1).
              Shows a "log your first top-up" CTA before any top-ups exist. */}
          <div className={`balance-card ${data.balance?.is_low ? 'low' : ''}`}>
            {data.balance ? (
              <>
                <div className="balance-main">
                  <div className="balance-label">Estimated balance</div>
                  <div className="balance-value">
                    {fmtCost(data.balance.estimated_balance_usd)}
                  </div>
                  {data.balance.is_low && (
                    <div className="balance-warning">
                      ⚠ Below ${data.balance.low_threshold_usd.toFixed(2)} —
                      time to top up.
                    </div>
                  )}
                </div>
                <div className="balance-meta">
                  <div>
                    <span className="muted">Topped up: </span>
                    {fmtCost(data.balance.total_topups_usd)} since{' '}
                    {fmtDate(data.balance.first_topup_at)}
                  </div>
                  <div>
                    <span className="muted">Spent since first top-up: </span>
                    {fmtCost(data.balance.total_spent_since_first_topup_usd)}
                  </div>
                </div>
                <div className="balance-actions">
                  <a
                    href={ANTHROPIC_BILLING_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="balance-link"
                  >
                    Top up at Anthropic →
                  </a>
                  <button
                    className="secondary"
                    onClick={() => setShowTopupForm(true)}
                  >
                    Log a top-up
                  </button>
                </div>
              </>
            ) : (
              <div className="balance-empty">
                <div className="balance-empty-title">Balance tracking not set up</div>
                <div className="muted" style={{ marginBottom: 10 }}>
                  Once you've topped up your Anthropic account, log the
                  amount here so ConnectClips can show an estimated remaining
                  balance and warn when it gets low.
                </div>
                <div className="balance-actions">
                  <a
                    href={ANTHROPIC_BILLING_URL}
                    target="_blank"
                    rel="noreferrer"
                    className="balance-link"
                  >
                    Top up at Anthropic →
                  </a>
                  <button onClick={() => setShowTopupForm(true)}>
                    Log my first top-up
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* Top-up logging form — inline panel, hidden by default. */}
          {showTopupForm && (
            <form className="topup-form" onSubmit={submitTopup}>
              <div className="topup-form-row">
                <label>
                  Amount (USD)
                  <input
                    type="number"
                    step="0.01"
                    min="0.01"
                    value={topupAmount}
                    onChange={(e) => setTopupAmount(e.target.value)}
                    placeholder="20.00"
                    required
                    autoFocus
                  />
                </label>
                <label>
                  Note <span className="muted">(optional)</span>
                  <input
                    type="text"
                    value={topupNote}
                    onChange={(e) => setTopupNote(e.target.value)}
                    placeholder="e.g. quarterly refill"
                  />
                </label>
              </div>
              {topupError && <div className="error">{topupError}</div>}
              <div className="topup-form-actions">
                <button type="submit" className="primary" disabled={topupBusy}>
                  {topupBusy ? 'Saving…' : 'Save top-up'}
                </button>
                <button
                  type="button"
                  className="secondary"
                  onClick={() => {
                    setShowTopupForm(false)
                    setTopupError(null)
                  }}
                >
                  Cancel
                </button>
              </div>
            </form>
          )}

          {/* Top-up history — only shown once at least one is recorded. */}
          {data.balance && data.balance.topups.length > 0 && (
            <details className="topup-history" open>
              <summary>Top-up history ({data.balance.topups.length})</summary>
              <table className="topup-table">
                <thead>
                  <tr>
                    <th>Date</th>
                    <th className="num">Amount</th>
                    <th>Note</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.balance.topups.map((t) => (
                    <tr key={t.id}>
                      <td>{fmtTime(t.created_at)}</td>
                      <td className="num">{fmtCost(t.amount_usd)}</td>
                      <td className="muted">{t.note || ''}</td>
                      <td>
                        <button
                          className="danger small"
                          onClick={() => removeTopup(t.id)}
                          title="Remove this top-up record"
                        >
                          Remove
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}

          {/* Aggregate spend stats. */}
          <h2 style={{ marginTop: 24 }}>Spend</h2>
          <div className="usage-summary">
            <div className="usage-stat">
              <div className="usage-stat-label">Estimated total spend</div>
              <div className="usage-stat-value">{fmtCost(data.summary.total_estimated_cost_usd)}</div>
            </div>
            <div className="usage-stat">
              <div className="usage-stat-label">Clip selections</div>
              <div className="usage-stat-value">{data.summary.n_clip_selections}</div>
            </div>
            <div className="usage-stat">
              <div className="usage-stat-label">Avg per sermon</div>
              <div className="usage-stat-value">
                {data.summary.n_clip_selections > 0
                  ? fmtCost(data.summary.total_estimated_cost_usd / data.summary.n_clip_selections)
                  : '—'}
              </div>
            </div>
            <div className="usage-stat">
              <div className="usage-stat-label">Output tokens</div>
              <div className="usage-stat-value">{fmtTokens(data.summary.total_output_tokens)}</div>
            </div>
            <div className="usage-stat">
              <div className="usage-stat-label">Cache writes</div>
              <div className="usage-stat-value">{fmtTokens(data.summary.total_cache_creation_input_tokens)}</div>
            </div>
            <div className="usage-stat">
              <div className="usage-stat-label">Cache reads</div>
              <div className="usage-stat-value">{fmtTokens(data.summary.total_cache_read_input_tokens)}</div>
            </div>
          </div>

          {data.rows.length === 0 ? (
            <div className="empty">
              No clip-selection runs yet. Once you run "Pick clips" on a sermon,
              its API usage will appear here.
            </div>
          ) : (
            <table className="usage-table">
              <thead>
                <tr>
                  <th>Sermon</th>
                  <th>When</th>
                  <th>Model</th>
                  <th className="num">Input</th>
                  <th className="num">Output</th>
                  <th className="num">Cache write</th>
                  <th className="num">Cache read</th>
                  <th className="num">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => (
                  <tr key={i}>
                    <td title={r.source}>{shorten(r.source)}</td>
                    <td>{fmtTime(r.created_at)}</td>
                    <td className="muted">{r.model ?? '—'}</td>
                    <td className="num">{fmtTokens(r.input_tokens)}</td>
                    <td className="num">{fmtTokens(r.output_tokens)}</td>
                    <td className="num">{fmtTokens(r.cache_creation_input_tokens)}</td>
                    <td className="num">{fmtTokens(r.cache_read_input_tokens)}</td>
                    <td className="num">{fmtCost(r.estimated_cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <div className="muted small" style={{ marginTop: 12 }}>
            Cost is estimated using Anthropic's published rate card (Sonnet 4.6:
            $3 / $15 / $3.75 / $0.30 per million tokens for input / output / cache-write
            / cache-read). For authoritative billing, see your{' '}
            <a href={ANTHROPIC_BILLING_URL} target="_blank" rel="noreferrer">
              Anthropic console
            </a>.
          </div>
        </>
      )}
    </div>
  )
}
