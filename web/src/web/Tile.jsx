import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import ProgressRing from '../shared/ProgressRing'
import { DownloadIcon, MyListIcon, PlayIcon } from '../shared/icons'

// Hover delay before the card grows, so sweeping across a row does not set off every tile.
const HOVER_DELAY = 450
const GROW = 1.3
const EDGE = 16

const canHover = () =>
  typeof window !== 'undefined' && window.matchMedia?.('(hover: hover)').matches

function stateOf(card, live) {
  const dl = live || card.download
  const ready = Boolean(dl && dl.playable)
  const active = Boolean(dl && ['downloading', 'adding', 'requested'].includes(dl.state))
  const preparing = Boolean(dl && dl.preparing)
  // A ready film plays its download; a show's is a season pack, no one file.
  const playId = card.resume_play_id || (ready && card.media_type !== 'tv' && dl.id)
  return { dl, ready, active, preparing, playId: playId ? String(playId) : null }
}

function Art({ card, children }) {
  const still = card.backdrop_small || card.backdrop
  return (
    <div className="tile-art">
      {still ? (
        <img className="tile-still" src={still} alt="" loading="lazy" />
      ) : card.poster ? (
        <img className="tile-still poster" src={card.poster} alt="" loading="lazy" />
      ) : null}
      {card.logo ? (
        <img className="tile-logo" src={card.logo} alt={card.title} loading="lazy" />
      ) : (
        <div className="tile-wordmark">{card.title}</div>
      )}
      {children}
    </div>
  )
}

function Progress({ card }) {
  const resume = card.resume_percent || 0
  if (resume <= 1) return null
  return (
    <div className="tile-resume">
      <span style={{ width: `${resume}%` }} />
    </div>
  )
}

export default function Tile({ card, shell }) {
  const live = shell.downloads[card.primary_release_id]
  const { dl, ready, active, preparing } = stateOf(card, live)
  const ref = useRef(null)
  const timer = useRef(null)
  const [hovered, setHovered] = useState(null)

  const close = useCallback(() => {
    clearTimeout(timer.current)
    setHovered(null)
  }, [])

  const enter = () => {
    if (!canHover()) return
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      const box = ref.current?.getBoundingClientRect()
      if (box) setHovered(box)
    }, HOVER_DELAY)
  }

  // The card is placed against where the tile was, so a scroll closes it.
  useEffect(() => {
    if (!hovered) return undefined
    window.addEventListener('scroll', close, true)
    window.addEventListener('resize', close)
    return () => {
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('resize', close)
    }
  }, [hovered, close])

  useEffect(() => () => clearTimeout(timer.current), [])

  return (
    <article
      ref={ref}
      className="tile"
      onClick={() => {
        close()
        shell.openTitle(card, ref.current?.getBoundingClientRect())
      }}
      onMouseEnter={enter}
      onMouseLeave={() => clearTimeout(timer.current)}
      aria-label={card.title}
    >
      <Art card={card}>
        <div className="tile-badges">
          {card.best_resolution === '2160p' && <span className="chip uhd">4K</span>}
        </div>
        {ready && !active && <span className="tile-ready" title="Ready to play" />}

        {(active || preparing) && (
          <div className="tile-ring">
            <ProgressRing
              percent={active ? dl.percent || 0 : dl.prepare_percent || 0}
              size={48}
              stroke={4}
              label={active && dl.percent >= 1 ? `${Math.round(dl.percent)}%` : ''}
              indeterminate={
                preparing ? !dl.prepare_percent : dl.state !== 'downloading' || dl.percent < 1
              }
            />
          </div>
        )}

        {card.resume_label && <span className="tile-episode">{card.resume_label}</span>}
        <Progress card={card} />
      </Art>

      {hovered &&
        createPortal(
          <HoverCard card={card} shell={shell} anchor={hovered} onClose={close} />,
          document.body,
        )}
    </article>
  )
}

/*
 * Drawn on the page, not inside the row, which scrolls sideways and would clip it.
 * Kept inside the window, so tiles at the ends of a row grow inwards.
 */
function HoverCard({ card, shell, anchor, onClose }) {
  const live = shell.downloads[card.primary_release_id]
  const { dl, ready, active, preparing, playId } = stateOf(card, live)
  const [busy, setBusy] = useState(false)
  const cardRef = useRef(null)

  const width = anchor.width * GROW
  const centre = anchor.left + anchor.width / 2
  const left = Math.min(
    Math.max(EDGE, centre - width / 2),
    document.documentElement.clientWidth - EDGE - width,
  )
  const artHeight = (width * 9) / 16
  const top = anchor.top + window.scrollY - (artHeight - anchor.height) / 2
  const origin = `${((centre - left) / width) * 100}% 50%`

  const saved = shell.myList.has(card.media_id)
  const series = card.media_type === 'tv'

  const play = (event) => {
    event.stopPropagation()
    onClose()
    shell.play(playId, card)
  }

  const download = async (event) => {
    event.stopPropagation()
    if (series || !card.primary_release_id) {
      onClose()
      shell.openTitle(card)
      return
    }
    setBusy(true)
    try {
      await shell.startDownload(card.primary_release_id)
    } finally {
      setBusy(false)
    }
  }

  const open = (event) => {
    event.stopPropagation()
    const from = cardRef.current?.getBoundingClientRect()
    onClose()
    shell.openTitle(card, from)
  }

  const meta = [
    series ? (card.limited ? 'Limited Series' : null) : null,
    series && !card.limited && card.season_count
      ? `${card.season_count} Season${card.season_count === 1 ? '' : 's'}`
      : null,
    !series && card.runtime
      ? card.runtime >= 60
        ? `${Math.floor(card.runtime / 60)}h ${card.runtime % 60}m`
        : `${card.runtime}m`
      : null,
  ].filter(Boolean)
  const facts = [card.year, ...meta, card.complete ? 'Complete' : null, card.certification].filter(Boolean)
  const percent = dl && dl.percent ? Math.round(dl.percent) : 0
  const standing = active
    ? (percent >= 1 ? `Downloading ${percent}%` : 'Downloading')
    : preparing ? 'Preparing' : ready ? 'Ready' : null

  return (
    <div
      ref={cardRef}
      className="hover-card"
      style={{ left, top, width, transformOrigin: origin }}
      onMouseLeave={onClose}
      onClick={open}
    >
      <Art card={card}>
        <Progress card={card} />
      </Art>

      <div className="hover-body">
        <div className="hover-text">
          <div className="hover-title">{card.title}</div>
          <div className="hover-meta">
            {standing && (
              <span className={`hover-standing ${ready ? 'ready' : 'working'}`}>{standing}</span>
            )}
            {facts.map((part) => <span key={part}>{part}</span>)}
          </div>
        </div>
        <button
          className="hover-btn"
          onClick={(e) => { e.stopPropagation(); shell.toggleMyList(card.media_id) }}
          aria-label={saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
          title={saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
        >
          <MyListIcon saved={saved} size={18} />
        </button>
        {playId ? (
          <button className="hover-btn primary play" onClick={play} aria-label="Play" title="Play">
            <PlayIcon size={18} />
          </button>
        ) : ready ? (
          <button className="hover-btn primary play" onClick={open} aria-label="Choose an episode" title="Choose an episode">
            <PlayIcon size={18} />
          </button>
        ) : (
          <button
            className="hover-btn primary"
            onClick={download}
            disabled={busy || active || preparing}
            aria-label={series ? 'Episodes' : 'Download'}
            title={series ? 'Episodes' : 'Download'}
          >
            <DownloadIcon size={18} />
          </button>
        )}
      </div>
    </div>
  )
}
