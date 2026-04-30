import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { SermonList } from './views/SermonList'
import { SermonDetail } from './views/SermonDetail'
import { Trim } from './views/Trim'
import { AdminControls } from './views/AdminControls'
import { History } from './views/History'
import type { Clip, Me, Sermon } from './types'
import logo from './assets/ccchlogo.png'
import './App.css'

type View =
  | { name: 'list' }
  | { name: 'detail'; sermon: Sermon }
  | { name: 'trim'; sermon: Sermon; clip: Clip; clipIndex: number }
  | { name: 'history' }

type Upload = {
  id: string  // client-side; lets the banner key by uploads even if the file
              // server-side job-id isn't fetched yet.
  filename: string
  status: 'uploading' | 'success' | 'failed'
  loaded: number
  total: number
  error?: string
  xhr?: XMLHttpRequest
}

const ANON: Me = { login: null, name: null, profile_pic: null, admin: false, anonymous: true }

function App() {
  const [view, setView] = useState<View>({ name: 'list' })
  const [me, setMe] = useState<Me>(ANON)
  const [listVersion, setListVersion] = useState(0)
  const [uploads, setUploads] = useState<Upload[]>([])

  const refreshMe = useCallback(() => {
    api.me().then(setMe).catch(() => setMe(ANON))
  }, [])

  useEffect(() => {
    refreshMe()
  }, [refreshMe])

  const refreshSermon = async (name: string): Promise<Sermon | null> => {
    const list = await api.listSermons()
    return list.find((s) => s.name === name) ?? null
  }

  // Each call to startUpload creates an independent Upload entry with its own
  // XHR. Multiple uploads run in parallel — browsers cap to ~6 concurrent
  // requests per origin, so a 10-file batch self-throttles. Each entry's
  // banner persists across view navigation since this state lives in App.
  const startUpload = useCallback(async (file: File) => {
    const localId = (crypto.randomUUID && crypto.randomUUID()) || String(Math.random())
    const xhr = new XMLHttpRequest()

    setUploads((prev) => [
      ...prev,
      { id: localId, filename: file.name, status: 'uploading', loaded: 0, total: file.size, xhr },
    ])

    // Register the upload server-side so it shows in Activity as 'running'
    let serverJobId: string | null = null
    try {
      const job = await api.uploadStart(file.name)
      serverJobId = job.id
    } catch { /* tracking is non-fatal */ }

    const update = (patch: Partial<Upload>) =>
      setUploads((prev) => prev.map((u) => (u.id === localId ? { ...u, ...patch } : u)))
    const remove = () =>
      setUploads((prev) => prev.filter((u) => u.id !== localId))
    const finishServerJob = (error?: string) => {
      if (serverJobId) api.uploadFinish(serverJobId, error).catch(() => {})
    }

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) update({ loaded: e.loaded, total: e.total })
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        finishServerJob()
        update({ status: 'success', xhr: undefined })
        setListVersion((v) => v + 1)
        setTimeout(remove, 4000)  // success banner auto-dismisses
      } else {
        let detail = `${xhr.status} ${xhr.statusText}`
        try {
          const body = JSON.parse(xhr.responseText)
          if (body?.detail) detail = body.detail
        } catch {}
        finishServerJob(detail)
        update({ status: 'failed', error: detail, xhr: undefined })
      }
    }
    xhr.onerror = () => {
      finishServerJob('Network error or upload aborted')
      update({ status: 'failed', error: 'Network error or upload aborted', xhr: undefined })
    }
    xhr.onabort = () => {
      finishServerJob('Cancelled by user')
      remove()
    }

    xhr.open('POST', '/api/sermons/upload')
    xhr.withCredentials = true
    const fd = new FormData()
    fd.append('file', file)
    xhr.send(fd)
  }, [])

  const cancelUpload = useCallback((id: string) => {
    setUploads((prev) => {
      const u = prev.find((x) => x.id === id)
      if (u?.xhr) u.xhr.abort()
      return prev
    })
  }, [])

  const dismissUpload = useCallback((id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id))
  }, [])

  return (
    <div className="app">
      <header>
        <img src={logo} alt="Connect Community Church Hamilton" className="logo" />
        <div className="title">
          <strong>ConnectClips</strong>
          <span className="muted">sermon → vertical clips</span>
        </div>
        <div className="header-spacer" />
        {/* Identity badge — shows when Tailscale Serve forwarded the request */}
        {!me.anonymous && (
          <div className="identity-badge" title={me.login ?? ''}>
            Hi, <strong>{me.name || me.login}</strong>
          </div>
        )}
        {/* History: admin-only — shows last 200 actions across all users */}
        {me.admin && view.name !== 'history' && (
          <button className="secondary" onClick={() => setView({ name: 'history' })}>
            Activity
          </button>
        )}
        {/* Admin: pre-authorized via Tailscale identity, or unlock via password */}
        <AdminControls admin={me.admin} identityAdmin={!me.anonymous && me.admin} onChange={refreshMe} />
      </header>

      {/* App-global upload banners — one row per active/recent upload, persists across view navigation */}
      {uploads.map((u) => (
        u.status === 'uploading' ? (
          <div key={u.id} className="upload-banner uploading">
            <div className="upload-banner-text">
              Uploading <strong>{u.filename}</strong> —{' '}
              {Math.round(u.loaded / Math.max(1, u.total) * 100)}%
              <span className="muted">
                {' '}({(u.loaded / 1024 / 1024).toFixed(1)} /{' '}
                {(u.total / 1024 / 1024).toFixed(1)} MB)
              </span>
            </div>
            <progress value={u.loaded} max={u.total} />
            <button className="secondary" onClick={() => cancelUpload(u.id)}>Cancel</button>
          </div>
        ) : u.status === 'success' ? (
          <div key={u.id} className="upload-banner success">
            ✓ Uploaded <strong>{u.filename}</strong>. Transcribe + clip selection started in the background.
          </div>
        ) : (
          <div key={u.id} className="upload-banner failed">
            Upload failed for <strong>{u.filename}</strong>: {u.error}
            <button className="secondary" onClick={() => dismissUpload(u.id)}>Dismiss</button>
          </div>
        )
      ))}

      <main>
        {view.name === 'list' && (
          <SermonList
            key={listVersion}
            admin={me.admin}
            onOpen={(s) => setView({ name: 'detail', sermon: s })}
            onDeleted={() => setListVersion((v) => v + 1)}
            onUpload={startUpload}
            uploadActive={uploads.some((u) => u.status === 'uploading')}
          />
        )}
        {view.name === 'detail' && (
          <SermonDetail
            sermon={view.sermon}
            admin={me.admin}
            onBack={() => setView({ name: 'list' })}
            onTrim={(clip, clipIndex) =>
              setView({ name: 'trim', sermon: view.sermon, clip, clipIndex })
            }
            onDeleted={() => {
              setListVersion((v) => v + 1)
              setView({ name: 'list' })
            }}
          />
        )}
        {view.name === 'trim' && (
          <Trim
            sermon={view.sermon}
            clip={view.clip}
            clipIndex={view.clipIndex}
            onBack={async () => {
              const updated = await refreshSermon(view.sermon.name)
              setView({ name: 'detail', sermon: updated ?? view.sermon })
            }}
          />
        )}
        {view.name === 'history' && (
          <History onBack={() => setView({ name: 'list' })} />
        )}
      </main>
    </div>
  )
}

export default App
