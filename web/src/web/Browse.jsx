import { Fragment, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ProgressRing from '../shared/ProgressRing'
import { DownloadIcon, Icon, PlayIcon } from '../shared/icons'
import { liveFor, titleState } from '../shared/titleState'
import { BrowseSkeleton, GridSkeleton } from './Skeleton'
import Tile from './Tile'
import { ClipsRow } from './Clips'

export default function Browse({ section, shell }) {
  const [feed, setFeed] = useState(null)
  const [error, setError] = useState(null)
  const typed = Boolean(section.mediaType) && section.id !== 'library'
  const [genre, setGenre] = useState(null)

  useEffect(() => {
    let alive = true
    setFeed(null)
    api
      .home(section.mediaType)
      .then((data) => alive && setFeed(data))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [section.mediaType])

  const head = typed && (
    <BrowseHead
      title={section.mediaType === 'tv' ? 'TV Shows' : 'Movies'}
      mediaType={section.mediaType}
      genre={genre}
      onGenre={setGenre}
      over={!genre}
    />
  )

  if (genre) {
    return (
      <div className="browse">
        {head}
        <GenreGrid genre={genre} mediaType={section.mediaType} shell={shell} />
      </div>
    )
  }
  if (error) return <p className="note error">{error}</p>
  if (!feed) return <div className="browse">{head}<BrowseSkeleton hero={section.id !== 'library'} /></div>

  const rows = section.id === 'library'
    ? feed.rows.filter((row) => ['continue', 'mylist', 'library'].includes(row.kind))
    : feed.rows
  const clipsAfter = Math.max(
    rows.findIndex((row) => row.kind === 'mylist'),
    rows.findIndex((row) => row.kind === 'continue'),
    0,
  )

  return (
    <div className="browse">
      {head}
      {feed.hero && section.id !== 'library' && <Hero card={feed.hero} shell={shell} />}
      <div className="rows">
        {rows.map((row, index) => (
          <Fragment key={row.id}>
          <Row
            row={row}
            shell={shell}
            onSeeAll={section.id === 'library' && row.kind === 'mylist'
              ? () => shell.go({ screen: 'home', section: 'mylist' })
              : null}
          />
          {section.id === 'library' && index === clipsAfter && <ClipsRow shell={shell} />}
          </Fragment>
        ))}
        {!rows.length && (
          <p className="note">
            Nothing here yet. Search for something and press Download.
          </p>
        )}
      </div>
    </div>
  )
}

function BrowseHead({ title, mediaType, genre, onGenre, over }) {
  const [genres, setGenres] = useState([])
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    let alive = true
    api.genres(mediaType, 'name').then((rows) => alive && setGenres(rows)).catch(() => {})
    return () => {
      alive = false
    }
  }, [mediaType])

  useEffect(() => {
    if (!open) return undefined
    const away = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false)
    }
    const escape = (event) => event.key === 'Escape' && setOpen(false)
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', escape)
    }
  }, [open])

  const choose = (name) => {
    onGenre(name)
    setOpen(false)
    window.scrollTo({ top: 0 })
  }

  return (
    <div className={`browse-head ${over ? 'over' : ''}`}>
      {genre ? (
        <button className="browse-crumb" onClick={() => choose(null)}>{title}</button>
      ) : (
        <h1>{title}</h1>
      )}
      {genre && <span className="browse-crumb-sep" aria-hidden="true">›</span>}
      {genre && <h1>{genre}</h1>}
      <div className="genre-menu-wrap" ref={ref}>
        <button
          className={`genre-button ${open ? 'open' : ''}`}
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          aria-haspopup="listbox"
        >
          {genre ? 'Change' : 'Genres'}
          <Icon name="chevron-down" size={14} />
        </button>
        {open && (
          <div className="genre-menu" role="listbox">
            {genre && (
              <button className="genre-all" onClick={() => choose(null)}>All {title}</button>
            )}
            <div className="genre-columns">
              {genres.map((g) => (
                <button
                  key={g.name}
                  role="option"
                  aria-selected={g.name === genre}
                  className={g.name === genre ? 'on' : ''}
                  onClick={() => choose(g.name)}
                >
                  {g.name}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

function GenreGrid({ genre, mediaType, shell }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setItems(null)
    setError(null)
    api
      .browse({ genre, media_type: mediaType, sort: 'popular', limit: 120 })
      .then((page) => alive && setItems(page.items || []))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [genre, mediaType])

  return (
    <div className="genre-page">
      {error && <p className="note error">{error}</p>}
      {!items && !error && <GridSkeleton />}
      {items && !items.length && <p className="note">Nothing in {genre} yet.</p>}
      {items && items.length > 0 && (
        <div className="grid">
          {items.map((card) => (
            <Tile key={card.media_id ?? card.id} card={card} shell={shell} />
          ))}
        </div>
      )}
    </div>
  )
}

function Hero({ card, shell }) {
  const state = titleState(liveFor(card, shell.downloads), card)

  return (
    <section className="hero">
      {card.backdrop && <img className="hero-art" src={card.backdrop} alt="" />}
      <div className="hero-shade" />
      <div className="hero-body">
        <h1>{card.title}</h1>
        <div className="hero-meta">
          {card.vote_average > 0 && (
            <span className="score">{card.vote_average.toFixed(1)}</span>
          )}
          {card.year && <span>{card.year}</span>}
          {card.media_type === 'tv' && <span>Series</span>}
          {(card.genres || []).slice(0, 2).map((g) => (
            <span key={g}>{g}</span>
          ))}
        </div>
        {card.overview && <p className="hero-overview">{card.overview}</p>}
        <div className="hero-actions">
          {state.id === 'play' ? (
            <button
              className="btn primary"
              onClick={() =>
                // A show plays an episode, never its season pack; with none, its page offers one.
                card.media_type === 'tv' && !card.resume_play_id
                  ? shell.openTitle(card)
                  : shell.play(state.playId, card)
              }
            >
              <PlayIcon size={20} /> {state.label}
            </button>
          ) : state.busy ? (
            <button className="btn primary working" onClick={() => shell.openTitle(card)}>
              <ProgressRing
                size={20}
                stroke={3}
                percent={state.percent || 0}
                indeterminate={state.spin}
              />
              {state.label}
            </button>
          ) : (
            <button
              className="btn primary"
              onClick={() => shell.startDownload(card.primary_release_id)}
              disabled={!card.primary_release_id}
            >
              {state.id === 'failed' ? <Icon name="replay" size={20} /> : <DownloadIcon size={18} />}
              {' '}{state.label}
              {state.id === 'failed' && <span className="fail-badge corner" aria-label="Failed">!</span>}
            </button>
          )}
          <button className="btn quiet" onClick={() => shell.openTitle(card)}>
            Details <Icon name="chevron-down" size={18} className="btn-arrow" />
          </button>
        </div>
      </div>
    </section>
  )
}

function Row({ row, shell, onSeeAll = null }) {
  const strip = useRef(null)
  const [edges, setEdges] = useState({ left: false, right: false })

  const measure = () => {
    const el = strip.current
    if (!el) return
    setEdges({
      left: el.scrollLeft > 8,
      right: el.scrollLeft + el.clientWidth < el.scrollWidth - 8,
    })
  }

  useEffect(() => {
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [row])

  const nudge = (direction) => {
    const el = strip.current
    if (!el) return
    el.scrollBy({ left: direction * (el.clientWidth * 0.85), behavior: 'smooth' })
  }

  return (
    <section className="row">
      <div className="row-head">
        <h2>{row.title}</h2>
        {onSeeAll && (
          <a
            href="/my-list"
            className="row-more"
            onClick={(e) => {
              e.preventDefault()
              onSeeAll()
            }}
          >
            See All ›
          </a>
        )}
      </div>
      <div className="row-strip-wrap">
        {edges.left && (
          <button className="row-arrow left" onClick={() => nudge(-1)} aria-label="Scroll left">
            ‹
          </button>
        )}
        <div className="row-strip" ref={strip} onScroll={measure}>
          {row.items.map((card) => (
            <Tile
              key={`${row.id}-${card.media_id ?? card.id}`}
              card={card}
              shell={shell}
            />
          ))}
        </div>
        {edges.right && (
          <button className="row-arrow right" onClick={() => nudge(1)} aria-label="Scroll right">
            ›
          </button>
        )}
      </div>
    </section>
  )
}
