import { useEffect, useRef, useState } from 'react'

type StyleEntry = { key: string; label: string }

type Props = {
  styles: StyleEntry[]
  value: string
  onChange: (key: string) => void
}

/** Custom dropdown showing each caption style as a live-animated mini preview.
 *  The preview's visuals are hardcoded to mirror backend STYLES — keep in
 *  sync with backend/app/services/captions.py. */
export function CaptionStylePicker({ styles, value, onChange }: Props) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef<HTMLDivElement | null>(null)

  // Close on outside click or Escape
  useEffect(() => {
    if (!open) return
    const onClick = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', onClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const selected = styles.find((s) => s.key === value) ?? styles[0]

  return (
    <div className="cs-picker" ref={wrapRef}>
      <button
        type="button"
        className="cs-trigger"
        onClick={() => setOpen((o) => !o)}
        title={selected?.label}
      >
        <CaptionPreview styleKey={selected?.key ?? 'classic'} small />
        <span className="cs-trigger-label">{selected?.label ?? 'Caption style'}</span>
        <span className="cs-caret">▼</span>
      </button>
      {open && (
        <div className="cs-popover" role="listbox">
          {styles.map((s) => (
            <button
              key={s.key}
              type="button"
              className={`cs-option ${s.key === value ? 'selected' : ''}`}
              onClick={() => { onChange(s.key); setOpen(false) }}
              role="option"
              aria-selected={s.key === value}
            >
              <CaptionPreview styleKey={s.key} />
              <div className="cs-option-label">{s.label}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** A short mock that animates the highlight across a few sample words.
 *  The visuals are class-driven — see App.css `.cp.style-{key}` rules. */
function CaptionPreview({ styleKey, small = false }: { styleKey: string; small?: boolean }) {
  const isWordPop = styleKey === 'word_pop'
  return (
    <div className={`cp ${small ? 'cp-small' : ''} style-${styleKey}`}>
      <div className="cp-frame">
        {isWordPop ? (
          <div className="cp-word-pop">
            <span className="cp-word w1">HELLO</span>
            <span className="cp-word w2">FRIENDS</span>
            <span className="cp-word w3">PREVIEW</span>
          </div>
        ) : (
          <div className="cp-line">
            <span className="cp-word w1">Hello</span>
            {' '}<span className="cp-word w2">there</span>
            {' '}<span className="cp-word w3">preview</span>
          </div>
        )}
      </div>
    </div>
  )
}
