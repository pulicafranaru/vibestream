import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Icon } from './icons'
import { t } from './i18n'
import { SUBTITLE_SIZES, SUBTITLE_STYLES, previewStyle } from './tracks'

// The player's Settings column. Every page is rows of pills: the TV walks them
// through the imperative handle, the browser clicks.
const PlayerSettings = forwardRef(function PlayerSettings({
  browser,
  subtitles,
  subtitleId,
  onSubtitle,
  audio,
  audioId,
  onAudio,
  appearance,
  onAppearance,
  statsShown,
  onStats,
  onPage,
  onClose,
  unit = 1,
}, ref) {
  const px = (n) => Math.round(n * Math.max(unit, 0.6))
  const [page, setPage] = useState('root')
  const [at, setAt] = useState({ row: 0, col: 0 })
  const listRef = useRef(null)
  const itemRefs = useRef({})

  const go = (next) => {
    setPage(next)
    setAt({ row: 0, col: 0 })
  }

  useEffect(() => {
    if (onPage) onPage(page)
  }, [page, onPage])
  useEffect(() => () => onPage && onPage(null), [onPage])

  const nameOf = (list, id, fallback) => {
    const found = list.find((x) => x.id === id)
    return found ? found.label : fallback
  }
  const sizeName = (SUBTITLE_SIZES.find((s) => s.id === appearance.size) || {}).label || ''
  const styleName = (SUBTITLE_STYLES.find((s) => s.id === appearance.style) || {}).label || ''

  let rows = []
  if (page === 'root') {
    rows = [
      [{ id: 'subtitles', kind: 'entry', icon: 'subtitles', label: t('Subtitles'),
        value: nameOf(subtitles, subtitleId || null, t('Off')), onPress: () => go('subtitles') }],
      [{ id: 'appearance', kind: 'entry', icon: 'gear', label: t('Subtitle Appearance'),
        value: `${t(sizeName)}, ${t(styleName)}`, onPress: () => go('appearance') }],
      [{ id: 'audio', kind: 'entry', icon: 'volume', label: t('Audio'),
        value: nameOf(audio, audioId, t('Default')), onPress: () => go('audio') }],
      [{ id: 'debug', kind: 'entry', icon: 'bug', label: t('Debug'),
        value: statsShown ? t('On') : t('Off'), onPress: () => go('debug') }],
    ]
  } else if (page === 'subtitles') {
    rows = subtitles.map((track) => [{
      id: `s-${track.id}`, kind: 'choice', label: track.label,
      chosen: (subtitleId || null) === track.id, onPress: () => onSubtitle(track.id),
    }])
  } else if (page === 'audio') {
    rows = audio.map((track) => [{
      id: `a-${track.id}`, kind: 'choice', label: track.label,
      chosen: audioId === track.id, onPress: () => onAudio(track.id),
    }])
  } else if (page === 'appearance') {
    rows = [
      SUBTITLE_SIZES.map((size) => ({
        id: `z-${size.id}`, kind: 'pill', label: t(size.label), chosen: appearance.size === size.id,
        onPress: () => onAppearance({ ...appearance, size: size.id }),
      })),
      SUBTITLE_STYLES.map((style) => ({
        id: `y-${style.id}`, kind: 'pill', label: t(style.label), chosen: appearance.style === style.id,
        onPress: () => onAppearance({ ...appearance, style: style.id }),
      })),
    ]
  } else if (page === 'debug') {
    rows = [
      [{ id: 'stats-off', kind: 'choice', label: t('Off'), chosen: !statsShown, onPress: () => onStats(false) }],
      [{ id: 'stats-on', kind: 'choice', label: t('On'), chosen: statsShown, onPress: () => onStats(true) }],
    ]
  }

  useEffect(() => {
    let row = 0
    let col = 0
    rows.forEach((items, r) => items.forEach((item, c) => {
      if (item.chosen && page !== 'appearance' && !row) {
        row = r
        col = c
      }
    }))
    setAt({ row, col })
    // Only on page change: choosing moves the tick, not the focus.
  }, [page])

  useEffect(() => {
    const list = listRef.current
    const el = itemRefs.current[`${at.row}-${at.col}`]
    if (!list || !el || browser) return
    const top = el.offsetTop - list.offsetTop
    if (top < list.scrollTop + 20) list.scrollTop = Math.max(0, top - 20)
    else if (top + el.offsetHeight > list.scrollTop + list.clientHeight - 20) {
      list.scrollTop = top + el.offsetHeight - list.clientHeight + 20
    }
  }, [at, browser])

  const back = () => {
    if (page === 'root') return false
    const from = page
    setPage('root')
    const index = ['subtitles', 'appearance', 'audio', 'debug'].indexOf(from)
    setAt({ row: Math.max(0, index), col: 0 })
    return true
  }

  useImperativeHandle(ref, () => ({
    onDirection(dir) {
      setAt((cur) => {
        if (dir === 'up' || dir === 'down') {
          const row = Math.max(0, Math.min(rows.length - 1, cur.row + (dir === 'down' ? 1 : -1)))
          return { row, col: Math.min(cur.col, (rows[row] || []).length - 1) }
        }
        const items = rows[cur.row] || []
        const col = Math.max(0, Math.min(items.length - 1, cur.col + (dir === 'right' ? 1 : -1)))
        return { row: cur.row, col }
      })
    },
    onEnter() {
      const item = (rows[at.row] || [])[at.col]
      if (item) item.onPress()
    },
    onBack: back,
  }))

  const title = {
    root: t('Settings'), subtitles: t('Subtitles'), appearance: t('Subtitle Appearance'),
    audio: t('Audio'), debug: t('Debug'),
  }[page]

  const isFocused = (r, c) => !browser && at.row === r && at.col === c
  const hover = (r, c) => (browser ? undefined : () => setAt({ row: r, col: c }))

  const pill = (item, r, c) => (
    <button
      key={item.id}
      type="button"
      ref={(el) => { itemRefs.current[`${r}-${c}`] = el }}
      className={[
        'ps-pill', item.kind, item.chosen ? 'chosen' : '', isFocused(r, c) ? 'focused' : '',
      ].join(' ')}
      onClick={() => { setAt({ row: r, col: c }); item.onPress() }}
      onMouseEnter={hover(r, c)}
    >
      {item.kind === 'entry' && <Icon name={item.icon} size={px(32)} className="ps-glyph" />}
      <span className="ps-text">
        <span className="ps-label">{item.label}</span>
        {item.value && <span className="ps-value">{item.value}</span>}
      </span>
      {item.kind === 'entry' && <Icon name="chevron-right" size={px(26)} className="ps-chevron" />}
      {item.kind === 'choice' && item.chosen && <Icon name="check" size={px(26)} className="ps-tick" />}
    </button>
  )

  return (
    <div className="ps">
      <div className="ps-header">
        {page !== 'root' && (
          <button type="button" className="ps-bare" onClick={back} aria-label={t('Back')}>
            <Icon name="arrow-left" size={px(36)} />
          </button>
        )}
        <h2>{title}</h2>
        <button type="button" className="ps-bare close" onClick={onClose} aria-label={t('Close')}>
          <Icon name="close" size={px(36)} />
        </button>
      </div>

      <div className="ps-list" ref={listRef}>
        {page === 'appearance' && (
          <div className="ps-sample">
            <span style={previewStyle(appearance, px(30))}>{t('This is how subtitles will look.')}</span>
          </div>
        )}
        {rows.map((items, r) => {
          const label = page === 'appearance' ? [t('Size'), t('Style')][r]
            : page === 'debug' && r === 0 ? t('Playback stats') : null
          return (
            <div key={`${page}-${r}`} className={`ps-row ${page === 'appearance' ? 'wrap' : ''}`}>
              {label && <div className="ps-section">{label}</div>}
              {items.map((item, c) => pill(item, r, c))}
            </div>
          )
        })}
      </div>
    </div>
  )
})

export default PlayerSettings
