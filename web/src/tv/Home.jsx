import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { formatBytes, formatRuntime } from '../api'
import ProgressRing from './ProgressRing'
import TopNav, { NAV_ITEMS, navIndexOf } from './TopNav'
import { liveFor, titleState } from '../shared/titleState'
import { genreName, rowTitle, t, tp } from '../shared/i18n'
import { genreRGB } from '../shared/genreColors'
import { Icon } from './icons'
import { clamp, scrollPageTo, scrollRowTo, setPageScroll } from './navigation'
import { tilePoster, tileLogo } from './images'

// Home, Shows, Movies, My Library and genre pages. Focus is (row, column): the bar is row -1, the hero row 0.

const WORKING = ['downloading', 'adding', 'requested']

const sameDownload = (a, b) =>
  a === b || Boolean(a && b && a.state === b.state && a.percent === b.percent &&
    a.playable === b.playable && a.preparing === b.preparing)

export function metaBits(card, { seasons } = {}) {
  const bits = []
  bits.push(card.media_type === 'tv' ? t('Show') : t('Movie'))
  if (card.genres && card.genres.length) bits.push(genreName(card.genres[0]))
  if (card.year) bits.push(String(card.year))
  if (card.media_type === 'tv') {
    const count = seasons || card.season_count
    if (card.limited) bits.push(t('Limited Series'))
    else if (count) bits.push(tp('{n} Season', '{n} Seasons', count))
    if (card.complete) bits.push(t('Complete'))
  } else if (card.runtime) {
    bits.push(formatRuntime(card.runtime))
  }
  if (card.certification) bits.push(card.certification)
  return bits
}

export function timeLeft(card) {
  const runtime = card.runtime || 0
  const percent = card.resume_percent || 0
  if (!runtime || !percent) return null
  const minutes = Math.max(1, Math.round(runtime * (1 - percent / 100)))
  if (minutes < 60) return t('{n}m left', { n: minutes })
  return t('{h}h {m}m left', { h: Math.floor(minutes / 60), m: minutes % 60 })
}

// Memoised so a remote press redraws only the tiles that changed; tiles far off screen draw nothing (`drawn`).
const Tile = memo(
  function Tile({ card, focused, drawn, live, rowIndex, colIndex, onHover, onOpen, setRef }) {
    const dl = live || card.download
    const active = dl && WORKING.includes(dl.state)
    const preparing = dl && dl.preparing
    const resume = card.resume_percent || 0
    const wide = focused && (card.backdrop_small || card.backdrop)

    if (!drawn && !focused) {
      return <div className="tile" ref={(el) => setRef(rowIndex, colIndex, el)} />
    }

    return (
      <div
        className={`tile ${focused ? 'focused' : ''} ${wide ? 'wide' : ''}`}
        ref={(el) => setRef(rowIndex, colIndex, el)}
        onMouseEnter={() => onHover(rowIndex, colIndex)}
        onClick={() => onOpen(card)}
      >
        {wide ? (
          <>
            <img className="tile-still" src={card.backdrop_small || card.backdrop} alt="" />
            <div className="tile-still-shade" />
            {card.logo ? (
              <img className="tile-logo" src={tileLogo(card.logo)} alt="" />
            ) : (
              <div className="tile-name">{card.title}</div>
            )}
          </>
        ) : card.poster ? (
          <img src={tilePoster(card.poster)} alt="" />
        ) : (
          <div className="tile-fallback">{card.title}</div>
        )}

        {card.best_resolution === '2160p' && !wide && <span className="tile-chip uhd">4K</span>}
        {dl && dl.playable && !active && <span className="tile-ready" />}

        {(active || preparing) && (
          <div className="tile-ring">
            <ProgressRing
              percent={active ? dl.percent || 0 : 0}
              size={62}
              stroke={5}
              label={active ? `${Math.round(dl.percent || 0)}%` : ''}
              indeterminate={preparing || dl.state !== 'downloading' || !dl.percent}
            />
          </div>
        )}

        {!active && resume > 1 && (
          <div className="tile-resume">
            <span style={{ width: `${resume}%` }} />
          </div>
        )}
      </div>
    )
  },
  (a, b) =>
    a.card === b.card && a.focused === b.focused && a.drawn === b.drawn &&
    a.rowIndex === b.rowIndex && a.colIndex === b.colIndex &&
    a.onHover === b.onHover && a.onOpen === b.onOpen && a.setRef === b.setRef &&
    sameDownload(a.live, b.live),
)

