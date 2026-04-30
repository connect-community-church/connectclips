export type Sermon = {
  name: string
  size_bytes: number
  modified_at: string
  transcribed: boolean
  clips_selected: boolean
  n_clips: number
}

export type PreviousExport = {
  filename: string
  start: number
  end: number
  exported_at: string | null
  by_name: string | null
}

export type Clip = {
  start: number
  end: number
  title: string
  rationale: string
  hook_score?: number
  hook_rationale?: string
  exported: boolean
  output_filename: string | null
  stale_export?: boolean
  previous_export?: PreviousExport | null
  last_exported_by_login: string | null
  last_exported_by_name: string | null
  last_exported_at: string | null
}

export type Track = {
  n_frames: number
  src_w: number
  src_h: number
  fps: number
  out_w: number
  out_h: number
  track: [number, number, number][]  // [cx, cy, crop_h] per source frame
}

export type Identity = {
  id: number
  n_samples: number
  first_frame: number
  last_frame: number
  score_max: number
  thumb_frame_idx: number
  thumb_box: { cx: number; cy: number; w: number; h: number }
}

export type IdentitiesResponse = {
  scanned: boolean
  identities: Identity[]
}

export type TranscriptWord = {
  text: string
  start: number  // clip-relative seconds (offset from the requested range start)
  end: number
}

export type Me = {
  login: string | null
  name: string | null
  profile_pic: string | null
  admin: boolean
  anonymous: boolean
}

export type ClipsFile = {
  source: string
  model: string
  created_at: string
  usage: Record<string, number>
  clips: Clip[]
}

export type JobStatus = 'queued' | 'running' | 'done' | 'failed'

export type Job = {
  id: string
  kind: 'transcribe' | 'youtube_download' | 'select_clips' | 'export_clip' | 'upload' | 'prescan_faces'
  status: JobStatus
  source: string | null
  transcript_path: string | null
  url: string | null
  ingested_filename: string | null
  clips_path: string | null
  clip_index: number | null
  start: number | null
  end: number | null
  output_clip_path: string | null
  identity_id: number | null
  user_login: string | null
  user_name: string | null
  progress_percent: number | null
  progress_message: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}
