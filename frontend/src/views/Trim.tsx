import { useEffect, useRef, useState } from 'react'
import { api, fileUrl } from '../api'
import type { Clip, Identity, Job, Sermon } from '../types'
import { Publish } from './Publish'
import { CaptionStylePicker } from './CaptionStylePicker'
import { LivePreview } from './LivePreview'

type Props = {
  sermon: Sermon
  clip: Clip
  clipIndex: number
  onBack: () => void
}

const NUDGE_STEP = 0.1 // seconds

export function Trim({ sermon, clip, clipIndex, onBack }: Props) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [start, setStart] = useState(clip.start)
  const [end, setEnd] = useState(clip.end)
  const [looping, setLooping] = useState(false)
  const [exportJob, setExportJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [styles, setStyles] = useState<{ key: string; label: string }[]>([])
  const [styleKey, setStyleKey] = useState<string>('classic')
  const [includeHookTitle, setIncludeHookTitle] = useState(true)
  // Volunteer's drag-set caption position (px from bottom in 1080×1920 frame).
  // null = use the picked style's default. Resets to null when style changes
  // because each style has a different ideal default position.
  const [captionMarginV, setCaptionMarginV] = useState<number | null>(null)
  const [identities, setIdentities] = useState<Identity[]>([])
  const [identityScanned, setIdentityScanned] = useState(false)
  // null = "auto" (highest-score live face per sample). Set to an id when the
  // volunteer picks a specific face from the strip; the picker only shows up
  // if the scan found more than one identity.
  const [identityId, setIdentityId] = useState<number | null>(null)

  useEffect(() => {
    api.captionStyles()
      .then((r) => { setStyles(r.styles); setStyleKey(r.default) })
      .catch(() => { /* fall back to none — backend uses default */ })
  }, [])

  // Identities for this sermon. Poll while scan is in progress so the picker
  // appears as soon as the prescan job finishes — no manual refresh needed.
  useEffect(() => {
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    const tick = () => {
      api.getIdentities(sermon.name)
        .then((r) => {
          if (cancelled) return
          setIdentities(r.identities)
          setIdentityScanned(r.scanned)
          if (!r.scanned) timer = setTimeout(tick, 5000)
        })
        .catch(() => {
          if (!cancelled) timer = setTimeout(tick, 8000)
        })
    }
    tick()
    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [sermon.name])

  // Reset caption position override when the volunteer picks a different style.
  // Different styles have different default positions and chunk sizes; carrying
  // a previous style's offset usually puts captions in the wrong place.
  useEffect(() => { setCaptionMarginV(null) }, [styleKey])

  // Position the source video at start when clip changes
  useEffect(() => {
    const v = videoRef.current
    if (v) {
      v.currentTime = clip.start
    }
  }, [clip.start])

  // Loop within [start, end] when looping is on
  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => {
      if (looping && v.currentTime >= end) {
        v.currentTime = start
      }
    }
    v.addEventListener('timeupdate', onTime)
    return () => v.removeEventListener('timeupdate', onTime)
  }, [start, end, looping])

  // Poll the export job status. Faster cadence while running so the progress
  // bar feels responsive; backend throttles its DB writes, not us.
  useEffect(() => {
    if (!exportJob || exportJob.status === 'done' || exportJob.status === 'failed') return
    const id = setInterval(async () => {
      try {
        const updated = await api.getJob(exportJob.id)
        setExportJob(updated)
      } catch {}
    }, 750)
    return () => clearInterval(id)
  }, [exportJob])

  const setInToCurrent = () => {
    const v = videoRef.current
    if (v) setStart(parseFloat(v.currentTime.toFixed(2)))
  }
  const setOutToCurrent = () => {
    const v = videoRef.current
    if (v) setEnd(parseFloat(v.currentTime.toFixed(2)))
  }
  const seekTo = (t: number) => {
    const v = videoRef.current
    if (!v) return
    setLooping(false)
    v.pause()
    v.currentTime = t
  }
  const playRange = () => {
    const v = videoRef.current
    if (!v) return
    v.currentTime = start
    v.play()
    setLooping(true)
  }
  const onExport = async () => {
    setError(null)
    try {
      const j = await api.startExportClip(
        sermon.name, clipIndex, start, end, styleKey, includeHookTitle,
        captionMarginV, identityId,
      )
      setExportJob(j)
    } catch (e) {
      setError(String(e))
    }
  }

  // Decide whether to show the face picker.
  //
  // The identity tracker can fragment a single person across layout changes
  // (full-frame → PiP-right → PiP-middle) because the centroid position and
  // face size shift between layouts and look like "different people" without
  // proper face embeddings. A solo-pastor sermon with active ATEM switching
  // typically produces 6-13 identity tracks for what's really just the pastor.
  //
  // Heuristic: show the picker only when 2-4 identities each account for at
  // least 10 % of detection samples. That covers the genuine multi-person
  // case (pastor + guest both on screen — single shot, no layout shuffle)
  // and skips the layout-fragmentation mess. Above 4 significant identities,
  // auto-pick (highest-score live face per sample) is the right behavior and
  // the picker would just confuse the volunteer.
  const totalSamples = identities.reduce((a, id) => a + id.n_samples, 0)
  const significantIdentities = identities.filter(
    (id) => totalSamples > 0 && id.n_samples / totalSamples >= 0.1,
  )
  const showFacePicker =
    identityScanned &&
    significantIdentities.length >= 2 &&
    significantIdentities.length <= 4

  const exporting = exportJob && (exportJob.status === 'queued' || exportJob.status === 'running')
  const exportedPath = exportJob?.output_clip_path
  const exportedFilename = exportedPath ? exportedPath.split('/').pop() : null
  const currentExportedFilename = exportJob?.status === 'done' ? exportedFilename : (clip.exported ? clip.output_filename : null)
  const previous = clip.previous_export
  // Stale exports come from clip-runs of clips.json that have been overwritten.
  // The MP4 still exists; we offer a download but don't auto-play it because its
  // content corresponds to a different clip range than the one being trimmed now.
  const showStale = !currentExportedFilename && !exporting && previous

  return (
    <div className="trim">
      <button className="back" onClick={onBack}>← Back</button>
      <h2>{clip.title}</h2>
      <div className="muted">{clip.rationale}</div>

      <div className="player-row">
        <div className="player">
          <div className="muted">Source video — scrub to find frame, then set in / out</div>
          <video
            ref={videoRef}
            src={fileUrl.source(sermon.name)}
            controls
            preload="metadata"
            style={{ width: '100%', maxWidth: 640, background: 'black' }}
          />
          <div className="trim-controls">
            <div className="time-input">
              <label>Start</label>
              <input
                type="number"
                step={NUDGE_STEP}
                value={start.toFixed(2)}
                onChange={(e) => setStart(parseFloat(e.target.value))}
              />
              <button onClick={() => setStart((s) => Math.max(0, s - NUDGE_STEP))}>−0.1s</button>
              <button onClick={() => setStart((s) => s + NUDGE_STEP)}>+0.1s</button>
              <button onClick={setInToCurrent} title="Set start to current playhead">⤓ playhead</button>
              <button onClick={() => seekTo(start)} title="Jump video to current start">⏮ go</button>
            </div>
            <div className="time-input">
              <label>End</label>
              <input
                type="number"
                step={NUDGE_STEP}
                value={end.toFixed(2)}
                onChange={(e) => setEnd(parseFloat(e.target.value))}
              />
              <button onClick={() => setEnd((s) => Math.max(start + 0.1, s - NUDGE_STEP))}>−0.1s</button>
              <button onClick={() => setEnd((s) => s + NUDGE_STEP)}>+0.1s</button>
              <button onClick={setOutToCurrent} title="Set end to current playhead">⤓ playhead</button>
              <button onClick={() => seekTo(Math.max(0, end - 0.05))} title="Jump video to just before current end">⏭ go</button>
            </div>
            <div className="duration">Duration: {(end - start).toFixed(2)}s</div>
            <div className="action-row">
              <button onClick={playRange}>▶ Play range (loop)</button>
              <button
                className={looping ? 'active' : 'secondary'}
                onClick={() => setLooping((l) => !l)}
              >
                Loop: {looping ? 'on' : 'off'}
              </button>
              {styles.length > 0 && (
                <CaptionStylePicker
                  styles={styles}
                  value={styleKey}
                  onChange={setStyleKey}
                />
              )}
              <label className="hook-toggle" title="Burn the clip's hook title on screen for the first 2s">
                <input
                  type="checkbox"
                  checked={includeHookTitle}
                  onChange={(e) => setIncludeHookTitle(e.target.checked)}
                />
                Hook title overlay
              </label>
              {captionMarginV !== null && (
                <button
                  className="secondary"
                  onClick={() => setCaptionMarginV(null)}
                  title="Reset caption position to the style's default"
                >
                  Reset position
                </button>
              )}
              <button className="primary" onClick={onExport} disabled={!!exporting}>
                {exporting ? 'Exporting…' : 'Export vertical clip'}
              </button>
            </div>
            {error && <div className="error">{error}</div>}
            {exportJob?.status === 'failed' && (
              <div className="error">Export failed: {(exportJob.error ?? '').split('\n')[0]}</div>
            )}
          </div>
        </div>

        <div className="output">
          <div className="muted preview-label">
            Preview — drag captions up/down to position
          </div>
          <LivePreview
            sermon={sermon.name}
            clipStart={start}
            clipEnd={end}
            sourceVideoRef={videoRef}
            captionStyleKey={styleKey}
            captionMarginV={captionMarginV}
            onCaptionMarginVChange={setCaptionMarginV}
            includeHookTitle={includeHookTitle}
            hookTitle={clip.title}
            identityId={identityId}
          />

          {showFacePicker && (
            <div className="face-picker">
              <div className="muted small">Track which face?</div>
              <div className="face-picker-row">
                <button
                  className={`face-thumb auto ${identityId === null ? 'selected' : ''}`}
                  onClick={() => setIdentityId(null)}
                  title="Auto: follow the most prominent face per moment"
                >
                  Auto
                </button>
                {significantIdentities.map((id) => (
                  <button
                    key={id.id}
                    className={`face-thumb ${identityId === id.id ? 'selected' : ''}`}
                    onClick={() => setIdentityId(id.id)}
                    title={`Identity ${id.id} · ${id.n_samples} samples`}
                  >
                    <img
                      src={fileUrl.identityThumb(sermon.name, id.id)}
                      alt={`Face ${id.id}`}
                    />
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="export-status">
            {exporting && (
              <div className="export-progress">
                <div>{exportJob?.progress_message ?? 'Exporting…'}</div>
                <progress
                  value={exportJob?.progress_percent ?? 0}
                  max={1}
                />
                <div className="progress-pct">
                  {Math.round((exportJob?.progress_percent ?? 0) * 100)}%
                </div>
              </div>
            )}
            {currentExportedFilename && (
              <div className="muted">
                Exported · <a href={fileUrl.clip(currentExportedFilename)} download>Download</a>
              </div>
            )}
            {showStale && previous && (
              <div className="stale-export-warning">
                Previous export from a different clip range
                ({previous.start.toFixed(1)} – {previous.end.toFixed(1)}s,
                {' '}{(previous.end - previous.start).toFixed(1)}s long) ·{' '}
                <a href={fileUrl.clip(previous.filename)} download>Download</a>
                <div className="muted small">
                  Re-export to apply your current trim and settings.
                </div>
              </div>
            )}
            {!exporting && !currentExportedFilename && !showStale && (
              <div className="muted small">No export yet.</div>
            )}
          </div>

          {currentExportedFilename && (
            <Publish
              sermon={sermon}
              clip={clip}
              exportedFilename={currentExportedFilename}
            />
          )}
        </div>
      </div>
    </div>
  )
}