function Caption({ card, row }) {
  if (!card) return <div className="row-caption" />
  if (row.id === 'continue') {
    const left = timeLeft(card)
    return (
      <div className="row-caption">
        <div className="cap-line">
          {card.resume_label
            ? `${card.resume_label.replace(':', ' ')}${card.resume_episode_name ? ` • ${card.resume_episode_name}` : ''}`
            : card.title}
        </div>
        {left && <div className="cap-strong">{left}</div>}
      </div>
    )
  }
  return (
    <div className="row-caption">
      <div className="cap-meta">{metaBits(card).join(' • ')}</div>
      {card.overview && <p className="cap-overview">{card.overview}</p>}
    </div>
  )
}

const Chips = memo(function Chips({ row, rowIndex, focusedCol, onHover, onOpen, setTileRef, setStripRef, setRowRef }) {
  return (
    <div className="row chips" ref={(el) => setRowRef(rowIndex, el)}>
      <div className="row-strip" ref={(el) => setStripRef(rowIndex, el)}>
        <div className="row-track">
        {row.items.map((genre, ci) => (
          <div
            key={genre.name}
            ref={(el) => setTileRef(rowIndex, ci, el)}
            className={`chip ${focusedCol === ci ? 'focused' : ''}`}
            style={{ '--genre': genreRGB(genre.name) }}
            onMouseEnter={() => onHover(rowIndex, ci)}
            onClick={() => onOpen(genre)}
          >
            {genreName(genre.name)}
          </div>
        ))}
        </div>
      </div>
    </div>
  )
})

// Computed from the index rather than measured: only the focused tile is wide, and measuring forced a layout every press.
let tileGeometry = null
function geometry() {
  if (tileGeometry) return tileGeometry
  const style = getComputedStyle(document.documentElement)
  const px = (name, fallback) => parseFloat(style.getPropertyValue(name)) || fallback
  tileGeometry = {
    tile: px('--tile-w', 268),
    wide: px('--tile-wide', 715),
    gap: px('--tile-gap', 14),
    pad: px('--safe-x', 72),
    view: document.documentElement.clientWidth || 1920,
  }
  return tileGeometry
}

const opensWide = (card) => Boolean(card && (card.backdrop_small || card.backdrop))

function rowShift(items, col, focused) {
  const g = geometry()
  const n = items.length
  const extra = focused && opensWide(items[col]) ? g.wide - g.tile : 0
  const total = g.pad * 2 + n * g.tile + Math.max(0, n - 1) * g.gap + extra
  return Math.max(0, Math.min(col * (g.tile + g.gap), total - g.view))
}

const DRAWN_BEFORE = 2
const DRAWN_AFTER = 10

