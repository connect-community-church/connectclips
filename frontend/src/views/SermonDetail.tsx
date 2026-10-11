import { useCallback, useEffect, useState } from 'react'
import { api } from '../api'
import type { Clip, ClipSelectionMode, ClipsFile, Job, Sermon, SocialPost } from '../types'

type Props = {
  sermon: Sermon
  admin: boolean
  onBack: () => void
  onTrim: (clip: Clip, clipIndex: number, selectionMode: ClipSelectionMode) => void
  initialSelectionMode?: ClipSelectionMode
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

const PLATFORM_LABELS: Record<string, string> = {
  youtube: 'YouTube', tiktok: 'TikTok', facebook: 'Facebook', instagram: 'Instagram', other: 'Other',
}

function fmtCount(n: number | null | undefined): string {
  if (n == null) return '—'
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

const IconEye = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 5C7 5 2.7 8.1 1 12c1.7 3.9 6 7 11 7s9.3-3.1 11-7c-1.7-3.9-6-7-11-7zm0 11.5A4.5 4.5 0 1 1 12 7.5a4.5 4.5 0 0 1 0 9zm0-7A2.5 2.5 0 1 0 12 14.5 2.5 2.5 0 0 0 12 9.5z"/>
  </svg>
)
const IconThumbsUp = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M1 10h4v12H1zM23 11c0-1.1-.9-2-2-2h-6.3l1-4.6.03-.34c0-.4-.17-.78-.44-1.05L14.17 2 7.59 8.59C7.22 8.95 7 9.45 7 10v10c0 1.1.9 2 2 2h9c.83 0 1.54-.5 1.84-1.22l3.02-7.05c.09-.23.14-.47.14-.73v-1.91z"/>
  </svg>
)
const IconChat = () => (
  <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M4 3h16a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H8l-4 4V5a2 2 0 0 1 2-2z"/>
  </svg>
)

function SermonSocialTotals({ postsByClip }: { postsByClip: Record<number, SocialPost[]> }) {
  const all = Object.values(postsByClip).flat()
  if (all.length === 0) return null

  const totals = all.reduce(
    (a, p) => ({
      views:    a.views    + (p.views    ?? 0),
      likes:    a.likes    + (p.likes    ?? 0),
      comments: a.comments + (p.comments ?? 0),
    }),
    { views: 0, likes: 0, comments: 0 },
  )

  const byPlatform = new Map<string, { views: number; likes: number; comments: number; count: number }>()
  for (const p of all) {
    const cur = byPlatform.get(p.platform) ?? { views: 0, likes: 0, comments: 0, count: 0 }
    cur.views    += p.views    ?? 0
    cur.likes    += p.likes    ?? 0
    cur.comments += p.comments ?? 0
    cur.count    += 1
    byPlatform.set(p.platform, cur)
  }

  return (
    <section className="sermon-social-totals">
      <div className="totals-row">
        <span className="muted small">Across {all.length} tracked post{all.length === 1 ? '' : 's'}:</span>
        <span className="totals-stat"><IconEye /> {fmtCount(totals.views)}</span>
        <span className="totals-stat"><IconThumbsUp /> {fmtCount(totals.likes)}</span>
        <span className="totals-stat"><IconChat /> {fmtCount(totals.comments)}</span>
      </div>
      <div className="clip-social-summary">
        {Array.from(byPlatform.entries()).map(([platform, s]) => (
          <span key={platform} className={'platform-badge platform-' + platform}>
            {PLATFORM_LABELS[platform] ?? platform}
            <span className="platform-stat" aria-label="views"><IconEye /> {fmtCount(s.views)}</span>
            <span className="platform-stat" aria-label="likes"><IconThumbsUp /> {fmtCount(s.likes)}</span>
            <span className="platform-stat" aria-label="comments"><IconChat /> {fmtCount(s.comments)}</span>
          </span>
        ))}
      </div>
    </section>
  )
}

function ClipSocialSummary({ posts }: { posts: SocialPost[] }) {
  if (posts.length === 0) return null
  return (
    <div className="clip-social-summary">
      {posts.map((p) => (
        <span
          key={p.id}
          className={'platform-badge platform-' + p.platform}
          title={p.post_url ?? ''}
        >
          {PLATFORM_LABELS[p.platform] ?? p.platform}
          <span className="platform-stat" aria-label="views"><IconEye /> {fmtCount(p.views)}</span>
          {p.likes != null && (
            <span className="platform-stat" aria-label="likes"><IconThumbsUp /> {fmtCount(p.likes)}</span>
          )}
          {p.comments != null && (
            <span className="platform-stat" aria-label="comments"><IconChat /> {fmtCount(p.comments)}</span>
          )}
        </span>
      ))}
    </div>
  )
}

