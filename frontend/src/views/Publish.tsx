import { useEffect, useState } from 'react'
import { api, fileUrl } from '../api'
import type { Clip, Sermon } from '../types'

type Props = {
  sermon: Sermon
  clip: Clip
  exportedFilename: string  // file inside data_clips_dir
}

// yt-dlp names files <title>-<videoid>.<ext>; the video id is 11 chars of [A-Za-z0-9_-]
function extractYoutubeId(sourceName: string): string | null {
  const m = sourceName.match(/-([A-Za-z0-9_-]{11})\.[^.]+$/)
  return m ? m[1] : null
}

function formatSermonDeepLink(sermon: Sermon, clip: Clip): string | null {
  const ytId = extractYoutubeId(sermon.name)
  if (!ytId) return null
  // youtu.be is shorter & cleaner; t param accepts seconds (as int)
  return `https://youtu.be/${ytId}?t=${Math.floor(clip.start)}`
}

// Build the platform list. When the admin has set a YouTube channel ID or
// Facebook Page ID via the Settings view, the corresponding platform deep-
// links to that specific channel / Page so the upload lands in the right
// place even if the volunteer is signed into multiple accounts. When unset,
// we fall back to today's generic upload pages -- post lands wherever the
// volunteer is signed in.
function buildPlatforms(t: { youtube_channel_id?: string; facebook_page_id?: string }) {
  const yt = t.youtube_channel_id?.trim()
  const fb = t.facebook_page_id?.trim()
  return [
    {
      key: 'youtube', label: 'YouTube', bg: '#ff0000',
      upload: yt
        ? `https://studio.youtube.com/channel/${encodeURIComponent(yt)}/videos/upload`
        : 'https://studio.youtube.com/',
    },
    { key: 'tiktok', label: 'TikTok', upload: 'https://www.tiktok.com/upload', bg: '#000000' },
    {
      key: 'facebook', label: 'Facebook', bg: '#1877f2',
      // Meta Business Suite Reels-create takes asset_id=<page-id>; without a
      // Page set we fall back to the generic personal Reels create page.
      upload: fb
        ? `https://business.facebook.com/latest/reels/create?asset_id=${encodeURIComponent(fb)}`
        : 'https://www.facebook.com/reel/create',
    },
    // Instagram's web Reels upload is gated; this is the canonical link, but mobile is the practical path.
    { key: 'instagram', label: 'Instagram', upload: 'https://www.instagram.com/reels/upload/', bg: '#e1306c' },
  ]
}

export function Publish({ sermon, clip, exportedFilename }: Props) {
  const [copied, setCopied] = useState<string | null>(null)
  const [platforms, setPlatforms] = useState(() => buildPlatforms({}))
  const deepLink = formatSermonDeepLink(sermon, clip)

  // Fetch publish targets once; rebuild the platform link list when they
  // arrive. If the fetch fails we keep the generic-link fallback we
  // initialized with -- a missing settings file is the same as "no overrides".
  useEffect(() => {
    api.getPublishTargets()
      .then((t) => setPlatforms(buildPlatforms(t)))
      .catch(() => { /* keep generic fallback */ })
  }, [])

  const copy = async (label: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(label)
      setTimeout(() => setCopied((c) => (c === label ? null : c)), 1500)
    } catch {
      // Some browsers block clipboard outside HTTPS / focused tab — fallback selection trick
      const ta = document.createElement('textarea')
      ta.value = text
      document.body.appendChild(ta)
      ta.select()
      document.execCommand('copy')
      document.body.removeChild(ta)
      setCopied(label)
      setTimeout(() => setCopied((c) => (c === label ? null : c)), 1500)
    }
  }

  return (
    <div className="publish">
      <h3>Publish</h3>
      <div className="publish-actions">
        <a
          href={fileUrl.clip(exportedFilename)}
          download={exportedFilename}
          className="publish-btn primary"
        >
          ↓ Download MP4
        </a>
        <button
          className="publish-btn"
          onClick={() => copy('title', clip.title)}
        >
          {copied === 'title' ? '✓ copied' : 'Copy title'}
        </button>
        {deepLink && (
          <button
            className="publish-btn"
            onClick={() => copy('link', deepLink)}
            title="YouTube URL into the original sermon at this clip's timestamp"
          >
            {copied === 'link' ? '✓ copied' : 'Copy full-sermon link'}
          </button>
        )}
      </div>

      <div className="muted publish-hint">
        Download the clip, click a platform below to open its upload page, and drop the file in.
        {deepLink && ' Use the full-sermon link for the YouTube Short\'s "Related video" field.'}
      </div>

      <div className="platform-buttons">
        {platforms.map((p) => (
          <a
            key={p.key}
            href={p.upload}
            target="_blank"
            rel="noopener noreferrer"
            className="platform-btn"
            style={{ background: p.bg }}
          >
            {p.label}
          </a>
        ))}
      </div>

      {deepLink && (
        <details className="publish-deeplink">
          <summary className="muted">full-sermon link preview</summary>
          <code>{deepLink}</code>
        </details>
      )}
    </div>
  )
}
