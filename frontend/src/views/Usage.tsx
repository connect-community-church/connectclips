import { useEffect, useState } from 'react'
import { api } from '../api'
import type { UsageResponse } from '../types'

type Props = {
  onBack: () => void
}

function fmtCost(usd: number): string {
  // Below 1¢, show four decimals so single-API-call usage doesn't round to $0.00.
  if (usd < 0.01) return `$${usd.toFixed(4)}`
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

function shorten(s: string, n = 50): string {
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

export function Usage({ onBack }: Props) {
  const [data, setData] = useState<UsageResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    api.getUsage()
      .then((d) => { if (!cancelled) setData(d) })
      .catch((e) => { if (!cancelled) setError(String(e)) })
    return () => { cancelled = true }
  }, [tick])

  return (
    <div className="usage">
      <div className="header-row">
        <button className="back" onClick={onBack}>← Back</button>
        <button className="secondary" onClick={() => setTick((t) => t + 1)}>Refresh</button>
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
          {/* Summary card — total dollars spent, # of runs, total tokens. */}
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
            <a href="https://console.anthropic.com/settings/usage" target="_blank" rel="noreferrer">
              Anthropic console
            </a>.
          </div>
        </>
      )}
    </div>
  )
}