export function SermonDetail({ sermon, admin, onBack, onTrim, initialSelectionMode = 'shorts', onDeleted }: Props) {
  const [clips, setClips] = useState<ClipsFile | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [activeJobs, setActiveJobs] = useState<Job[]>([])
  const [deleting, setDeleting] = useState(false)
  const [minClips, setMinClips] = useState(3)
  const [maxClips, setMaxClips] = useState(8)
  const [selectionMode, setSelectionMode] = useState<ClipSelectionMode>(initialSelectionMode)
  // Full-sermon YouTube URL drives the "watch from this moment" deep link in
  // the Publish view. Stored as a sidecar per sermon; admin edits it once
  // per sermon and volunteers consume the resulting deep link.
  const [programUrl, setProgramUrl] = useState<string>('')
  const [programVideoId, setProgramVideoId] = useState<string | null>(null)
  const [urlError, setUrlError] = useState<string | null>(null)
  const [urlSaving, setUrlSaving] = useState(false)
  const [postsByClip, setPostsByClip] = useState<Record<number, SocialPost[]>>({})

  useEffect(() => {
    api.listPosts({ sermon_source: sermon.name })
      .then((r) => {
        const grouped: Record<number, SocialPost[]> = {}
        for (const p of r.posts) {
          if (p.clip_index == null) continue
          ;(grouped[p.clip_index] ??= []).push(p)
        }
        setPostsByClip(grouped)
      })
      .catch(() => setPostsByClip({}))
  }, [sermon.name])

  const refreshClips = useCallback(() => {
    if (!sermon.clips_selected) {
      setClips(null)
      return
    }
    api.getClips(sermon.name, selectionMode).then(setClips).catch((e) => setError(String(e)))
  }, [sermon.name, sermon.clips_selected, selectionMode])

  useEffect(() => {
    refreshClips()
  }, [refreshClips])

  // Load the per-sermon meta once. The URL is read here for both admin
  // (to populate the edit field) and non-admin (so we can display the
  // current setting read-only or hide it if unset).
  useEffect(() => {
    let cancelled = false
    api.getSermonMeta(sermon.name).then((m) => {
      if (cancelled) return
      setProgramUrl(m.program_video_url ?? '')
      setProgramVideoId(m.program_video_id ?? null)
    }).catch(() => {})
    return () => { cancelled = true }
  }, [sermon.name])

  const saveProgramUrl = async (raw: string) => {
    const trimmed = raw.trim()
    setUrlError(null)
    setUrlSaving(true)
    try {
      const m = await api.saveSermonMeta(sermon.name, { program_video_url: trimmed || null })
      setProgramUrl(m.program_video_url ?? '')
      setProgramVideoId(m.program_video_id ?? null)
    } catch (err) {
      setUrlError(String(err))
    } finally {
      setUrlSaving(false)
    }
  }

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
    api.startSelectClips(sermon.name, minClips, maxClips, selectionMode).catch((e) => setError(String(e)))
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

      <SermonSocialTotals postsByClip={postsByClip} />

      {error && <div className="error">Error: {error}</div>}

      {(admin || programVideoId) && (
        <section className="program-url-row">
          <label className="muted small" htmlFor="program-url-input">Full sermon YouTube URL</label>
          {admin ? (
            <>
              <input
                id="program-url-input"
                type="url"
                className="program-url-input"
                placeholder="https://youtu.be/… (used for clip deep-links)"
                value={programUrl}
                disabled={urlSaving}
                onChange={(e) => setProgramUrl(e.target.value)}
                onBlur={(e) => saveProgramUrl(e.target.value)}
              />
              {programVideoId && (
                <span className="badge ok" title="Parsed YouTube video ID — deep links will work">
                  ✓ {programVideoId}
                </span>
              )}
              {urlError && <span className="error-inline">{urlError}</span>}
            </>
          ) : (
            programVideoId && (
              <a
                href={`https://youtu.be/${programVideoId}`}
                target="_blank"
                rel="noopener noreferrer"
                className="muted small"
              >
                youtu.be/{programVideoId}
              </a>
            )
          )}
        </section>
      )}

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
            <label className="muted">Mode</label>
            <select
              value={selectionMode}
              onChange={(e) => {
                const mode = e.target.value as ClipSelectionMode
                setSelectionMode(mode)
                if (mode === 'deeper') {
                  setMinClips(1)
                  setMaxClips(2)
                } else {
                  setMinClips(3)
                  setMaxClips(8)
                }
              }}
              title="Shorts finds 30–90 second clips. Deeper Clips finds 2:30–5:00 midweek excerpts from the whole sermon."
            >
              <option value="shorts">Shorts</option>
              <option value="deeper">Deeper Clips</option>
            </select>
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
                title="Re-run Claude clip selection with the mode and range above"
              >
                {runningKinds.has('select_clips') ? 'Re-running…' : `Re-run ${selectionMode === 'deeper' ? 'Deeper Clips' : 'Shorts'}`}
              </button>
              <JobProgress job={selectJob} />
            </>
          ) : (
            <>
              <button
                onClick={onSelectClips}
                disabled={!sermon.transcribed || runningKinds.has('select_clips')}
              >
                {runningKinds.has('select_clips') ? 'Running…' : `Run ${selectionMode === 'deeper' ? 'Deeper Clips' : 'clip selection'}`}
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
          <h2>{clips.selection_mode === 'deeper' ? 'Suggested Deeper Clips' : 'Suggested clips'}</h2>
          {clips.selection_mode === 'deeper' && (
            <p className="muted small">Longer midweek excerpts chosen from the whole sermon, not from the existing Shorts pool.</p>
          )}
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
                    <button onClick={() => onTrim(clip, i, clips.selection_mode ?? selectionMode)}>
                      {clip.exported ? 'Re-trim & export' : 'Preview / trim / export'}
                    </button>
                  </div>
                  <ClipSocialSummary posts={postsByClip[i] ?? []} />
                </li>
              )
            })}
          </ul>
        </section>
      )}
    </div>
  )
}