// Rows slide with a GPU transform: scrolling a non-scrollable strip repaints it in full on webOS, every press.
const Row = memo(function Row({
  r, rowIndex, focusedCol, shift, downloads, live, onHoverTile, onOpen, setTileRef,
  setStripRef, setRowRef, onWheel, showTitle,
}) {
  const focusedCard = focusedCol >= 0 ? r.items[focusedCol] : null
  const g = geometry()
  const first = Math.floor(shift / (g.tile + g.gap))
  if (!live) {
    return (
      <div className="row" ref={(el) => setRowRef(rowIndex, el)}>
        <h2 className="row-title">{rowTitle(r)}</h2>
        <div className="row-strip placeholder" />
      </div>
    )
  }
  return (
    <div className={`row ${focusedCard ? 'current' : ''}`} ref={(el) => setRowRef(rowIndex, el)}>
      {showTitle && <h2 className="row-title">{rowTitle(r)}</h2>}
      <div className="row-strip" ref={(el) => setStripRef(rowIndex, el)} onWheel={(event) => onWheel(rowIndex, event)}>
        <div className="row-track" style={{ transform: `translateX(${-shift}px)` }}>
        {r.items.map((card, ci) => (
          <Tile
            key={`${card.media_id || card.primary_release_id}-${ci}`}
            card={card}
            focused={focusedCol === ci}
            drawn={ci >= first - DRAWN_BEFORE && ci <= first + DRAWN_AFTER}
            live={downloads[card.primary_release_id]}
            rowIndex={rowIndex}
            colIndex={ci}
            onHover={onHoverTile}
            onOpen={onOpen}
            setRef={setTileRef}
          />
        ))}
        </div>
      </div>
      {focusedCard && <Caption card={focusedCard} row={r} />}
    </div>
  )
})

// Where the viewer was, keyed by profile and section, so Back returns there.
const lastPosition = new Map()
const prefetched = new Set()
const positionKey = (profileId, section, genre) => `${profileId ?? 'none'}:${section}:${genre || ''}`

