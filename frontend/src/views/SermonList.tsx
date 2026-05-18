import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import type { Sermon } from '../types'
import { AddSermon } from './AddSermon'

type Props = {
  admin: boolean
  onOpen: (sermon: Sermon) => void
  onDeleted: () => void
  onUpload: (file: File) => void
  uploadActive: boolean
}

type SortKey = 'date-desc' | 'date-asc' | 'name-asc' | 'name-desc'

const SORT_STORAGE_KEY = 'connectclips.sermonSort'
const DEFAULT_SORT: SortKey = 'date-desc'

function isSortKey(v: string | null): v is SortKey {
  return v === 'date-desc' || v === 'date-asc' || v === 'name-asc' || v === 'name-desc'
}

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(0)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
}

function sortSermons(items: Sermon[], key: SortKey): Sermon[] {
  const sorted = [...items]
  switch (key) {
    case 'date-desc':
      sorted.sort((a, b) => b.modified_at.localeCompare(a.modified_at))
      break
    case 'date-asc':
      sorted.sort((a, b) => a.modified_at.localeCompare(b.modified_at))
      break
    case 'name-asc':
      sorted.sort((a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: 'base' }))
      break
    case 'name-desc':
      sorted.sort((a, b) => b.name.localeCompare(a.name, undefined, { numeric: true, sensitivity: 'base' }))
      break
  }
  return sorted
}

export function SermonList({ admin, onOpen, onDeleted, onUpload, uploadActive }: Props) {
  const [sermons, setSermons] = useState<Sermon[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>(() => {
    const stored = typeof window !== 'undefined' ? window.localStorage.getItem(SORT_STORAGE_KEY) : null
    return isSortKey(stored) ? stored : DEFAULT_SORT
  })

  const onSortChange = (v: SortKey) => {
    setSortKey(v)
    try { window.localStorage.setItem(SORT_STORAGE_KEY, v) } catch { /* ignore */ }
  }

  const sortedSermons = useMemo(
    () => (sermons ? sortSermons(sermons, sortKey) : null),
    [sermons, sortKey],
  )

  const refresh = useCallback(() => {
    api.listSermons().then(setSermons).catch((e) => setError(String(e)))
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const onDelete = async (e: React.MouseEvent, name: string) => {
    e.stopPropagation()
    if (!window.confirm(`Delete "${name}"?\n\nThis removes the source file, transcript, clips.json, and every exported MP4.`)) return
    setDeleting(name)
    setError(null)
    try {
      await api.deleteSermon(name)
      refresh()
      onDeleted()
    } catch (err) {
      setError(String(err))
    } finally {
      setDeleting(null)
    }
  }

  return (
    <div className="sermon-list">
      <h1>Sermons</h1>

      <AddSermon onAdded={refresh} onUpload={onUpload} uploadActive={uploadActive} />

      {error && <div className="error">Error: {error}</div>}
      {!sermons && !error && <div className="muted">Loading…</div>}
      {sermons && sermons.length === 0 && (
        <div className="empty">No sermons yet — add one above.</div>
      )}
      {sortedSermons && sortedSermons.length > 0 && (
        <>
          <div className="sermon-sort">
            <label htmlFor="sermon-sort-select">Sort</label>
            <select
              id="sermon-sort-select"
              value={sortKey}
              onChange={(e) => onSortChange(e.target.value as SortKey)}
            >
              <option value="date-desc">Date — newest first</option>
              <option value="date-asc">Date — oldest first</option>
              <option value="name-asc">Name — A to Z</option>
              <option value="name-desc">Name — Z to A</option>
            </select>
          </div>
          <ul>
            {sortedSermons.map((s) => (
            <li key={s.name} className="sermon-row" onClick={() => onOpen(s)}>
              <div className="name">{s.name}</div>
              <div className="meta">
                {formatSize(s.size_bytes)} · {new Date(s.modified_at).toLocaleString()}
              </div>
              <div className="badges">
                <span className={s.transcribed ? 'badge ok' : 'badge muted'}>
                  {s.transcribed ? '✓ transcribed' : 'not transcribed'}
                </span>
                <span className={s.clips_selected ? 'badge ok' : 'badge muted'}>
                  {s.clips_selected ? `✓ ${s.n_clips} clips` : 'no clips yet'}
                </span>
              </div>
              {admin && (
                <div className="row-actions">
                  <button
                    className="danger"
                    onClick={(e) => onDelete(e, s.name)}
                    disabled={deleting === s.name}
                  >
                    {deleting === s.name ? 'Deleting…' : 'Delete'}
                  </button>
                </div>
              )}
            </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
