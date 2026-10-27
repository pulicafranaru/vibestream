import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, episodeCost, formatBytes, formatRuntime } from '../api'
import ProgressRing from '../shared/ProgressRing'
import Player from '../shared/Player'
import { liveFor, titleState } from '../shared/titleState'
import { genreSlug } from './Collection'
import { DetailSkeleton, EpisodesSkeleton } from './Skeleton'
import { DislikeIcon, DownloadIcon, Icon, LikeIcon, MyListIcon, PlayIcon, SeasonDownloadIcon, TrashIcon } from '../shared/icons'
import { confirmDialog } from './Confirm'

/*
 * The dialog is drawn full size, then transformed onto the rect it opened from and released;
 * closing runs it backwards. With no origin it simply rises in.
 */
const GROW_MS = 320
const EASE = 'cubic-bezier(0.2, 0.8, 0.2, 1)'

/*
 * Whether the artwork's top left corner is light (Rec. 709 average, biased towards white).
 * Read from a separate CORS copy: the displayed picture was fetched without CORS, so a canvas cannot read it.
 */
function cornerIsLight(url) {
  return new Promise((resolve) => {
    const image = new Image()
    image.crossOrigin = 'anonymous'
    image.onload = () => {
      try {
        const canvas = document.createElement('canvas')
        canvas.width = 32
        canvas.height = 18
        const g = canvas.getContext('2d')
        g.drawImage(image, 0, 0, 32, 18)
        const { data } = g.getImageData(0, 0, 10, 5)
        let sum = 0
        for (let i = 0; i < data.length; i += 4) {
          sum += 0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]
        }
        resolve(sum / (data.length / 4) / 255 > 0.62)
      } catch {
        resolve(false)
      }
    }
    image.onerror = () => resolve(false)
    image.src = url.replace(/\/t\/p\/w\d+\//, '/t/p/w300/')
  })
}

function placeOver(sheet, from) {
  const to = sheet.getBoundingClientRect()
  const scale = from.width / to.width
  const dx = from.left - to.left
  const dy = from.top - to.top
  return `translate(${dx}px, ${dy}px) scale(${scale})`
}

