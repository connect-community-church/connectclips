import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { Job } from '../types'

type Props = {
  onAdded: () => void  // tell parent to refresh sermon list
  onUpload: (file: File) => void  // app-global upload (progress shown in header banner)
  uploadActive: boolean
}

export function AddSermon({ onAdded, onUpload, uploadActive }: Props) {
  const [url, setUrl] = useState('')
  const [ytJob, setYtJob] = useState<Job | null>(null)
  const [error, setError] = useState<string | null>(null)
  const fileInput = useRef<HTMLInputElement | null>(null)

  // Poll the YouTube download job until done/failed
  useEffect(() => {
    if (!ytJob || ytJob.status === 'done' || ytJob.status === 'failed') return
    const id = setInterval(async () => {
      try {
        const updated = await api.getJob(ytJob.id)
        setYtJob(updated)
        if (updated.status === 'done') {
          onAdded()
          // clear after a beat so the user sees the success
          setTimeout(() => setYtJob(null), 1500)
        }
      } catch {}
    }, 2000)
    return () => clearInterval(id)
  }, [ytJob, onAdded])

  const onYoutubeSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError(null)
    if (!url.trim()) return
    try {
      const j = await api.startYoutubeDownload(url.trim())
      setYtJob(j)
      setUrl('')
    } catch (err) {
      setError(String(err))
    }
  }

  const onFilePicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError(null)
    onUpload(file)  // app-global; progress banner survives navigation
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <section className="add-sermon">
      <h2>Add a sermon</h2>
      <div className="add-row">
        <form className="add-youtube" onSubmit={onYoutubeSubmit}>
          <label className="muted">From YouTube</label>
          <div className="input-row">
            <input
              type="text"
              placeholder="https://www.youtube.com/watch?v=…"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              disabled={!!ytJob && ytJob.status !== 'done' && ytJob.status !== 'failed'}
            />
            <button
              type="submit"
              className="primary"
              disabled={!url.trim() || (!!ytJob && ytJob.status !== 'done' && ytJob.status !== 'failed')}
            >
              {ytJob && ytJob.status === 'queued' && 'Queued…'}
              {ytJob && ytJob.status === 'running' && 'Downloading…'}
              {(!ytJob || ytJob.status === 'done' || ytJob.status === 'failed') && 'Download'}
            </button>
          </div>
          {ytJob?.status === 'done' && (
            <div className="muted" style={{ marginTop: 6 }}>
              ✓ Saved as <code>{ytJob.ingested_filename}</code>
            </div>
          )}
          {ytJob?.status === 'failed' && (
            <div className="error">YouTube download failed: {(ytJob.error ?? '').split('\n')[0]}</div>
          )}
        </form>

        <div className="add-upload">
          <label className="muted">Upload a file{uploadActive && <> · pick another to add to the queue</>}</label>
          <div className="input-row">
            <input
              ref={fileInput}
              type="file"
              accept="video/*,audio/*"
              onChange={onFilePicked}
            />
          </div>
          <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
            mp4, mov, mkv, webm, wav, mp3, m4a, flac, etc. Multiple uploads run in parallel — progress shows in the banners above.
          </div>
        </div>
      </div>
      {error && <div className="error">{error}</div>}
    </section>
  )
}
