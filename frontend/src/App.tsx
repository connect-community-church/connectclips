import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api'
import { SermonList } from './views/SermonList'
import { SermonDetail } from './views/SermonDetail'
import { Trim } from './views/Trim'
import { AdminControls } from './views/AdminControls'
import { History } from './views/History'
import type { Clip, Me, Sermon } from './types'
import logo from './assets/connectclips-banner.png'
import './App.css'

type View =
  | { name: 'list' }
  | { name: 'detail'; sermon: Sermon }
  | { name: 'trim'; sermon: Sermon; clip: Clip; clipIndex: number }
  | { name: 'history' }

// Parsed-from-URL form. Doesn't carry the full sermon/clip object — those
// come from the API on hydration.
type Route =
  | { name: 'list' }
  | { name: 'detail'; sermonName: string }
  | { name: 'trim'; sermonName: string; clipIndex: number }
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

// History-API routing. The backend serves index.html for any path that
// isn't under /api or /files (SPAStaticFiles falls back on 404), so deep
// links survive a refresh and the URL bar shows clean paths instead of
// `#/sermons/...`. Back/forward buttons fire `popstate`, which we listen
// to for cross-history hydration.
function buildPath(view: View): string {
  switch (view.name) {
    case 'list':    return '/'
    case 'history': return '/history'
    case 'detail':  return `/sermons/${encodeURIComponent(view.sermon.name)}`
    case 'trim':    return `/sermons/${encodeURIComponent(view.sermon.name)}/clip/${view.clipIndex}`
  }
}

function parsePath(pathname: string): Route {
  if (pathname === '' || pathname === '/') return { name: 'list' }
  if (pathname === '/history') return { name: 'history' }
  const trim = pathname.match(/^\/sermons\/([^/]+)\/clip\/(\d+)\/?$/)
  if (trim) {
    return { name: 'trim', sermonName: decodeURIComponent(trim[1]), clipIndex: parseInt(trim[2], 10) }
  }
  const detail = pathname.match(/^\/sermons\/([^/]+)\/?$/)
  if (detail) {
    return { name: 'detail', sermonName: decodeURIComponent(detail[1]) }
  }
  return { name: 'list' }
}

// True iff the route encoded in the URL matches the view we're rendering.
// We compare so that programmatic `navigate()` (which also updates the hash)
// doesn't trigger a redundant re-hydrate via the hashchange listener.
function routeMatchesView(route: Route, view: View): boolean {
  if (route.name === 'list' && view.name === 'list') return true
  if (route.name === 'history' && view.name === 'history') return true
  if (route.name === 'detail' && view.name === 'detail') {
    return route.sermonName === view.sermon.name
  }
  if (route.name === 'trim' && view.name === 'trim') {
    return route.sermonName === view.sermon.name && route.clipIndex === view.clipIndex
  }
  return false
}

