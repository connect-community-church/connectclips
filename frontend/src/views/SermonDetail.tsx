import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Clip, ClipsFile, Job, Sermon } from '../types'

type Props = {
  sermon: Sermon
  admin: boolean
  onBack: () => void
  onTrim: (clip: Clip, clipIndex: number) => void
  onDeleted: () => void
}

function fmtSecs(s: number): string {
  const m = Math.floor(s / 60)
  const sec = (s % 60).toFixed(1)
  return `${m}:${sec.padStart(4, '0')}`
}

function fmtRelTime(iso: string | null): string {
  if (!iso) return ''
  const dt = new Date(iso).getTime()
  const ms = Date.now() - dt
  if (ms < 60_000) return 'just now'
  if (ms < 3_600_000) return `${Math.floor(ms / 60_000)}m ago`
  if (ms < 86_400_000) return `${Math.floor(ms / 3_600_000)}h ago`
  return `${Math.floor(ms / 86_400_000)}d ago`
}

function jobLabel(j: Job): string {
  const kind = j.kind.replace('_', ' ')
  if (j.status === 'failed') return `${kind} failed: ${(j.error ?? '').split('\n')[0]}`
  if (j.status === 'running') return `${kind} running…`
  if (j.status === 'queued') return `${kind} queued`
  return `${kind} done`
}

function JobProgress({ job }: { job: Job | undefined }) {
  if (!job) return null
  if (job.status !== 'running' && job.status !== 'queued') return null
  const hasPercent = typeof job.progress_percent === 'number'
  return (
    <div className="status-progress">
      {/* HTML5 `<progress>` renders an animated indeterminate bar when no
          value attribute is set — used here for jobs (like select_clips)
          that don't expose a percentage during their single API call. */}
      {hasPercent ? (
        <progress value={job.progress_percent ?? 0} max={1} />
      ) : (
        <progress />
      )}
      {hasPercent && (
        <span className="status-progress-pct">
          {Math.round((job.progress_percent ?? 0) * 100)}%
        </span>
      )}
      {job.progress_message && (
        <div className="status-progress-msg muted small">{job.progress_message}</div>
      )}
    </div>
  )
}

function hookScoreClass(score: number): string {
  if (score >= 85) return 'high'
  if (score >= 70) return 'good'
  if (score >= 55) return 'med'
  return 'low'
}