export default function Detail({
  mediaId, shell, onClose, from = null, preview = null,
  playing = null, onStop = () => {},
}) {
  // The player has the whole window: Escape is its, not the dialog's.
  const [playerFull, setPlayerFull] = useState(false)
  const [card, setCard] = useState(null)
  const [season, setSeason] = useState(null)
  const [revision, setRevision] = useState(0)
  const [chosenSeason, setChosenSeason] = useState(null)
  const seasons = (card && card.seasons) || []
  const seasonNumber =
    chosenSeason ?? (seasons.find((s) => s.downloaded) || seasons[0] || {}).number ?? 1
  const sheetRef = useRef(null)
  const backdropRef = useRef(null)
  const closing = useRef(false)
  const [tab, setTab] = useState(null)
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const [similar, setSimilar] = useState(null)
  useEffect(() => {
    let alive = true
    api
      .similar(mediaId)
      .then((page) => alive && setSimilar(page.items || []))
      .catch(() => alive && setSimilar([]))
    return () => {
      alive = false
    }
  }, [mediaId])

  // The show's button changes as downloads land and episodes are watched, so reread after either.
  const [choosing, setChoosing] = useState(false)
  // Newest answer only, and the poll never stacks requests: an older plan landing last set the button back.
  const reloadSeq = useRef(0)
  const reloading = useRef(false)
  const reload = useCallback(() => {
    const seq = ++reloadSeq.current
    reloading.current = true
    api.media(mediaId)
      .then((data) => seq === reloadSeq.current && setCard(data))
      .catch(() => {})
      .finally(() => {
        if (seq === reloadSeq.current) reloading.current = false
      })
  }, [mediaId])
  const changed = useCallback(() => {
    reload()
    setRevision((r) => r + 1)
  }, [reload])
  const waitingOn = card?.plan?.primary?.action
  useEffect(() => {
    if (waitingOn !== 'downloading' && waitingOn !== 'preparing') return undefined
    const timer = setInterval(() => {
      if (!reloading.current) reload()
    }, 5000)
    return () => clearInterval(timer)
  }, [waitingOn, reload])

  useEffect(() => {
    let alive = true
    reloadSeq.current += 1
    reloading.current = false
    api
      .media(mediaId)
      .then((data) => {
        if (!alive) return
        setCard(data)
        setTab((data.seasons || []).length ? 'episodes' : 'more')
      })
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [mediaId])

  // Before the first paint, so the dialog is never seen in place.
  useLayoutEffect(() => {
    const sheet = sheetRef.current
    const backdrop = backdropRef.current
    if (!sheet || !backdrop) return
    sheet.style.transformOrigin = 'top left'
    if (from) {
      sheet.style.transform = placeOver(sheet, from)
      sheet.style.opacity = '0.6'
    } else {
      sheet.style.transform = 'translateY(24px) scale(0.97)'
      sheet.style.opacity = '0'
    }
    backdrop.style.backgroundColor = 'rgba(0, 0, 0, 0)'
    backdrop.style.backdropFilter = 'blur(0px)'
    backdrop.style.webkitBackdropFilter = 'blur(0px)'
    // Read back so the start is committed before the transition is set.
    sheet.getBoundingClientRect()
    sheet.style.transition = `transform ${GROW_MS}ms ${EASE}, opacity ${GROW_MS}ms ${EASE}`
    backdrop.style.transition = ['background-color', 'backdrop-filter', '-webkit-backdrop-filter']
      .map((p) => `${p} ${GROW_MS}ms ${EASE}`).join(', ')
    sheet.style.transform = ''
    sheet.style.opacity = ''
    backdrop.style.backgroundColor = ''
    backdrop.style.backdropFilter = ''
    backdrop.style.webkitBackdropFilter = ''
  }, [])

  // The page behind keeps its place but does not scroll under the dialog.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  const close = useCallback(() => {
    if (closing.current) return
    closing.current = true
    const sheet = sheetRef.current
    const backdrop = backdropRef.current
    if (!sheet || !backdrop) {
      onClose()
      return
    }
    const target = from
    const ms = Math.round(GROW_MS * 0.75)
    sheet.style.transition = `transform ${ms}ms ${EASE}, opacity ${ms}ms ${EASE}`
    backdrop.style.transition = ['background-color', 'backdrop-filter', '-webkit-backdrop-filter']
      .map((p) => `${p} ${ms}ms ${EASE}`).join(', ')
    sheet.style.transform = target ? placeOver(sheet, target) : 'translateY(24px) scale(0.97)'
    sheet.style.opacity = '0'
    backdrop.style.backgroundColor = 'rgba(0, 0, 0, 0)'
    backdrop.style.backdropFilter = 'blur(0px)'
    backdrop.style.webkitBackdropFilter = 'blur(0px)'
    setTimeout(onClose, ms)
  }, [from, onClose])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key !== 'Escape' || playerFull) return
      // The player claims Escape (Settings, speed tray) by preventing the default; read once every listener has run.
      setTimeout(() => {
        if (!event.defaultPrevented) close()
      }, 0)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [close, playerFull])

  const artwork = (card || preview || {}).backdrop || null
  const [closeOnLight, setCloseOnLight] = useState(false)
  useEffect(() => {
    let alive = true
    setCloseOnLight(false)
    if (artwork) cornerIsLight(artwork).then((light) => alive && setCloseOnLight(light))
    return () => {
      alive = false
    }
  }, [artwork])

  useEffect(() => {
    if (playing && backdropRef.current) backdropRef.current.scrollTo({ top: 0, behavior: 'smooth' })
  }, [playing])

  const facts = (card && card.facts) || {}
  const live = card && liveFor(card, shell.downloads)
  const state = card ? titleState(live, card) : null

  const download = async (torrentId) => {
    setBusy(true)
    try {
      await shell.startDownload(torrentId)
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  const fetchPrimary = async (offer) => {
    setBusy(true)
    try {
      await fetchOffer(shell, offer)
    } catch (e) {
      shell.showError(`Couldn't start the download: ${e.message}`)
    }
    setBusy(false)
    changed()
  }

  const hero = card ? heroFor(card, live, state, busy, shell, {
    play: (id) => shell.play(id),
    download: () => download(card.primary_release_id),
    fetch: fetchPrimary,
    choose: () => setChoosing(true),
  }) : null

  return (
    <div className="sheet-backdrop" ref={backdropRef} onClick={close}>
      <div className="sheet" ref={sheetRef} onClick={(e) => e.stopPropagation()}>
        <button className={`sheet-close start ${closeOnLight && !playing ? 'on-light' : ''}`} onClick={close} aria-label="Close">
          <Icon name="close" size={34} />
        </button>

        {playing && (
          <div className="sheet-art playing" data-player-frame>
            <Player
              key={playing}
              playId={playing}
              title={(card || preview || {}).title || ''}
              variant="browser"
              inline
              registerHandler={() => {}}
              onExit={onStop}
              onNext={(next) => shell.play(next.play_id)}
              onFull={setPlayerFull}
              startFull={playerFull}
            />
          </div>
        )}

        {!playing && (card || preview) && (
          <div className="sheet-art">
            {(card || preview).backdrop && <img src={(card || preview).backdrop} alt="" />}
            <div className="sheet-shade" />
            {(card || preview).logo ? (
              <img className="sheet-logo" src={(card || preview).logo} alt={(card || preview).title} />
            ) : (
              <h1>{(card || preview).title}</h1>
            )}
            {hero && <HeroButton {...hero} />}
          </div>
        )}

        {!card && !preview && !error && <div className="sheet-art bone" />}
        {!card && !error && <DetailSkeleton />}
        {error && <p className="note error">{error}</p>}

        {card && (
          <>

            <div className="sheet-body">
              <div className="sheet-top">
                <div className="sheet-meta">
                  {card.vote_average > 0 && (
                    <span className="score">{card.vote_average.toFixed(1)}</span>
                  )}
                  {card.year && <span>{card.year}</span>}
                  {seriesLine(card) && <span>{seriesLine(card)}</span>}
                  {card.complete && <span className="complete">Complete</span>}
                  {card.media_type !== 'tv' && card.runtime > 0 && (
                    <span>{formatRuntime(card.runtime)}</span>
                  )}
                  {facts.certification && <span className="cert">{facts.certification}</span>}
                  {(card.quality?.badges || []).map((b) => (
                    <span key={b} className="badge">{b}</span>
                  ))}
                </div>

                {choosing && (
                  <DownloadChooser
                    card={card}
                    shell={shell}
                    onClose={() => setChoosing(false)}
                    onChanged={changed}
                  />
                )}
                <div className="rate">
                  <button
                    className={shell.myList.has(card.media_id) ? 'on saved' : ''}
                    onClick={() => shell.toggleMyList(card.media_id)}
                    title={shell.myList.has(card.media_id) ? 'Remove from Watchlist' : 'Add to Watchlist'}
                  >
                    <MyListIcon size={20} saved={shell.myList.has(card.media_id)} />
                  </button>
                  <button
                    className={shell.ratings[card.media_id] === -1 ? 'on' : ''}
                    onClick={() => shell.rate(card.media_id, -1)}
                    title="Not for me"
                  >
                    <DislikeIcon size={20} />
                  </button>
                  <button
                    className={shell.ratings[card.media_id] === 1 ? 'on' : ''}
                    onClick={() => shell.rate(card.media_id, 1)}
                    title="Like it!"
                  >
                    <LikeIcon size={20} />
                  </button>
                  {season && (
                    <SeasonButton season={season} shell={shell} onChanged={changed} />
                  )}
                </div>
              </div>

              <div className="sheet-info">
                <div>
                  {card.tagline && <p className="sheet-tagline">{card.tagline}</p>}
                  {card.overview && <p className="sheet-overview">{card.overview}</p>}
                </div>
                <FactList card={card} facts={facts} shell={shell} />
              </div>

              <div className="tabs">
                {(card.seasons || []).length > 0 && (
                  <button
                    className={tab === 'episodes' ? 'on' : ''}
                    onClick={() => setTab('episodes')}
                  >
                    Episodes
                  </button>
                )}
                <button className={tab === 'more' ? 'on' : ''} onClick={() => setTab('more')}>
                  Similar
                </button>
                <button
                  className={tab === 'versions' ? 'on' : ''}
                  onClick={() => setTab('versions')}
                >
                  Versions ({(card.releases || []).length})
                </button>
                {tab === 'episodes' && seasons.length > 1 && (
                  <div className="tabs-aside">
                    <SeasonPicker
                      seasons={seasons}
                      number={seasonNumber}
                      onChange={setChosenSeason}
                    />
                  </div>
                )}
              </div>

              {/* At least a screen tall, or switching to a short tab shrinks the dialog and the page jumps. */}
              <div className="tab-panel">
              {tab === 'episodes' && (
                <Episodes
                  card={card}
                  shell={shell}
                  playing={playing}
                  number={seasonNumber}
                  revision={revision}
                  onSeason={setSeason}
                />
              )}
              {tab === 'more' && <MoreLikeThis items={similar} shell={shell} />}
              {tab === 'versions' && (
                <Versions card={card} shell={shell} onDownload={download} />
              )}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

async function fetchOffer(shell, offer) {
  for (const part of offer.fetch) {
    const started = await shell.startDownload(
      part.release_id,
      part.episode_id ? { episode: part.episode_id } : part.all ? { scope: 'all' } : undefined,
    )
    // Called off at the low space prompt: the rest of the series too.
    if (started === null) return false
  }
  return true
}

const gigabytes = (offer) =>
  offer.size_gb ? `${offer.size_exact === false ? 'About ' : ''}${Number(offer.size_gb).toFixed(1)} GB` : null

/* The title's main button. A show's comes from the server's plan (services/plan.py), so every app agrees. */
function heroFor(card, live, state, busy, shell, act) {
  const primary = card.media_type === 'tv' && card.plan ? card.plan.primary : null
  if (primary) {
    const label = primary.label || null
    if (primary.action === 'play') return { kind: 'play', caption: label, onPress: () => act.play(primary.play_id) }
    if (primary.action === 'rewatch') return { kind: 'play', onPress: () => act.play(primary.play_id) }
    if (busy) return { kind: 'busy', spin: true, caption: label }
    if (primary.action === 'preparing') return { kind: 'busy', spin: true, caption: label, note: 'Preparing' }
    if (primary.action === 'downloading') {
      const arriving = primary.torrent_id ? shell.downloads[primary.torrent_id] : null
      const percent = (arriving && arriving.percent) || 0
      return { kind: 'busy', percent, spin: percent < 1, caption: label }
    }
    if (primary.action === 'download') {
      return { kind: 'download', caption: label, title: `Download ${label}`, onPress: () => act.fetch(primary.offer) }
    }
    if (!card.plan.offers.length) return null
    return { kind: 'download', title: 'Download', onPress: act.choose }
  }

  if (state && state.id === 'play') return { kind: 'play', onPress: () => act.play(state.playId) }
  if (!card.primary_release_id) return null
  if (busy) return { kind: 'busy', spin: true }
  const working = live && (['downloading', 'adding', 'requested'].includes(live.state) || live.preparing)
  if (working) {
    const percent = live.preparing ? live.prepare_percent || 0 : live.percent || 0
    return {
      kind: 'busy',
      percent,
      spin: live.preparing ? !live.prepare_percent : live.percent < 1,
      note: live.preparing ? 'Preparing' : null,
      title: 'Cancel download',
      onPress: async () => {
        if (await confirmDialog({
          title: 'Cancel Download?',
          message: 'Anything already downloaded is deleted.',
          action: 'Cancel Download',
          cancel: 'Keep Downloading',
        })) {
          shell.cancelDownload(live)
        }
      },
    }
  }
  if (live && (live.state === 'error' || live.prepare_error)) {
    return { kind: 'retry', title: 'Try again', onPress: act.download }
  }
  return { kind: 'download', title: 'Download', onPress: act.download }
}

function HeroButton({ kind, caption = null, note = null, percent = 0, spin = false, title, onPress }) {
  const words = [note, caption].filter(Boolean).join(' ')
  return (
    <button
      className={`sheet-play ${kind}`}
      onClick={onPress}
      disabled={!onPress}
      aria-label={title || (kind === 'play' ? 'Play' : words || 'Downloading')}
      title={title}
    >
      <span className="sheet-play-disc" data-tip-anchor>
        {kind === 'play' && <PlayIcon size={38} />}
        {kind === 'download' && <DownloadIcon size={34} />}
        {kind === 'retry' && <Icon name="replay" size={34} />}
        {kind === 'retry' && <span className="fail-badge corner" aria-label="Failed">!</span>}
        {kind === 'busy' && (
          <>
            <ProgressRing size={84} stroke={4} percent={percent} indeterminate={spin} />
            {!spin && <span className="sheet-play-percent">{Math.round(percent)}%</span>}
          </>
        )}
      </span>
      {words && <span className="sheet-play-label">{words}</span>}
    </button>
  )
}

const OFFER_ICONS = { episode: 'download', season: 'download-season', series: 'download-season' }

function DownloadChooser({ card, shell, onClose, onChanged }) {
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)
  const offers = card.plan?.offers || []

  useEffect(() => {
    const escape = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', escape, true)
    return () => window.removeEventListener('keydown', escape, true)
  }, [onClose])

  const choose = async (offer) => {
    setBusy(offer.kind)
    setError(null)
    try {
      await fetchOffer(shell, offer)
      onChanged()
      onClose()
    } catch (e) {
      setError(`Couldn't start the download: ${e.message}`)
      setBusy(null)
    }
  }

  return createPortal(
    <div className="chooser-backdrop" onClick={(e) => { e.stopPropagation(); onClose() }}>
      <div className="chooser" role="dialog" aria-label="Download" onClick={(e) => e.stopPropagation()}>
        <button className="chooser-close" onClick={onClose} aria-label="Close">
          <Icon name="close" size={18} />
        </button>
        <h2>Download {card.title}</h2>
        {offers.map((offer, index) => (
          <button
            key={offer.kind}
            className="chooser-option"
            disabled={busy !== null}
            onClick={() => choose(offer)}
          >
            <span className="chooser-icon">
              {busy === offer.kind
                ? <ProgressRing size={22} stroke={3} indeterminate />
                : <Icon name={OFFER_ICONS[offer.kind]} size={24} />}
            </span>
            <span className="chooser-text">
              <strong>
                {offer.title}
                {index === 0 && offer.kind === 'episode' && (
                  <em className="chooser-tag">Quickest to start</em>
                )}
              </strong>
              <span>{offer.detail}</span>
            </span>
            {gigabytes(offer) && <span className="chooser-size">{gigabytes(offer)}</span>}
          </button>
        ))}
        {error && <p className="note error">{error}</p>}
      </div>
    </div>,
    document.body,
  )
}

function SeasonButton({ season, shell, onChanged }) {
  const [busy, setBusy] = useState(false)
  const label = `Season ${season.number}`

  if (season.kind === 'downloaded') {
    const remove = async () => {
      const count = season.held.length
      if (!await confirmDialog({
        title: `Delete ${label}?`,
        message: `This removes all ${count} episode${count === 1 ? '' : 's'} from the server and from your library.`,
        action: 'Delete',
      })) return
      setBusy(true)
      try {
        // One episode at a time: a pack can hold more than this season.
        for (const item of season.held) {
          await api.removeEpisode(item.download, item.episode)
        }
      } catch {
        shell.showError("Couldn't delete the whole season. Try again.")
      }
      await shell.refreshDownloads()
      setBusy(false)
      onChanged()
    }
    return (
      <button
        className="season-held-button"
        onClick={remove}
        disabled={busy}
        title={busy ? `Deleting ${label}` : `${label} downloaded. Click to delete it.`}
        aria-label={`${label} downloaded`}
      >
        {busy ? (
          <ProgressRing size={20} stroke={3} indeterminate />
        ) : (
          <span className="season-held-icon">
            <SeasonDownloadIcon size={22} />
            <Icon name="check" size={10} className="season-held-badge" />
          </span>
        )}
      </button>
    )
  }

  const { pack } = season
  const live = shell.downloads[pack.id] || pack.download
  const arriving = pack.complete_request &&
    live && (['downloading', 'adding', 'requested'].includes(live.state) || live.preparing)
  const start = async () => {
    setBusy(true)
    try {
      await shell.startDownload(pack.id, pack.download ? { scope: 'all' } : undefined)
    } catch (e) {
      shell.showError(`Couldn't start the download: ${e.message}`)
    }
    setBusy(false)
    onChanged()
  }
  return (
    <button
      onClick={start}
      disabled={busy || arriving}
      title={arriving ? `Downloading ${label}` : `Download ${label}`}
      aria-label={`Download ${label}`}
    >
      {busy || arriving ? (
        <ProgressRing
          size={20}
          stroke={3}
          percent={live?.percent || 0}
          indeterminate={busy || !live || live.percent < 1}
        />
      ) : (
        <SeasonDownloadIcon size={22} />
      )}
    </button>
  )
}

/** Downloaded when every episode that has aired is here; otherwise the pack. */
function seasonStatus(number, episodes, pack) {
  if (!episodes.length) return null
  const aired = (e) => !(e.air_date && new Date(e.air_date) > new Date())
  const held = episodes
    .filter((e) => e.available && e.download_id)
    .map((e) => ({ episode: e.id, download: e.download_id }))
  const missing = episodes.some((e) => !e.available && aired(e))
  if (!missing && held.length) return { kind: 'downloaded', number, held }
  if (pack && episodes.some((e) => !e.available)) return { kind: 'offer', number, pack }
  return null
}

function SeasonPicker({ seasons, number, onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const current = seasons.find((s) => s.number === number) || seasons[0]

  useEffect(() => {
    if (!open) return undefined
    const away = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false)
    }
    const escape = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        setOpen(false)
      }
    }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', escape, true)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', escape, true)
    }
  }, [open])

  return (
    <div className={`season-picker ${open ? 'open' : ''}`} ref={ref}>
      <button className="season-picker-button" onClick={() => setOpen(!open)} aria-expanded={open}>
        {current?.name || `Season ${number}`}
        <span className="season-caret" aria-hidden="true" />
      </button>
      {open && (
        <div className="season-menu" role="listbox">
          {seasons.map((s) => (
            <button
              key={s.number}
              role="option"
              aria-selected={s.number === number}
              className={s.number === number ? 'on' : ''}
              onClick={() => {
                onChange(s.number)
                setOpen(false)
              }}
            >
              <strong>{s.name}</strong>
              {s.episode_count > 0 && (
                <span>({s.episode_count} Episode{s.episode_count === 1 ? '' : 's'})</span>
              )}
              {s.downloaded && <Icon name="check" size={14} className="season-held" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function Episodes({ card, shell, playing = null, number, revision = 0, onSeason = () => {} }) {
  const seasons = card.seasons || []
  const [episodes, setEpisodes] = useState([])
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(null)
  const [note, setNote] = useState(null)
  const [confirming, setConfirming] = useState(null)
  const [menu, setMenu] = useState(null)
  const episodesRef = useRef([])

  useEffect(() => {
    if (menu === null) return undefined
    const close = () => setMenu(null)
    window.addEventListener('click', close)
    return () => window.removeEventListener('click', close)
  }, [menu])
  episodesRef.current = episodes

  // Only the newest answer lands, or a slow one for the previous season fills this one.
  const loadSeq = useRef(0)
  const loadsOut = useRef(0)
  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    loadsOut.current += 1
    const data = await api.season(card.media_id, number).catch(() => null)
    loadsOut.current -= 1
    if (data && seq === loadSeq.current) {
      setEpisodes(data.episodes || [])
      onSeason(seasonStatus(number, data.episodes || [], data.season_pack || null))
    }
    // revision: a season downloaded or deleted from the button above.
  }, [card.media_id, number, revision])

  // Another season's state must not sit under this season's number.
  useEffect(() => {
    onSeason(null)
  }, [number])

  const removeEpisode = async (episode) => {
    setConfirming(null)
    setBusy(episode.id)
    setNote(null)
    try {
      await api.removeEpisode(episode.download_id, episode.id)
      await shell.refreshDownloads()
      await load()
    } catch {
      shell.showError("Couldn't delete the episode. Try again.")
    } finally {
      setBusy(null)
    }
  }

  useEffect(() => {
    let alive = true
    setLoading(true)
    setEpisodes([])
    load().finally(() => alive && setLoading(false))
    // Poll while anything is in flight: preparation finishes after the download with nothing to announce it.
    // Read through a ref, as the captured list is the empty one from before the first load.
    const timer = setInterval(() => {
      if (loadsOut.current) return
      if (episodesRef.current.some((e) => e.preparing || (e.download && !e.available))) load()
    }, 5000)
    return () => {
      alive = false
      clearInterval(timer)
    }
  }, [load])

  /* An episode out of a season pack is requested as that episode: only its file downloads. */
  const fetchEpisodes = async (releaseId, options, key, label) => {
    setBusy(key)
    setNote(null)
    try {
      const started = await shell.startDownload(releaseId, options)
      if (started) setNote(`${label} queued. It will be playable here once it has arrived.`)
      await load()
    } catch (e) {
      setNote(`Could not start ${label}: ${e.message}`)
    } finally {
      setBusy(null)
    }
  }

  return (
    <div className="episodes">
      {seasons.length === 1 && <div className="season-only">{seasons[0].name}</div>}
      {note && <p className="note">{note}</p>}

      {loading && !episodes.length && <EpisodesSkeleton />}

      {episodes.map((episode) => {
        const release = (episode.releases || [])[0]
        const now = Boolean(playing) && episode.play_id === playing
        const fetchable = !episode.available && !episode.download && release
        const fetch = () => fetchEpisodes(
          release.id,
          release.season_pack ? { episode: episode.id } : undefined,
          episode.id,
          `S${episode.season}:E${episode.episode}`,
        )
        const press = now ? null
          : episode.playable ? () => shell.play(episode.play_id)
            : fetchable && busy === null ? fetch : null
        return (
          <div
            className={['episode', episode.available || now ? '' : 'dim', press ? 'pressable' : '', now ? 'now' : ''].join(' ')}
            key={episode.id}
            onClick={press || undefined}
            role={press ? 'button' : undefined}
            tabIndex={press ? 0 : undefined}
            onKeyDown={press ? (e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                press()
              }
            } : undefined}
            aria-label={press
              ? `${episode.playable ? 'Play' : 'Download'} episode ${episode.episode}, ${episode.name}`
              : undefined}
            title={fetchable && episodeCost(release) ? `Download episode · ${episodeCost(release)}` : undefined}
          >
            <div className="episode-still">
              {episode.still && <img src={episode.still} alt="" loading="lazy" />}
              {episode.resume_percent > 1 && !episode.watched && (
                <div className="episode-resume">
                  <span style={{ width: `${episode.resume_percent}%` }} />
                </div>
              )}
              {now ? (
                <span className="episode-now"><Icon name="now-playing" size={16} /></span>
              ) : busy === episode.id ? (
                <span className="episode-glyph"><ProgressRing size={22} stroke={3} indeterminate /></span>
              ) : episode.playable ? (
                <span className="episode-glyph"><PlayIcon size={20} /></span>
              ) : fetchable ? (
                <span className="episode-glyph"><DownloadIcon size={19} /></span>
              ) : null}
            </div>
            <div className="episode-text">
              <div className="episode-title">
                {episode.episode}. {episode.name}
              </div>
              <div className="episode-note">
                {episode.runtime ? `${episode.runtime}m  ·  ` : ''}
                {now ? 'Playing' : episodeState(episode)}
              </div>
              {episode.overview && <p>{episode.overview}</p>}
            </div>
            <div className="episode-action" onClick={(e) => e.stopPropagation()}>
              {episode.available && episode.download_id && (
                confirming === episode.id ? (
                  <span className="episode-confirm">
                    Delete S{episode.season}:E{episode.episode}?
                    <button className="btn small danger" onClick={() => removeEpisode(episode)}>
                      Delete
                    </button>
                    <button className="btn small" onClick={() => setConfirming(null)}>Keep</button>
                  </span>
                ) : (
                  <div className="episode-more">
                    <button
                      className="icon-action"
                      disabled={busy !== null}
                      onClick={() => setMenu(menu === episode.id ? null : episode.id)}
                      title="More"
                      aria-label={`More for episode ${episode.episode}`}
                      aria-expanded={menu === episode.id}
                    >
                      {busy === episode.id
                        ? <ProgressRing size={18} stroke={3} indeterminate />
                        : <Icon name="more" size={20} />}
                    </button>
                    {menu === episode.id && (
                      <div className="episode-menu" role="menu">
                        <button
                          role="menuitem"
                          className="danger"
                          onClick={() => {
                            setMenu(null)
                            setConfirming(episode.id)
                          }}
                        >
                          <TrashIcon size={17} /> Delete Episode
                        </button>
                      </div>
                    )}
                  </div>
                )
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function episodeState(episode) {
  if (episode.watched) return 'Watched'
  if (episode.playable) return 'Ready'
  if (episode.preparing) return 'Preparing'
  if (episode.prepare_error) return 'Arrived, but could not be made playable'
  // Every episode has an air date, so only a future one means "coming".
  if (episode.air_date && new Date(episode.air_date) > new Date()) {
    return `Coming ${episode.air_date}`
  }
  if (episode.download && !episode.available && episode.download.state === 'error') {
    return episode.download.error_message || 'The download could not start'
  }
  if (episode.download && !episode.available) {
    const percent = Math.round(episode.download.percent || 0)
    return percent >= 1 ? `Downloading ${percent}%` : 'Waiting to download'
  }
  if (!(episode.releases || []).length) return 'Not on the tracker'
  return 'Not downloaded'
}

function MoreLikeThis({ items, shell }) {
  if (!items) return <EpisodesSkeleton count={2} />
  if (!items.length) return <p className="note">Nothing like this in the catalog yet.</p>

  return (
    <div className="similar-grid">
      {items.map((other) => {
        const saved = shell.myList.has(other.media_id)
        const runtime = other.media_type === 'tv'
          ? other.season_count && `${other.season_count} Season${other.season_count === 1 ? '' : 's'}`
          : other.runtime > 0 && formatRuntime(other.runtime)
        return (
          <article
            key={other.media_id}
            className="similar-card"
            onClick={(e) => shell.openTitle(other, e.currentTarget.getBoundingClientRect())}
          >
            <div className="similar-art">
              {(other.backdrop_small || other.backdrop) && (
                <img src={other.backdrop_small || other.backdrop} alt="" loading="lazy" />
              )}
              {other.logo
                ? <img className="similar-logo" src={other.logo} alt={other.title} loading="lazy" />
                : <span className="similar-wordmark">{other.title}</span>}
              {runtime && <span className="similar-runtime">{runtime}</span>}
            </div>
            <div className="similar-body">
              <div className="similar-meta">
                {other.certification && <span className="cert">{other.certification}</span>}
                {other.year && <span>{other.year}</span>}
                {other.best_resolution === '2160p' && <span className="badge">4K</span>}
                <button
                  className={`similar-add ${saved ? 'on' : ''}`}
                  onClick={(e) => {
                    e.stopPropagation()
                    shell.toggleMyList(other.media_id)
                  }}
                  title={saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
                  aria-label={saved ? 'Remove from Watchlist' : 'Add to Watchlist'}
                >
                  <MyListIcon size={18} saved={saved} />
                </button>
              </div>
              {other.overview && <p>{other.overview}</p>}
            </div>
          </article>
        )
      })}
    </div>
  )
}

function Versions({ card, shell, onDownload }) {
  return (
    <div className="versions">
      {(card.releases || []).map((release) => {
        const live = shell.downloads[release.id] || release.download
        return (
          <div className="version" key={release.id}>
            <div className="version-name">{release.name}</div>
            <div className="version-tags">
              {release.id === card.primary_release_id && <span className="chip best">BEST</span>}
              {release.origin_label && <span className="chip origin">{release.origin_label}</span>}
              {release.debrid && <span className="chip origin">Debrid</span>}
              {[release.resolution, release.hdr, release.video_codec, release.audio_codec]
                .filter(Boolean)
                .map((tag) => (
                  <span className="chip" key={tag}>{tag}</span>
                ))}
              {release.size_bytes > 0 && (
                <span className="chip">{formatBytes(release.size_bytes)}</span>
              )}
              {release.seeders > 0 && <span className="chip">{release.seeders} seeders</span>}
            </div>
            <div className="version-action">
              {live && live.playable ? (
                <button className="btn small" onClick={() => shell.play(String(live.id))}>
                  <PlayIcon size={16} /> Play
                </button>
              ) : live && live.state !== 'removed' ? (
                <span className="muted">
                  {live.preparing ? 'Preparing' : `${Math.round(live.percent || 0)}%`}
                </span>
              ) : (
                <button className="btn small" onClick={() => onDownload(release.id)}>
                  <DownloadIcon size={15} /> Download
                </button>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function seriesLine(card) {
  const facts = card.facts || {}
  if (card.media_type !== 'tv') return null
  if (facts.limited) return 'Limited Series'
  if (facts.seasons) return facts.seasons === 1 ? '1 Season' : `${facts.seasons} Seasons`
  return null
}

const capitalise = (text) => text.charAt(0).toUpperCase() + text.slice(1)

function FactList({ card, facts, shell }) {
  const genres = card.genres || []
  const ids = facts.person_ids || {}
  /* Real links, so they open in a new tab; a plain click stays in the app. */
  const link = (label, state, path) => (
    <a
      key={label}
      href={path}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        shell.go(state)
      }}
    >
      {label}
    </a>
  )
  const people = (names) => names.map((name) => (
    ids[name] ? link(name, { screen: 'person', personId: ids[name] }, `/browse/person/${ids[name]}`) : name
  ))
  const list = (items) => items.flatMap((item, i) => (i ? [', ', item] : [item]))
  const rows = [
    ['Cast', list(people((facts.cast || []).slice(0, 4)))],
    [facts.crew_heading, list(people(facts.crew || []))],
    ['Genres', list(genres.map((g) => link(g, { screen: 'genre', slug: genreSlug(g) },
      `/browse/genre/${genreSlug(g)}`)))],
    [
      card.media_type === 'tv' ? 'This show is about' : 'This film is about',
      (facts.keywords || []).map(capitalise).join(', '),
    ],
    [card.media_type === 'tv' ? 'Network' : 'Studio',
      ((card.media_type === 'tv' ? facts.networks : facts.studios) || []).join(', ')],
  ].filter(([label, value]) => label && (Array.isArray(value) ? value.length : value))

  if (!rows.length) return null
  return (
    <dl className="sheet-facts">
      {rows.map(([label, value]) => (
        <div key={label}>
          <dt>{label}:</dt> <dd>{value}</dd>
        </div>
      ))}
    </dl>
  )
}