function App() {
  const [view, setView] = useState<View>({ name: 'list' })
  const [me, setMe] = useState<Me>(ANON)
  const [listVersion, setListVersion] = useState(0)
  const [uploads, setUploads] = useState<Upload[]>([])
  // Set true while we're resolving a non-default URL into a View — we
  // need to fetch the sermon (and clip, for trim) from the API before we
  // can render. Without this the user sees a flash of the sermon list
  // before the hydrated view replaces it.
  const [hydrating, setHydrating] = useState(() => parsePath(window.location.pathname).name !== 'list')
  const [hydrateError, setHydrateError] = useState<string | null>(null)

  const refreshMe = useCallback(() => {
    api.me().then(setMe).catch(() => setMe(ANON))
  }, [])

  useEffect(() => {
    refreshMe()
  }, [refreshMe])

  // viewRef keeps a stable reference to the current view for use inside the
  // hashchange listener (which is registered once with [] deps).
  const viewRef = useRef(view)
  useEffect(() => { viewRef.current = view }, [view])

  // Resolve a parsed Route → fully hydrated View by fetching the sermon and
  // (for trim) clip from the API. On miss (sermon deleted, clip index out
  // of range, network error) falls back to the closest valid view.
  const hydrateRoute = useCallback(async (route: Route): Promise<View> => {
    if (route.name === 'list')    return { name: 'list' }
    if (route.name === 'history') return { name: 'history' }

    const sermons = await api.listSermons()
    const sermon = sermons.find((s) => s.name === route.sermonName)
    if (!sermon) {
      throw new Error(`Sermon not found: ${route.sermonName}`)
    }
    if (route.name === 'detail') {
      return { name: 'detail', sermon }
    }
    // trim
    const clipsFile = await api.getClips(sermon.name)
    const clip = clipsFile.clips[route.clipIndex]
    if (!clip) {
      // Clip index out of range — clips.json was regenerated since the URL
      // was bookmarked. Drop to the sermon detail so the user can pick again.
      return { name: 'detail', sermon }
    }
    return { name: 'trim', sermon, clip, clipIndex: route.clipIndex }
  }, [])

  // Mount: read URL, hydrate. Subscribe to popstate so the browser
  // back/forward buttons actually navigate (otherwise back would change
  // the URL but leave the view in place).
  useEffect(() => {
    let cancelled = false
    const hydrateFromUrl = async () => {
      const route = parsePath(window.location.pathname)
      if (routeMatchesView(route, viewRef.current)) return  // programmatic nav, already in sync
      setHydrating(true)
      setHydrateError(null)
      try {
        const next = await hydrateRoute(route)
        if (cancelled) return
        setView(next)
        // If hydration fell back (sermon missing, clip OOR), update the
        // URL to match the actual view so refreshing again is consistent.
        const expected = buildPath(next)
        if (expected !== window.location.pathname) {
          window.history.replaceState(null, '', expected + window.location.search)
        }
      } catch (e) {
        if (cancelled) return
        setHydrateError(String(e instanceof Error ? e.message : e))
        setView({ name: 'list' })
        window.history.replaceState(null, '', '/' + window.location.search)
      } finally {
        if (!cancelled) setHydrating(false)
      }
    }
    hydrateFromUrl()
    const onPopState = () => hydrateFromUrl()
    window.addEventListener('popstate', onPopState)
    return () => {
      cancelled = true
      window.removeEventListener('popstate', onPopState)
    }
  }, [hydrateRoute])

  // navigate(): the only way to change views. Updates state synchronously,
  // then pushes a new history entry if the target path differs from the
  // current one (so back/forward retraces the user's navigation).
  const navigate = useCallback((next: View) => {
    setView(next)
    const target = buildPath(next)
    if (target === window.location.pathname) return
    window.history.pushState(null, '', target + window.location.search)
  }, [])

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
    <>
      {/* Full-viewport-width banner. The banner image is the BACKGROUND
          of this strip (set inline so Vite resolves the imported asset
          URL). The home-link button overlays the banner-image area on
          the left ~75 %; UI controls sit on the right side, above the
          empty white right zone of the banner. The banner-bar lives
          OUTSIDE .app so it spans the full viewport instead of being
          capped by the .app max-width. */}
      <div
        className="banner-bar"
        style={{ backgroundImage: `url(${logo})` }}
      >
        <button
          type="button"
          className="banner-home-zone"
          onClick={() => navigate({ name: 'list' })}
          title="Back to sermon list"
          aria-label="ConnectClips home"
        />
        <div className="banner-controls">
          {/* Identity badge — shows when Tailscale Serve forwarded the request */}
          {!me.anonymous && (
            <div className="identity-badge" title={me.login ?? ''}>
              Hi, <strong>{me.name || me.login}</strong>
            </div>
          )}
          {/* History: admin-only — shows last 200 actions across all users */}
          {me.admin && view.name !== 'history' && (
            <button className="secondary" onClick={() => navigate({ name: 'history' })}>
              Activity
            </button>
          )}
          {/* Admin: pre-authorized via Tailscale identity, or unlock via password */}
          <AdminControls admin={me.admin} identityAdmin={!me.anonymous && me.admin} onChange={refreshMe} />
        </div>
      </div>
    <div className="app">

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
        {hydrateError && (
          <div className="error" style={{ marginBottom: 12 }}>
            Couldn't open that link: {hydrateError}
          </div>
        )}
        {hydrating ? (
          <div className="muted" style={{ padding: 24 }}>Loading…</div>
        ) : (
          <>
            {view.name === 'list' && (
              <SermonList
                key={listVersion}
                admin={me.admin}
                onOpen={(s) => navigate({ name: 'detail', sermon: s })}
                onDeleted={() => setListVersion((v) => v + 1)}
                onUpload={startUpload}
                uploadActive={uploads.some((u) => u.status === 'uploading')}
              />
            )}
            {view.name === 'detail' && (
              <SermonDetail
                sermon={view.sermon}
                admin={me.admin}
                onBack={() => navigate({ name: 'list' })}
                onTrim={(clip, clipIndex) =>
                  navigate({ name: 'trim', sermon: view.sermon, clip, clipIndex })
                }
                onDeleted={() => {
                  setListVersion((v) => v + 1)
                  navigate({ name: 'list' })
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
                  navigate({ name: 'detail', sermon: updated ?? view.sermon })
                }}
              />
            )}
            {view.name === 'history' && (
              <History onBack={() => navigate({ name: 'list' })} />
            )}
          </>
        )}
      </main>
    </div>
    </>
  )
}

export default App