export function SermonDetail({ sermon, admin, onBack, onTrim, onDeleted }: Props) {
  const [clips, setClips] = useState<ClipsFile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeJobs, setActiveJobs] = useState<Job[]>([])
  const [deleting, setDeleting] = useState(false)
  const [minClips, setMinClips] = useState(3)
  const [maxClips, setMaxClips] = useState(8)

  const refreshClips = useCallback(() => {
    if (!sermon.clips_selected) {
      setClips(null)
      return
    }
    api.getClips(sermon.name).then(setClips).catch((e) => setError(String(e)))
  }, [sermon.name, sermon.clips_selected])

  useEffect(() => {
    refreshClips()
  }, [refreshClips])

  // Poll relevant jobs every 2s while any are active for this sermon
  useEffect(() => {
    let cancelled = false
    const tick = async () => {
      try {
        const jobs = await api.listJobs()
        if (cancelled) return
        const mine = jobs.filter((j) => j.source === sermon.name)
        setActiveJobs(mine)
        // If anything just finished, refresh clips
        if (mine.some((j) => j.status === 'done' && j.kind !== 'transcribe')) {
          refreshClips()
        }
      } catch {}
    }
    tick()
    const id = setInterval(tick, 2000)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [sermon.name, refreshClips])

  const runningKinds = new Set(
    activeJobs.filter((j) => j.status === 'queued' || j.status === 'running').map((j) => j.kind),
  )
  const recentJobsFor = (kind: string) =>
    activeJobs.filter((j) => j.kind === kind).sort((a, b) => b.created_at.localeCompare(a.created_at))[0]

  const transcribeJob = recentJobsFor('transcribe')
  const selectJob = recentJobsFor('select_clips')
  const prescanJob = recentJobsFor('prescan_faces')

  const onTranscribe = () => api.startTranscribe(sermon.name).catch((e) => setError(String(e)))
  const onSelectClips = () =>
    api.startSelectClips(sermon.name, minClips, maxClips).catch((e) => setError(String(e)))
  const onDelete = async () => {
    if (!window.confirm(`Delete "${sermon.name}"?\n\nThis removes the source file, transcript, clips.json, and every exported MP4.`)) return
    setDeleting(true)
    setError(null)
    try {
      await api.deleteSermon(sermon.name)
      onDeleted()
    } catch (err) {
      setError(String(err))
      setDeleting(false)
    }
  }

  return (
    <div className="sermon-detail">
      <div className="header-row">
        <button className="back" onClick={onBack}>← Back</button>
        {admin && (
          <button className="danger" onClick={onDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete sermon'}
          </button>
        )}
      </div>
      <h1 title={sermon.name}>{sermon.name}</h1>

      {error && <div className="error">Error: {error}</div>}

      <section className="pipeline">
        <div className="step">
          <div className="step-title">1. Transcribe</div>
          {sermon.transcribed ? (
            <span className="badge ok">✓ done</span>
          ) : (
            <>
              <button onClick={onTranscribe} disabled={runningKinds.has('transcribe')}>
                {runningKinds.has('transcribe') ? 'Running…' : 'Run transcribe'}
              </button>
              <JobProgress job={transcribeJob} />
              {transcribeJob && transcribeJob.status === 'failed' && (
                <span className="error-inline">{jobLabel(transcribeJob)}</span>
              )}
            </>
          )}
        </div>
        <div className="step">
          <div className="step-title">2. Pick clips</div>
          <div className="clip-count-controls">
            <label className="muted">Range</label>
            <input
              type="number"
              min={1}
              max={20}
              value={minClips}
              onChange={(e) => setMinClips(Math.max(1, parseInt(e.target.value || '1', 10)))}
              title="minimum clips Claude must return"
            />
            <span className="muted">to</span>
            <input
              type="number"
              min={minClips}
              max={20}
              value={maxClips}
              onChange={(e) => setMaxClips(Math.max(minClips, parseInt(e.target.value || '1', 10)))}
              title="maximum clips Claude may return"
            />
          </div>
          {sermon.clips_selected ? (
            <>
              <span className="badge ok">✓ {sermon.n_clips} clips</span>
              <button
                className="secondary"
                onClick={onSelectClips}
                disabled={runningKinds.has('select_clips')}
                title="Re-run Claude clip selection with the range above"
              >
                {runningKinds.has('select_clips') ? 'Re-running…' : 'Re-run'}
              </button>
              <JobProgress job={selectJob} />
            </>
          ) : (
            <>
              <button
                onClick={onSelectClips}
                disabled={!sermon.transcribed || runningKinds.has('select_clips')}
              >
                {runningKinds.has('select_clips') ? 'Running…' : 'Run clip selection'}
              </button>
              {!sermon.transcribed && <span className="muted">(transcribe first)</span>}
              <JobProgress job={selectJob} />
              {selectJob && selectJob.status === 'failed' && (
                <span className="error-inline">{jobLabel(selectJob)}</span>
              )}
            </>
          )}
        </div>
        {prescanJob && (prescanJob.status === 'queued' || prescanJob.status === 'running') && (
          <div className="step">
            <div className="step-title muted">Background: face prescan</div>
            <JobProgress job={prescanJob} />
          </div>
        )}
      </section>

      {clips && (
        <section className="clips">
          <h2>Suggested clips</h2>
          <ul>
            {clips.clips
              .map((clip, i) => ({ clip, i }))
              .sort((a, b) => (b.clip.hook_score ?? -1) - (a.clip.hook_score ?? -1))
              .map(({ clip, i }) => {
              const exportJobs = activeJobs.filter(
                (j) => j.kind === 'export_clip' && j.clip_index === i,
              )
              const latest = exportJobs.sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
              const exporting = latest && (latest.status === 'queued' || latest.status === 'running')
              const score = clip.hook_score
              return (
                <li key={i} className="clip-card">
                  <div className="clip-title">
                    {score !== undefined && (
                      <span
                        className={`hook-score ${hookScoreClass(score)}`}
                        title="Hook score: how likely a cold scroller keeps watching past 3s"
                      >
                        {score}
                      </span>
                    )}
                    {clip.title}
                  </div>
                  <div className="clip-meta">
                    {fmtSecs(clip.start)} – {fmtSecs(clip.end)} · {(clip.end - clip.start).toFixed(1)}s
                    {clip.exported && <span className="badge ok"> ✓ exported</span>}
                    {exporting && <span className="badge"> exporting…</span>}
                    {latest?.status === 'failed' && (
                      <span className="error-inline"> {(latest.error ?? '').split('\n')[0]}</span>
                    )}
                    {clip.exported && clip.last_exported_by_name && (
                      <span className="muted clip-attribution">
                        {' '}by <strong>{clip.last_exported_by_name}</strong>
                        {clip.last_exported_at && <> · {fmtRelTime(clip.last_exported_at)}</>}
                      </span>
                    )}
                  </div>
                  {exporting && <JobProgress job={latest} />}
                  <div className="clip-rationale">{clip.rationale}</div>
                  {clip.hook_rationale && (
                    <div className="clip-hook-rationale">
                      <span className="clip-hook-label">Hook:</span> {clip.hook_rationale}
                    </div>
                  )}
                  <div className="clip-actions">
                    <button onClick={() => onTrim(clip, i)}>
                      {clip.exported ? 'Re-trim & export' : 'Preview / trim / export'}
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