export default function Home({
  data,
  profile,
  downloads = {},
  totals = null,
  genres = [],
  loading,
  section,
  category = null,
  onNav,
  onOpen,
  onPlay,
  onMoreInfo,
  onGenre,
  onDownloads,
  onClose,
  registerHandler,
}) {
  const isMine = section === 'library' && !category
  const key = positionKey(profile?.id, section, category)
  const restored = useRef(lastPosition.get(key))
  const [row, setRow] = useState(restored.current?.row ?? 0)
  const [col, setCol] = useState(restored.current?.col ?? 0)
  const [heroCol, setHeroCol] = useState(0)
  const [navCol, setNavCol] = useState(navIndexOf(category ? 'home' : section))

  const pageRef = useRef(null)
  const askedRef = useRef(false)
  const rowRefs = useRef({})
  const stripRefs = useRef({})
  const tileRefs = useRef({})
  const setRowRef = useCallback((index, el) => { rowRefs.current[index] = el }, [])
  const setStripRef = useCallback((index, el) => { stripRefs.current[index] = el }, [])
  const setTileRef = useCallback((rowIndex, colIndex, el) => {
    tileRefs.current[`${rowIndex}:${colIndex}`] = el
  }, [])
  const [viewRows, setViewRows] = useState([1, 4])
  const focusSource = useRef('dpad')
  const shifts = useRef({})
  // Last column per row: rows are not a grid, so Down returns to where that row was left.
  const cols = useRef(restored.current ? { [restored.current.row]: restored.current.col } : {})
  const everLive = useRef(new Set())

  const baseRows = useMemo(() => {
    if (!data) return []
    const list = data.rows || []
    if (isMine || category || !genres.length) return list
    const at = list.findIndex((r) => r.id === 'continue') + 1
    return [...list.slice(0, at), { id: 'genres', kind: 'chips', items: genres }, ...list.slice(at)]
  }, [data, genres, isMine, category])

  // Endless: rounds of rows are appended near the end. The genre strip is not repeated, and My Library ends.
  const repeating = useMemo(() => baseRows.filter((r) => r.kind !== 'chips'), [baseRows])
  const endless = !isMine && repeating.length >= 3
  const [rounds, setRounds] = useState(0)
  useEffect(() => {
    const short = (restored.current?.row || 0) - baseRows.length
    if (endless && short > 0) setRounds((n) => Math.max(n, Math.ceil(short / repeating.length)))
  }, [endless, baseRows.length, repeating.length])
  const rows = useMemo(() => {
    if (!endless || !rounds) return baseRows
    const more = []
    for (let round = 1; round <= rounds; round += 1) {
      repeating.forEach((r) => more.push({ ...r, key: `${r.id}~${round}` }))
    }
    return [...baseRows, ...more]
  }, [baseRows, repeating, endless, rounds])

  const hero = isMine ? null : data?.hero
  const hasTop = Boolean(hero || isMine)

  // Compared with the last section seen rather than skipping the first run, which StrictMode runs twice.
  const shownFor = useRef(`${section}:${category}`)
  useEffect(() => {
    const now = `${section}:${category}`
    if (shownFor.current === now) return
    shownFor.current = now
    setRow(hasTop ? 0 : 1)
    setCol(0)
    setHeroCol(0)
    focusSource.current = 'dpad'
    shifts.current = {}
    cols.current = {}
    everLive.current = new Set()
    setRounds(0)
    if (pageRef.current) pageRef.current.scrollTop = 0
     
  }, [section, category])

  useEffect(() => {
    if (row === 0 && !hasTop && data && rows.length) setRow(1)
  }, [row, hasTop, data, rows.length])

  useEffect(() => {
    lastPosition.set(key, { row, col })
    if (row >= 1) cols.current[row] = col
  }, [key, row, col])

  const colIn = (index) => {
    const target = rows[index - 1]
    return target ? clamp(cols.current[index] ?? 0, target.items.length) ?? 0 : 0
  }

  const currentRow = row >= 1 ? rows[row - 1] : null

  useEffect(() => {
    if (!data) return
    if (row > rows.length) {
      if (endless) {
        setRounds((n) => Math.max(n, Math.ceil((row - baseRows.length) / repeating.length)))
        return
      }
      setRow(rows.length || (hasTop ? 0 : -1))
      return
    }
    if (currentRow && col >= currentRow.items.length) setCol(clamp(col, currentRow.items.length) ?? 0)
  }, [data, row, col, rows.length, currentRow, endless, baseRows.length, repeating.length, hasTop])

  const heroButtons = hero ? ['play', 'info'] : []

  const move = useCallback(
    (direction) => {
      focusSource.current = 'dpad'
      if (direction === 'up') {
        if (row === -1) return
        if (row === 0 || (row === 1 && !hasTop)) {
          if (!category) setRow(-1)
          return
        }
        const next = row - 1
        setRow(next)
        if (next >= 1) setCol(colIn(next))
        return
      }
      if (direction === 'down') {
        if (row === -1) {
          setRow(hasTop ? 0 : 1)
          return
        }
        const next = Math.min(row + 1, rows.length)
        if (endless && next >= rows.length - 2) setRounds((n) => n + 1)
        if (next === row) return
        setRow(next)
        setCol(colIn(next))
        return
      }
      if (row === -1) {
        if (direction === 'left') setNavCol((c) => Math.max(0, c - 1))
        if (direction === 'right') setNavCol((c) => Math.min(NAV_ITEMS.length - 1, c + 1))
        return
      }
      if (row === 0) {
        if (direction === 'left') setHeroCol((c) => Math.max(0, c - 1))
        if (direction === 'right') setHeroCol((c) => Math.min(heroButtons.length - 1, c + 1))
        return
      }
      const length = rows[row - 1]?.items.length || 0
      if (direction === 'left') setCol((c) => Math.max(0, c - 1))
      if (direction === 'right') setCol((c) => Math.min(length - 1, c + 1))
    },
    [row, rows, hasTop, category, heroButtons.length, endless],
  )

  const activate = useCallback(() => {
    if (row === -1) {
      onNav(NAV_ITEMS[navCol].id)
      return
    }
    if (row === 0) {
      if (isMine) onDownloads()
      else if (hero) {
        if (heroButtons[heroCol] === 'info') onMoreInfo(hero)
        else onPlay(hero)
      }
      return
    }
    if (!currentRow) return
    const item = currentRow.items[col]
    if (!item) return
    if (currentRow.kind === 'chips') onGenre(item.name)
    else onOpen(item)
  }, [row, navCol, isMine, hero, heroCol, heroButtons, currentRow, col, onNav, onDownloads,
    onMoreInfo, onPlay, onGenre, onOpen])

  useEffect(() => {
    registerHandler({
      onDirection: move,
      onEnter: activate,
      onBack: () => {
        if (category) {
          onClose()
          return true
        }
        if (row !== -1) {
          setRow(-1)
          setNavCol(navIndexOf(section))
          if (pageRef.current) pageRef.current.scrollTop = 0
          return true
        }
        return false
      },
    })
  }, [registerHandler, move, activate, row, category, section, onClose])

  // At most once a frame: it reads every row's position.
  const scrollQueued = useRef(false)
  const onPageScroll = useCallback(() => {
    if (scrollQueued.current) return
    scrollQueued.current = true
    requestAnimationFrame(() => {
      scrollQueued.current = false
      measureView()
    })
  }, [])
  const measureView = () => {
    const page = pageRef.current
    if (!page) return
    const top = page.scrollTop - 400
    const bottom = page.scrollTop + page.clientHeight + 400
    let first = Infinity
    let last = 0
    Object.keys(rowRefs.current).forEach((index) => {
      const el = rowRefs.current[index]
      if (!el) return
      const at = el.offsetTop
      if (at + el.offsetHeight >= top && at <= bottom) {
        first = Math.min(first, Number(index))
        last = Math.max(last, Number(index))
      }
    })
    if (last) setViewRows((v) => (v[0] === first && v[1] === last ? v : [first, last]))
  }

  const focusRow = row >= 1 ? row : 1
  const isLive = (index) => {
    const near = (index >= focusRow - 2 && index <= focusRow + 3) ||
      (index >= viewRows[0] && index <= viewRows[1])
    if (near) everLive.current.add(index)
    return near || (index >= focusRow - 5 && everLive.current.has(index))
  }

  // A pointer resting on a tile leaves the row where it is, or the tile would move out from under it.
  if (row >= 1 && currentRow && currentRow.kind !== 'chips' && focusSource.current === 'dpad') {
    shifts.current[row] = rowShift(currentRow.items, col, true)
  }
  const shiftFor = (index, r) =>
    index === row
      ? shifts.current[index] || 0
      : Math.min(shifts.current[index] || 0, rowShift(r.items, r.items.length, false))

  useEffect(() => {
    if (focusSource.current !== 'dpad') return
    const page = pageRef.current
    if (row >= 1) {
      if (rows[row - 1] && rows[row - 1].kind === 'chips') {
        scrollRowTo(stripRefs.current[row], tileRefs.current[`${row}:${col}`], { offset: 72 })
      }
      scrollPageTo(page, rowRefs.current[row], { offset: category ? 120 : 132, animate: true })
    } else if (page) {
      setPageScroll(page, 0, { animate: true })
    }
  }, [row, col, category, rows])

  // Stills either side of the focus are prefetched so the fetch and decode do not land in the slide's frames.
  useEffect(() => {
    if (row < 1 || !currentRow || currentRow.kind === 'chips') return
    ;[col - 1, col + 1, col + 2].forEach((index) => {
      const card = currentRow.items[index]
      const src = card && (card.backdrop_small || card.backdrop)
      if (src && !prefetched.has(src)) {
        prefetched.add(src)
        const image = new Image()
        image.src = src
      }
    })
  }, [row, col, currentRow])

  const heroState = useMemo(
    () => titleState(liveFor(hero, downloads), hero || {}),
    [hero, downloads],
  )

  const hoverTile = useCallback((rowIndex, colIndex) => {
    focusSource.current = 'pointer'
    setRow(rowIndex)
    setCol(colIndex)
  }, [])

  const lastWheel = useRef(0)
  const onWheel = useCallback((rowIndex, event) => {
    const delta = Math.abs(event.deltaX) > Math.abs(event.deltaY) ? event.deltaX : event.deltaY
    const now = Date.now()
    if (!delta || now - lastWheel.current < 150) return
    lastWheel.current = now
    const length = rows[rowIndex - 1]?.items.length || 0
    focusSource.current = 'dpad'
    const from = rowIndex === row ? col : cols.current[rowIndex] ?? 0
    setRow(rowIndex)
    setCol(clamp(from + (delta > 0 ? 1 : -1), length) ?? 0)
  }, [rows, row, col])

  const summary = useMemo(() => {
    const list = Object.values(downloads).filter((d) => d.state !== 'removed')
    const active = list.filter((d) => WORKING.includes(d.state))
    const percent = active.length
      ? active.reduce((sum, d) => sum + (d.percent || 0), 0) / active.length
      : 0
    return { titles: list.filter((d) => d.playable).length, active: active.length, percent }
  }, [downloads])

  const nav = !category && (
    <TopNav
      active={section}
      focused={row === -1 ? navCol : null}
      profile={profile}
      onHover={(i) => {
        focusSource.current = 'pointer'
        setRow(-1)
        setNavCol(i)
      }}
      onActivate={(i) => onNav(NAV_ITEMS[i].id)}
    />
  )

  if (loading) askedRef.current = true
  const waiting = !data && !(askedRef.current && !loading)

  return (
    <>
      {nav}
      {category && (
        <div className="category-head">
          <span className="category-bar" />
          {genreName(category)}
        </div>
      )}

      <div className={`tv-scroll home ${category ? 'in-category' : ''}`} ref={pageRef} onScroll={onPageScroll}>
        {isMine && (
          <div className="mine-head">
            <div
              className={`downloads-box ${row === 0 ? 'focused' : ''}`}
              onMouseEnter={() => {
                focusSource.current = 'pointer'
                setRow(0)
              }}
              onClick={onDownloads}
            >
              <span className="downloads-box-icon">
                {summary.active > 0 ? (
                  <ProgressRing percent={summary.percent} size={72} stroke={6}
                    label={`${Math.round(summary.percent)}%`} indeterminate={!summary.percent} />
                ) : (
                  <Icon name="download" size={46} />
                )}
              </span>
              <div className="downloads-box-body">
                <h2>{t('Downloads')}</h2>
                <div className="downloads-box-stats">
                  <span>{tp('{n} title', '{n} titles', summary.titles)}</span>
                  {summary.active > 0 && <span>{summary.active} {t('downloading')}</span>}
                  {totals && totals.size_bytes ? <span>{formatBytes(totals.size_bytes)} {t('on disk')}</span> : null}
                  {totals && totals.free_bytes ? <span>{formatBytes(totals.free_bytes)} {t('free')}</span> : null}
                </div>
              </div>
              <span className="downloads-box-go">{t('Manage Downloads')}</span>
            </div>
          </div>
        )}

        {waiting && !isMine && <HeroSkeleton />}

        {hero && (
          <div className="hero">
            <div
              className="hero-art"
              style={hero.backdrop ? { backgroundImage: `url(${hero.backdrop})` } : undefined}
            />
            <div className="hero-shade" />
            <div className="hero-body">
              {hero.logo ? (
                <img className="hero-logo" src={hero.logo} alt={hero.title} />
              ) : (
                <h1 className="hero-title">{hero.title}</h1>
              )}
              <div className="hero-meta">{metaBits(hero).join(' • ')}</div>
              {hero.overview && <p className="hero-overview">{hero.overview}</p>}
              <div className="hero-actions">
                <div
                  className={`pill-btn primary ${row === 0 && heroCol === 0 ? 'focused' : ''}`}
                  onMouseEnter={() => {
                    focusSource.current = 'pointer'
                    setRow(0)
                    setHeroCol(0)
                  }}
                  onClick={() => onPlay(hero)}
                >
                  {heroState.busy ? (
                    <ProgressRing percent={heroState.percent || 0} size={30} stroke={4}
                      indeterminate={heroState.spin} />
                  ) : (
                    <Icon name={heroState.icon} size={26} />
                  )}
                  <span>{t(stateLabel(heroState), stateVars(heroState))}</span>
                  {heroState.id === 'failed' && <span className="fail-badge corner">!</span>}
                </div>
                <div
                  className={`pill-btn quiet ${row === 0 && heroCol === 1 ? 'focused' : ''}`}
                  onMouseEnter={() => {
                    focusSource.current = 'pointer'
                    setRow(0)
                    setHeroCol(1)
                  }}
                  onClick={() => onMoreInfo(hero)}
                >
                  <span>{t('Details')}</span>
                  <Icon name="chevron-down" size={22} className="pill-arrow" />
                </div>
              </div>
            </div>
            {hero.vote_average ? (
              <div className="hero-aside">
                <Icon name="like" size={22} />
                <span>{hero.vote_average.toFixed(1)} TMDB</span>
              </div>
            ) : null}
          </div>
        )}

        <div className="rows">
          {waiting && <RowsSkeleton chips={!isMine && !category} />}
          {rows.map((r, ri) =>
            r.kind === 'chips' ? (
              <Chips
                key={r.id}
                row={r}
                rowIndex={ri + 1}
                focusedCol={row === ri + 1 ? col : -1}
                onHover={hoverTile}
                onOpen={(genre) => onGenre(genre.name)}
                setTileRef={setTileRef}
                setStripRef={setStripRef}
                setRowRef={setRowRef}
              />
            ) : (
              <Row
                key={r.key || r.id}
                r={r}
                rowIndex={ri + 1}
                focusedCol={row === ri + 1 ? col : -1}
                shift={shiftFor(ri + 1, r)}
                downloads={downloads}
                live={isLive(ri + 1)}
                onHoverTile={hoverTile}
                onOpen={onOpen}
                setTileRef={setTileRef}
                setStripRef={setStripRef}
                setRowRef={setRowRef}
                onWheel={onWheel}
                showTitle
              />
            ),
          )}
          {!waiting && !loading && rows.length === 0 && (
            <div className="empty-note">{t('Nothing to show yet.')}</div>
          )}
          <div className="rows-spacer" />
        </div>
      </div>
    </>
  )
}

