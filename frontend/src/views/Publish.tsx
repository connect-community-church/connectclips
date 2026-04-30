import { useState } from 'react'
import { fileUrl } from '../api'
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

const PLATFORMS: { key: string; label: string; upload: string; bg: string }[] = [
  // YouTube Studio's upload flow lives in /channel/.../videos but requires a channel id;
  // /upload routes through the same flow without one.
  { key: 'youtube', label: 'YouTube', upload: 'https://studio.youtube.com/', bg: '#ff0000' },
  { key: 'tiktok', label: 'TikTok', upload: 'https://www.tiktok.com/upload', bg: '#000000' },
  { key: 'facebook', label: 'Facebook', upload: 'https://www.facebook.com/reel/create', bg: '#1877f2' },
  // Instagram's web Reels upload is gated; this is the canonical link, but mobile is the practical path.
  { key: 'instagram', label: 'Instagram', upload: 'https://www.instagram.com/reels/upload/', bg: '#e1306c' },
]

export function Publish({ sermon, clip, exportedFilename }: Props) {
  const [copied, setCopied] = useState<string | null>(null)
  const deepLink = formatSermonDeepLink(sermon, clip)

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
        {PLATFORMS.map((p) => (
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
