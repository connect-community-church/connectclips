import type { ClipsFile, IdentitiesResponse, Job, Me, Sermon, Track, TranscriptWord, UsageResponse } from './types'

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
  getClips: (name: string) => jsonFetch<ClipsFile>(`/sermons/${encodeURIComponent(name)}/clips`),

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
  startSelectClips: (source: string, num_clips_min?: number, num_clips_max?: number) =>
    jsonFetch<Job>('/jobs/select-clips', {
      method: 'POST',
      body: JSON.stringify({ source, num_clips_min, num_clips_max }),
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
  ) =>
    jsonFetch<Job>('/jobs/export-clip', {
      method: 'POST',
      body: JSON.stringify({
        source, clip_index, start_override, end_override, caption_style,
        include_hook_title, caption_margin_v, identity_id,
      }),
    }),

  // Preview-pane support — see backend/app/services/reframe.track_for_clip.
  // After the source-level prescan lands during ingest, this is a near-instant
  // slice. The first call on a pre-prescan source falls back to a full scan.
  getClipTrack: (source: string, start: number, end: number, identity_id?: number | null) => {
    const id = identity_id == null ? '' : `&identity_id=${identity_id}`
    return jsonFetch<Track>(
      `/sermons/${encodeURIComponent(source)}/clip-track?start=${start}&end=${end}${id}`,
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
