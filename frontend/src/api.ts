import type { AppSettings, ClipsFile, ClipTracks, ClipUserEdits, IdentitiesResponse, Job, Me, ReportingSummary, Sermon, SocialPost, Track, TranscriptWord, UsageResponse, YouTubeBackfillQueue } from './types'

async function jsonFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`/api${path}`, {
    credentials: 'include',  // carry the admin session cookie
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
  })
  if (!r.ok) {
    let detail = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (body?.detail) detail = body.detail
    } catch {}
    throw new Error(detail)
  }
  // Some DELETE/POST endpoints return JSON; some return empty bodies.
  const text = await r.text()
  return (text ? JSON.parse(text) : ({} as T))
}

export const api = {
  health: () => jsonFetch<{ status: string }>('/health'),

  listSermons: () => jsonFetch<Sermon[]>('/sermons'),
  getClips: (name: string, selection_mode: 'shorts' | 'deeper' = 'shorts') =>
    jsonFetch<ClipsFile>(`/sermons/${encodeURIComponent(name)}/clips?selection_mode=${selection_mode}`),

  listJobs: (limit = 200) => jsonFetch<Job[]>(`/jobs?limit=${limit}`),
  getJob: (id: string) => jsonFetch<Job>(`/jobs/${id}`),

  // Anthropic API usage / cost summary (admin-only).
  getUsage: () => jsonFetch<UsageResponse>('/usage'),
  addTopup: (amount_usd: number, note?: string, created_at?: string) =>
    jsonFetch<{ id: number; amount_usd: number; note: string | null; created_at: string }>(
      '/usage/topups',
      { method: 'POST', body: JSON.stringify({ amount_usd, note, created_at }) },
    ),
  deleteTopup: (id: number) =>
    jsonFetch<{ id: number; deleted: boolean }>(`/usage/topups/${id}`, { method: 'DELETE' }),

  startTranscribe: (source: string) =>
    jsonFetch<Job>('/jobs', { method: 'POST', body: JSON.stringify({ source }) }),
  startSelectClips: (source: string, num_clips_min?: number, num_clips_max?: number, selection_mode: 'shorts' | 'deeper' = 'shorts') =>
    jsonFetch<Job>('/jobs/select-clips', {
      method: 'POST',
      body: JSON.stringify({ source, num_clips_min, num_clips_max, selection_mode }),
    }),
  startExportClip: (
    source: string,
    clip_index: number,
    start_override?: number,
    end_override?: number,
    caption_style?: string,
    include_hook_title?: boolean,
    caption_margin_v?: number | null,
    identity_id?: number | null,
    zoom_level?: string | null,
    lock_camera?: boolean,
    panels?: number[] | null,
    selection_mode: 'shorts' | 'deeper' = 'shorts',
  ) =>
    jsonFetch<Job>('/jobs/export-clip', {
      method: 'POST',
      body: JSON.stringify({
        source, clip_index, start_override, end_override, caption_style,
        include_hook_title, caption_margin_v, identity_id, zoom_level,
        lock_camera, panels, selection_mode,
      }),
    }),

  // Persist the volunteer's per-clip edits so they survive page navigation.
  // The Trim view debounces calls to this on every input change.
  saveClipOverride: (source: string, clip_index: number, edits: ClipUserEdits) =>
    jsonFetch<{ saved: boolean }>(
      `/sermons/${encodeURIComponent(source)}/clips/${clip_index}/overrides`,
      { method: 'PUT', body: JSON.stringify(edits) },
    ),
  resetClipOverride: (source: string, clip_index: number) =>
    jsonFetch<{ deleted: boolean }>(
      `/sermons/${encodeURIComponent(source)}/clips/${clip_index}/overrides`,
      { method: 'DELETE' },
    ),

  // Preview-pane support — see backend/app/services/reframe.track_for_clip.
  // After the source-level prescan lands during ingest, this is a near-instant
  // slice. The first call on a pre-prescan source falls back to a full scan.
  getClipTrack: (
    source: string, start: number, end: number,
    identity_id?: number | null,
    zoom_level?: string | null,
    lock_camera?: boolean,
  ) => {
    const id = identity_id == null ? '' : `&identity_id=${identity_id}`
    const zl = zoom_level == null ? '' : `&zoom_level=${encodeURIComponent(zoom_level)}`
    const lc = lock_camera ? '&lock_camera=true' : ''
    return jsonFetch<Track>(
      `/sermons/${encodeURIComponent(source)}/clip-track?start=${start}&end=${end}${id}${zl}${lc}`,
    )
  },

  // Split-screen preview: per-panel crop tracks for an ordered list of
  // speaker identities (2+). Mirrors getClipTrack but returns one track per
  // stacked panel so the preview canvas can draw the composite.
  getClipTracks: (
    source: string, start: number, end: number,
    panels: number[],
    zoom_level?: string | null,
    lock_camera?: boolean,
  ) => {
    const zl = zoom_level == null ? '' : `&zoom_level=${encodeURIComponent(zoom_level)}`
    const lc = lock_camera ? '&lock_camera=true' : ''
    return jsonFetch<ClipTracks>(
      `/sermons/${encodeURIComponent(source)}/clip-tracks?start=${start}&end=${end}&panels=${panels.join(',')}${zl}${lc}`,
    )
  },

  // Identities tracked across the source. Returns scanned=false when prescan
  // hasn't run yet — callers can poll while the prescan job completes.
  getIdentities: (source: string) =>
    jsonFetch<IdentitiesResponse>(`/sermons/${encodeURIComponent(source)}/identities`),

  // Word-level transcript timings within a range — drives the JS caption
  // overlay. Returns clip-relative offsets so the renderer can compare
  // directly against (videoEl.currentTime - clip.start).
  getTranscriptWords: (source: string, start: number, end: number) =>
    jsonFetch<{ start: number; end: number; words: TranscriptWord[] }>(
      `/sermons/${encodeURIComponent(source)}/transcript-words?start=${start}&end=${end}`,
    ),

  captionStyles: () => jsonFetch<{ styles: { key: string; label: string }[]; default: string }>('/caption-styles'),

  // Per-deployment publish targets -- which channel/page each platform's
  // upload deep-link should point at. GET is open (the Publish view reads
  // it on every clip page); PUT is admin-only.
  getPublishTargets: () =>
    jsonFetch<{ youtube_channel_id?: string; facebook_page_id?: string }>('/publish-targets'),
  savePublishTargets: (body: { youtube_channel_id?: string; facebook_page_id?: string }) =>
    jsonFetch<{ youtube_channel_id?: string; facebook_page_id?: string }>(
      '/publish-targets',
      { method: 'PUT', body: JSON.stringify(body) },
    ),

  // Admin-tunable clip-selection settings (thinking effort, output ceiling,
  // clip count range). GET is open (Settings view reads it); PUT is admin-only.
  getAppSettings: () => jsonFetch<AppSettings>('/app-settings'),
  saveAppSettings: (body: Partial<AppSettings>) =>
    jsonFetch<AppSettings>('/app-settings', { method: 'PUT', body: JSON.stringify(body) }),

  // Per-sermon metadata -- currently just the full-sermon YouTube URL that
  // each clip's "watch from this moment" deep link points at. GET is open;
  // PUT is admin-only. Backend validates that the URL parses to a YouTube
  // video ID and returns it as program_video_id for the frontend to use.
  getSermonMeta: (name: string) =>
    jsonFetch<{ program_video_url: string | null; program_video_id: string | null }>(
      `/sermons/${encodeURIComponent(name)}/meta`,
    ),
  saveSermonMeta: (name: string, body: { program_video_url: string | null }) =>
    jsonFetch<{ program_video_url: string | null; program_video_id: string | null }>(
      `/sermons/${encodeURIComponent(name)}/meta`,
      { method: 'PUT', body: JSON.stringify(body) },
    ),

  uploadStart: (filename: string) =>
    jsonFetch<Job>('/jobs/upload-start', { method: 'POST', body: JSON.stringify({ filename }) }),
  uploadFinish: (job_id: string, error?: string) =>
    jsonFetch<Job>('/jobs/upload-finish', { method: 'POST', body: JSON.stringify({ job_id, error }) }),

  startYoutubeDownload: (url: string) =>
    jsonFetch<Job>('/sermons/youtube', { method: 'POST', body: JSON.stringify({ url }) }),

  uploadSermon: async (file: File): Promise<{ name: string; size_bytes: number }> => {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch('/api/sermons/upload', { method: 'POST', body: fd, credentials: 'include' })
    if (!r.ok) {
      let detail = `${r.status} ${r.statusText}`
      try {
        const body = await r.json()
        if (body?.detail) detail = body.detail
      } catch {}
      throw new Error(detail)
    }
    return r.json()
  },

  me: () => jsonFetch<Me>('/auth/me'),

  // Admin
  adminStatus: () => jsonFetch<{ admin: boolean }>('/auth/admin/status'),
  enterAdmin: (password: string) =>
    jsonFetch<{ admin: boolean }>('/auth/admin/enter', {
      method: 'POST',
      body: JSON.stringify({ password }),
    }),
  exitAdmin: () => jsonFetch<{ admin: boolean }>('/auth/admin/exit', { method: 'POST' }),


  // Reporting
  listPosts: (opts: { limit?: number; sermon_source?: string; clip_index?: number } = {}) => {
    const q = new URLSearchParams()
    q.set('limit', String(opts.limit ?? 500))
    if (opts.sermon_source != null) q.set('sermon_source', opts.sermon_source)
    if (opts.clip_index != null) q.set('clip_index', String(opts.clip_index))
    return jsonFetch<{ posts: SocialPost[] }>('/reporting/posts?' + q.toString())
  },
  getReportingSummary: () =>
    jsonFetch<ReportingSummary>('/reporting/summary'),
  logPost: (body: {
    sermon_source?: string | null
    clip_index?: number | null
    post_url?: string | null
    posted_at?: string | null
    title?: string | null
  }) =>
    jsonFetch<{ id: number; created_at: string }>('/reporting/posts', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  logMissingUrlAttempt: (body: {
    sermon_source: string
    clip_index: number
    platform: string
    title?: string | null
  }) =>
    jsonFetch<{ id: string; created_at: string }>('/reporting/missing-url-attempt', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  refreshPost: (id: number) =>
    jsonFetch<{
      id: number
      post_id: number
      snapshot_at: string
      post_url: string
      stats: { views: number | null; likes: number | null; shares: number | null; comments: number | null }
    }>('/reporting/posts/' + id + '/refresh', { method: 'POST' }),
  deletePost: (id: number) =>
    jsonFetch<{ id: number; deleted: boolean }>('/reporting/posts/' + id, { method: 'DELETE' }),
  logMetrics: (
    postId: number,
    body: { views?: number | null; likes?: number | null; shares?: number | null; comments?: number | null; snapshot_at?: string | null },
  ) =>
    jsonFetch<{ id: number; post_id: number; snapshot_at: string }>(
      '/reporting/posts/' + postId + '/metrics',
      { method: 'POST', body: JSON.stringify(body) },
    ),
  importPostsCSV: async (file: File): Promise<{ imported: number; errors: string[] }> => {
    const fd = new FormData()
    fd.append('file', file)
    const r = await fetch('/api/reporting/import', { method: 'POST', body: fd, credentials: 'include' })
    if (!r.ok) {
      let detail = r.status + ' ' + r.statusText
      try { const b = await r.json(); if (b?.detail) detail = b.detail } catch {}
      throw new Error(detail)
    }
    return r.json()
  },

  youtubeStatus: () =>
    jsonFetch<{
      connected: boolean
      channel_id?: string | null
      channel_title?: string | null
      connected_by?: string | null
      connected_at?: string | null
    }>('/auth/youtube/status'),
  authorizeYoutube: () =>
    jsonFetch<{ url: string }>('/auth/youtube/authorize'),
  disconnectYoutube: () =>
    jsonFetch<{ connected: boolean }>('/auth/youtube/disconnect', { method: 'POST' }),
  publishYoutube: (body: {
    sermon_source: string
    clip_index: number
    filename: string
    title: string
    description?: string
    privacy_status?: 'public' | 'unlisted' | 'private'
  }) =>
    jsonFetch<{ id: number; video_id: string; post_url: string; created_at: string }>(
      '/publish/youtube',
      { method: 'POST', body: JSON.stringify(body) },
    ),


  getYoutubeBackfillQueue: () =>
    jsonFetch<YouTubeBackfillQueue>('/reporting/youtube-backfill'),
  approveYoutubeBackfill: (videoId: string, body: { sermon_source: string; clip_index: number }) =>
    jsonFetch<{ video_id: string; post_id: number | null; already_tracked?: boolean }>(
      `/reporting/youtube-backfill/${encodeURIComponent(videoId)}/approve`,
      { method: 'POST', body: JSON.stringify(body) },
    ),
  denyYoutubeBackfill: (videoId: string) =>
    jsonFetch<{ video_id: string; decision: string }>(
      `/reporting/youtube-backfill/${encodeURIComponent(videoId)}/deny`,
      { method: 'POST' },
    ),

  deleteSermon: (name: string) =>
    jsonFetch<{ name: string; removed: string[]; removed_count: number }>(
      `/sermons/${encodeURIComponent(name)}`,
      { method: 'DELETE' },
    ),
}

// Helper: file URLs (not under /api — proxy passes /files through directly)
export const fileUrl = {
  source: (name: string) => `/files/sources/${encodeURIComponent(name)}`,
  clip: (name: string) => `/files/clips/${encodeURIComponent(name)}`,
  identityThumb: (source: string, identityId: number) =>
    `/api/sermons/${encodeURIComponent(source)}/identities/${identityId}/thumb.png`,
}