const SKELETON_TILES = 7

function Bone({ className = '', delay = 0 }) {
  return (
    <div
      className={`bone ${className}`}
      style={delay ? { animationDelay: `${delay}ms` } : undefined}
    />
  )
}

function HeroSkeleton() {
  return (
    <div className="hero hero-skeleton">
      <div className="hero-body">
        <Bone className="bone-title" />
        <Bone className="bone-line short" />
        <Bone className="bone-line" />
        <Bone className="bone-line" />
        <Bone className="bone-line half" />
        <div className="hero-actions">
          <Bone className="bone-pill" />
          <Bone className="bone-pill" />
        </div>
      </div>
    </div>
  )
}

function RowsSkeleton({ chips }) {
  const tiles = Array.from({ length: SKELETON_TILES }, (_, i) => i)
  const row = (r) => (
    <div className="row" key={r}>
      <div className="row-title"><Bone className="bone-heading" delay={r * 120} /></div>
      <div className="row-strip">
        <div className="row-track">
          {tiles.map((i) => <Bone key={i} className="tile" delay={r * 120 + i * 90} />)}
        </div>
      </div>
    </div>
  )
  return (
    <>
      {row(0)}
      {chips && (
        <div className="row chips">
          <div className="row-strip">
            <div className="row-track">
              {tiles.map((i) => <Bone key={i} className="chip" delay={i * 90} />)}
            </div>
          </div>
        </div>
      )}
      {row(1)}
    </>
  )
}

// The shared state machine's English labels have the number baked in; these take it out to translate.
export function stateLabel(state) {
  if (state.id === 'downloading' && state.percent >= 1) return 'Downloading {n}%'
  if (state.id === 'preparing' && state.percent) return 'Preparing {n}%'
  if (state.id === 'downloading') return 'Downloading'
  if (state.id === 'preparing') return 'Preparing'
  return state.label
}

export function stateVars(state) {
  return { n: Math.round(state.percent || 0) }
}
