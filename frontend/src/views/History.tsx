import { useEffect, useState } from 'react'
import { api, fileUrl } from '../api'
import type { Job } from '../types'

type Props = {
  onBack: () => void
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

function fmtDuration(start: string | null, end: string | null): string {
  if (!start || !end) return ''
  const ms = new Date(end).getTime() - new Date(start).getTime()
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

function shorten(s: string | null, n = 40): string {
  if (!s) return ''
  return s.length > n ? s.slice(0, n - 1) + '…' : s
}

function jobLabel(j: Job): string {
  switch (j.kind) {
    case 'upload': return `Upload ${shorten(j.source, 38)}`
    case 'youtube_download': return j.url ? `YouTube: ${shorten(j.url, 40)}` : 'YouTube download'
    case 'transcribe': return `Transcribe ${shorten(j.source, 32)}`
    case 'select_clips': return `Pick clips for ${shorten(j.source, 32)}`
    case 'export_clip':
      return `Export clip ${j.clip_index ?? '?'} of ${shorten(j.source, 28)}`
    default: return j.kind
  }
}

export function History({ onBack }: Props) {
  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<string>('')
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      api.listJobs(200)
        .then((d) => { if (!cancelled) setJobs(d) })
        .catch((e) => { if (!cancelled) setError(String(e)) })
    load()
    const id = setInterval(load, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [tick])

  const filtered = (jobs ?? []).filter((j) => {
    if (!filter) return true
    const f = filter.toLowerCase()
    return (j.user_name?.toLowerCase().includes(f)
      || j.user_login?.toLowerCase().includes(f)
      || j.source?.toLowerCase().includes(f)
      || j.kind.includes(f)
      || j.status.includes(f))
  })

  return (
    <div className="history">
      <div className="header-row">
        <button className="back" onClick={onBack}>← Back</button>
        <button className="secondary" onClick={() => setTick((t) => t + 1)}>Refresh</button>
      </div>
      <h1>Activity</h1>
      <div className="muted" style={{ marginBottom: 12 }}>
        Most recent 200 actions across all users. Refreshes every 5 seconds.
      </div>
      <input
        type="text"
        placeholder="Filter — user, sermon, kind, status…"
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="history-filter"
      />
      {error && <div className="error">{error}</div>}
      {!jobs && !error && <div className="muted">Loading…</div>}
      {jobs && (
        <table className="history-table">
          <thead>
            <tr>
              <th>When</th>
              <th>Who</th>
              <th>What</th>
              <th>Status</th>
              <th>Duration</th>
              <th>Output</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((j) => (
              <tr key={j.id} className={`row-${j.status}`}>
                <td className="muted small">{fmtTime(j.created_at)}</td>
                <td>{j.user_name ?? <span className="muted">anon</span>}</td>
                <td title={j.error ?? ''}>{jobLabel(j)}</td>
                <td>
                  <span className={`status-pill status-${j.status}`}>{j.status}</span>
                  {j.status === 'running' && typeof j.progress_percent === 'number' && (
                    <div className="status-progress">
                      <progress value={j.progress_percent} max={1} />
                      <span className="status-progress-pct">
                        {Math.round(j.progress_percent * 100)}%
                      </span>
                      {j.progress_message && (
                        <div className="status-progress-msg muted small">
                          {j.progress_message}
                        </div>
                      )}
                    </div>
                  )}
                </td>
                <td className="muted small">{fmtDuration(j.started_at, j.finished_at)}</td>
                <td className="small">
                  {j.kind === 'export_clip' && j.status === 'done' && j.output_clip_path && (
                    <a
                      href={fileUrl.clip(j.output_clip_path.split('/').pop() ?? '')}
                      download
                      title="Download the exported MP4 — preserved across clips.json regenerations"
                    >
                      Download
                    </a>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={6} className="muted" style={{ textAlign: 'center', padding: 24 }}>
                No matches.
              </td></tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  )
}
