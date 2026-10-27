import { forwardRef, useCallback, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'
import { api, errorText, formatEta, formatSpeed } from '../api'
import { Icon, PlayIcon } from './icons'
import ProgressRing from './ProgressRing'
import { t } from './i18n'

// The player's Episodes column: a cover flow of episodes. The middle one plays
// when downloaded, or is fetched when not.
const PlayerEpisodes = forwardRef(function PlayerEpisodes({
  browser, mediaId, episode, playId, onPlay, onClose, unit = 1,
}, ref) {
  const px = (n) => Math.round(n * Math.max(unit, 0.6))
  const [seasons, setSeasons] = useState([])
  const [season, setSeason] = useState(episode.season)
  const [episodes, setEpisodes] = useState(null)
  const [index, setIndex] = useState(0)
  // header: season pill (0) and close (1); list: the cover flow; seasons: season picker.
  const [zone, setZone] = useState('list')
  const [headerAt, setHeaderAt] = useState(0)
  const [seasonAt, setSeasonAt] = useState(0)
  const [fetching, setFetching] = useState({})
  const [failed, setFailed] = useState({})
  const trackRef = useRef(null)
  const listRef = useRef(null)
  const rowRefs = useRef({})
  const seasonsRef = useRef(null)
  const seasonRefs = useRef({})
  const [offset, setOffset] = useState(0)
  const placed = useRef(false)

  useEffect(() => {
    let alive = true
    api.media(mediaId).then((card) => alive && setSeasons(card.seasons || [])).catch(() => {})
    return () => { alive = false }
  }, [mediaId])

  const load = useCallback(() => (
    api.season(mediaId, season)
      .then((data) => setEpisodes(data.episodes || []))
      .catch(() => setEpisodes((list) => list || []))
  ), [mediaId, season])

  useEffect(() => {
    setEpisodes(null)
    placed.current = false
    load()
  }, [load])

  useEffect(() => {
    if (!episodes || placed.current) return
    placed.current = true
    const at = episodes.findIndex((e) => isCurrent(e, playId))
    setIndex(at >= 0 ? at : 0)
  }, [episodes, playId])

  // Keep polling while a requested episode arrives, so its row turns playable in place.
  const busy = Boolean(episodes && episodes.some((e) => isBusy(e)))
  useEffect(() => {
    if (!busy) return undefined
    const timer = setInterval(load, 4000)
    return () => clearInterval(timer)
  }, [busy, load])

  useLayoutEffect(() => {
    const list = listRef.current
    const row = rowRefs.current[index]
    if (!list || !row) return
    setOffset(list.clientHeight / 2 - (row.offsetTop + row.offsetHeight / 2))
  }, [index, episodes])

  const fetch = useCallback((item) => {
    const release = (item.releases || [])[0]
    if (!release) return
    setFetching((f) => ({ ...f, [item.id]: true }))
    setFailed((f) => ({ ...f, [item.id]: null }))
    api.startDownload(release.id, { episode: release.season_pack ? item.id : undefined })
      .catch((e) => setFailed((f) => ({ ...f, [item.id]: errorText(e) || t('The download could not start.') })))
      .then(load)
      .then(() => setFetching((f) => ({ ...f, [item.id]: false })))
  }, [load])

  const act = useCallback((at) => {
    const item = (episodes || [])[at]
    if (!item) return
    if (at !== index) {
      setIndex(at)
      return
    }
    if (isCurrent(item, playId)) return
    if (item.playable && item.play_id) onPlay(item.play_id)
    else if (statusOf(item, playId, fetching[item.id], failed[item.id]).mark === 'download') fetch(item)
  }, [episodes, index, playId, onPlay, fetch, fetching, failed])

  const chooseSeason = (number) => {
    setSeason(number)
    setZone('list')
  }

  useImperativeHandle(ref, () => ({
    onDirection(dir) {
      if (zone === 'seasons') {
        if (dir === 'up') setSeasonAt((i) => Math.max(0, i - 1))
        if (dir === 'down') setSeasonAt((i) => Math.min(seasons.length - 1, i + 1))
        return
      }
      if (zone === 'header') {
        if (dir === 'left') setHeaderAt(0)
        if (dir === 'right') setHeaderAt(1)
        if (dir === 'down') setZone('list')
        return
      }
      if (dir === 'up') {
        if (index === 0) setZone('header')
        else setIndex(index - 1)
      }
      if (dir === 'down') setIndex(Math.min((episodes || []).length - 1, index + 1))
    },
    onEnter() {
      if (zone === 'seasons') {
        const picked = seasons[seasonAt]
        if (picked) chooseSeason(picked.number)
        return
      }
      if (zone === 'header') {
        if (headerAt === 1) onClose()
        else if (seasons.length > 1) {
          setSeasonAt(Math.max(0, seasons.findIndex((s) => s.number === season)))
          setZone('seasons')
        }
        return
      }
      act(index)
    },
    onBack() {
      if (zone === 'seasons') {
        setZone('header')
        return true
      }
      return false
    },
  }))

  // One episode per wheel turn, not a scroll's worth of pixels.
  const lastWheel = useRef(0)
  const onWheel = (event) => {
    if (!browser || !episodes) return
    const now = Date.now()
    if (now - lastWheel.current < 160 || Math.abs(event.deltaY) < 4) return
    lastWheel.current = now
    setIndex((i) => Math.max(0, Math.min(episodes.length - 1, i + (event.deltaY > 0 ? 1 : -1))))
  }

  useEffect(() => {
    const list = seasonsRef.current
    const el = seasonRefs.current[seasonAt]
    if (zone !== 'seasons' || !list || !el || browser) return
    const top = el.offsetTop - list.offsetTop
    if (top < list.scrollTop + 20) list.scrollTop = Math.max(0, top - 20)
    else if (top + el.offsetHeight > list.scrollTop + list.clientHeight - 20) {
      list.scrollTop = top + el.offsetHeight - list.clientHeight + 20
    }
  }, [zone, seasonAt, browser])

  const seasonName = (seasons.find((s) => s.number === season) || {}).name || t('Season {n}', { n: season })

  if (zone === 'seasons') {
    return (
      <div className="pe">
        <div className="pe-header">
          <h2>{t('Seasons')}</h2>
        </div>
        <div className="pe-seasons" ref={seasonsRef}>
          {seasons.map((s, i) => (
            <button
              type="button"
              key={s.number}
              ref={(el) => { seasonRefs.current[i] = el }}
              className={['ps-pill', 'choice', s.number === season ? 'chosen' : '', !browser && i === seasonAt ? 'focused' : ''].join(' ')}
              onClick={() => chooseSeason(s.number)}
              onMouseEnter={browser ? undefined : () => setSeasonAt(i)}
            >
              <span className="ps-text"><span className="ps-label">{s.name}</span></span>
            </button>
          ))}
        </div>
      </div>
    )
  }

  return (
    <div className="pe">
      <div className="pe-header">
        <button
          type="button"
          className={`pe-season ${!browser && zone === 'header' && headerAt === 0 ? 'focused' : ''}`}
          disabled={seasons.length < 2}
          onClick={() => setZone('seasons')}
        >
          {seasonName}
          {seasons.length > 1 && <Icon name="chevron-down" size={px(26)} />}
        </button>
        <button
          type="button"
          className={`ps-bare close ${!browser && zone === 'header' && headerAt === 1 ? 'focused' : ''}`}
          onClick={onClose}
          aria-label={t('Close episodes')}
        >
          <Icon name="close" size={px(36)} />
        </button>
      </div>

      <div className="pe-list" ref={listRef} onWheel={onWheel}>
        {!episodes && <div className="pe-wait"><div className="spinner" /></div>}
        <div className="pe-track" ref={trackRef} style={{ transform: `translateY(${offset}px)` }}>
          {(episodes || []).map((item, i) => {
            const away = Math.min(1, Math.abs(i - index))
            const middle = i === index && zone === 'list'
            const status = statusOf(item, playId, fetching[item.id], failed[item.id])
            return (
              <div
                key={item.id}
                ref={(el) => { rowRefs.current[i] = el }}
                className={`pe-row ${i === index ? 'middle' : ''}`}
                style={{
                  transform: `scale(${1 - 0.16 * away})`,
                  opacity: i === index ? 1 : 1 - 0.62 * away,
                }}
                onClick={() => act(i)}
              >
                <div className={`pe-still ${middle || (browser && i === index) ? 'lifted' : ''}`}>
                  {item.still && <img src={item.still} alt="" />}
                  {status.mark === 'now' && <span className="pe-mark now"><Icon name="now-playing" size={px(40)} /></span>}
                  {status.mark === 'play' && i === index && <span className="pe-mark"><PlayIcon size={px(32)} /></span>}
                  {status.mark === 'download' && i === index && <span className="pe-mark"><Icon name="download" size={px(30)} /></span>}
                  {status.ring && (
                    <span className="pe-ring">
                      <ProgressRing percent={status.percent || 0} size={px(64)} stroke={Math.max(3, px(5))}
                        indeterminate={!status.percent} />
                    </span>
                  )}
                  {item.resume_percent > 1 && !item.watched && (
                    <span className="pe-resume"><i style={{ width: `${item.resume_percent}%` }} /></span>
                  )}
                </div>
                <div className="pe-text">
                  <div className="pe-name">{item.episode}. {item.name || t('Episode {n}', { n: item.episode })}</div>
                  {status.label && (
                    <div className={`pe-status ${status.failed ? 'failed' : ''}`}>
                      {status.failed && <span className="fail-badge small">!</span>}
                      {status.label}
                    </div>
                  )}
                  {item.overview && <p className="pe-overview">{item.overview}</p>}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
})

function isCurrent(item, playId) {
  return (item.play_id && item.play_id === playId) || `e${item.id}` === playId
}

function isBusy(item) {
  if (item.preparing) return true
  const dl = item.download
  return Boolean(dl && !item.available && ['requested', 'adding', 'downloading'].indexOf(dl.state) >= 0)
}

function statusOf(item, playId, fetching, failed) {
  if (isCurrent(item, playId)) return { label: t('Now playing'), mark: 'now' }
  if (failed) return { label: t(failed), failed: true, mark: 'download' }
  if (fetching) return { label: t('Waiting for download'), ring: true }
  const dl = item.download
  if (item.playable) {
    return { label: item.runtime ? t('{n}m', { n: item.runtime }) : null, mark: 'play' }
  }
  if (item.preparing) {
    const percent = (dl && dl.prepare_percent) || 0
    return {
      label: percent ? t('Preparing {n}%', { n: Math.round(percent) }) : t('Preparing'),
      ring: true, percent,
    }
  }
  if (item.prepare_error) return { label: t('Could not prepare'), failed: true }
  if (dl && !item.available) {
    if (dl.state === 'error') return { label: t(dl.error_message || 'Failed'), failed: true, mark: 'download' }
    if (dl.state === 'downloading' && dl.percent >= 1) {
      const bits = [t('Downloading {n}%', { n: Math.round(dl.percent) })]
      if (dl.dl_speed > 0) bits.push(formatSpeed(dl.dl_speed))
      if (dl.eta_seconds) bits.push(t('{time} left', { time: formatEta(dl.eta_seconds) }))
      return { label: bits.join(' · '), ring: true, percent: dl.percent }
    }
    return { label: dl.state === 'downloading' ? t('Downloading') : t('Queued'), ring: true }
  }
  if (item.air_date && new Date(item.air_date) > new Date()) {
    return { label: t('Coming {date}', { date: item.air_date }) }
  }
  if ((item.releases || []).length) return { label: t('Not downloaded'), mark: 'download' }
  return { label: t('Not on the tracker') }
}

export default PlayerEpisodes
