import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, episodeCost, errorText, formatBytes, formatEta, formatSpeed } from '../api'
import { titleState } from '../shared/titleState'
import { genreName, getLanguage, shortDate, t, tp } from '../shared/i18n'
import { loadTrackPrefs, languageCode, saveTrackPrefs, sameLanguage } from '../shared/trackPrefs'
import ProgressRing from './ProgressRing'
import { tilePoster } from './images'
import { metaBits, stateLabel, stateVars } from './Home'
import { BackIcon, Icon, PlayIcon, SeasonDownloadIcon } from './icons'
import { inputMode, setPageScroll } from './navigation'

function episodeWait(episode) {
  if (episode.air_date && new Date(episode.air_date) > new Date()) {
    return t('Coming {date}', { date: shortDate(episode.air_date) })
  }
  if (episode.releases && episode.releases.length) {
    const cost = episodeCost(episode.releases[0])
    return `${t('Not downloaded')}${cost ? ` · ${cost}` : ''}`
  }
  return t('Not on the tracker')
}

function episodeProgress(episode) {
  const dl = episode.download
  if (episode.preparing) {
    const percent = (dl && dl.prepare_percent) || 0
    return {
      label: percent ? t('Preparing {n}%', { n: Math.round(percent) }) : t('Preparing'),
      percent,
      spin: !percent,
    }
  }
  if (episode.available || !dl) return null
  if (dl.state === 'error') return { label: t(dl.error_message || 'Failed'), failed: true }
  if (dl.state === 'paused') return { label: t('Paused'), percent: dl.percent || 0, spin: false }
  if (dl.state !== 'downloading' || !dl.percent) {
    return { label: dl.state === 'downloading' ? t('Downloading') : t('Queued'), percent: 0, spin: true }
  }
  const bits = [t('Downloading {n}%', { n: Math.round(dl.percent) })]
  if (dl.dl_speed > 0) bits.push(formatSpeed(dl.dl_speed))
  if (dl.eta_seconds) bits.push(t('{time} left', { time: formatEta(dl.eta_seconds) }))
  return { label: bits.join(' · '), percent: dl.percent, spin: false }
}

function releaseState(dl) {
  if (dl.playable) return t('Downloaded')
  if (dl.preparing) return t('Preparing')
  if (dl.state === 'downloading') return t('Downloading {n}%', { n: Math.round(dl.percent || 0) })
  if (['adding', 'requested'].indexOf(dl.state) >= 0) return t('Queued')
  if (dl.state === 'error') return t('Failed')
  return dl.state
}

function keepInView(container, element, margin = 24) {
  if (!container || !element) return
  const box = container.getBoundingClientRect()
  const rect = element.getBoundingClientRect()
  const top = rect.top - box.top + container.scrollTop
  const bottom = top + element.offsetHeight
  if (top - margin < container.scrollTop) {
    container.scrollTop = Math.max(0, top - margin)
  } else if (bottom + margin > container.scrollTop + container.clientHeight) {
    container.scrollTop = bottom + margin - container.clientHeight
  }
}

// offsetTop, not a rect: neighbouring rows are drawn scaled down, and a rect would count the transform.
function centreInList(list, element, animate) {
  if (!list || !element) return
  const centred = element.offsetTop - (list.clientHeight - element.offsetHeight) / 2
  const target = Math.max(0, Math.min(centred, list.scrollHeight - list.clientHeight))
  setPageScroll(list, target, { animate })
}

function keepInRow(container, element, margin = 72) {
  if (!container || !element) return
  const box = container.getBoundingClientRect()
  const rect = element.getBoundingClientRect()
  const left = rect.left - box.left + container.scrollLeft
  container.scrollLeft = Math.max(0, left - margin)
}

function trackName(track) {
  const code = languageCode(track.language)
  if (code === 'en') return t('English')
  if (code === 'de') return t('German')
  if (code === 'ro') return t('Romanian')
  return track.label || track.language || '?'
}

export default function Detail({
  card,
  downloads = {},
  rating = 0,
  inMyList = false,
  inContinue = false,
  focus = null,
  onRate,
  onToggleMyList,
  onHideContinue,
  onPlay,
  onDownload,
  onError,
  onOpenTitle,
  onClose,
  registerHandler,
}) {
  const seasons = card.seasons || []
  const isSeries = card.media_type === 'tv' && seasons.length > 0
  const facts = card.facts || {}

  const pickSeason = () => {
    if (focus) {
      const at = seasons.findIndex((s) => s.number === focus.season)
      if (at >= 0) return at
    }
    if (card.next_up) {
      const at = seasons.findIndex((s) => s.number === card.next_up.season)
      if (at >= 0) return at
    }
    const held = seasons.findIndex((s) => s.downloaded)
    return held >= 0 ? held : 0
  }

  // main | episodes | audio | credits | releases
  const [view, setView] = useState(focus && isSeries ? 'episodes' : 'main')
  // Within main: rate | actions | similar
  const [zone, setZone] = useState('actions')
  const [rateIndex, setRateIndex] = useState(1)
  const [actionIndex, setActionIndex] = useState(0)
  const [similar, setSimilar] = useState([])
  const [similarIndex, setSimilarIndex] = useState(0)

  const [epColumn, setEpColumn] = useState('episodes')
  const [seasonIndex, setSeasonIndex] = useState(pickSeason)
  const [episodeIndex, setEpisodeIndex] = useState(0)
  const [episodes, setEpisodes] = useState([])
  const [episodesFor, setEpisodesFor] = useState(null)
  const [seasonPack, setSeasonPack] = useState(null)
  const [seasonRevision, setSeasonRevision] = useState(0)
  const [loadingEpisodes, setLoadingEpisodes] = useState(false)

  const [releaseIndex, setReleaseIndex] = useState(0)
  const [trackInfo, setTrackInfo] = useState(null)
  const [trackIndex, setTrackIndex] = useState(0)
  const [prefs, setPrefs] = useState(() => loadTrackPrefs(card.media_id))
  const [moreSubs, setMoreSubs] = useState(false)
  const [moreAudio, setMoreAudio] = useState(false)
  const [creditIndex, setCreditIndex] = useState(0)

  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)

  const pendingEpisode = useRef(focus ? focus.episode : card.next_up ? card.next_up.number : null)
  const episodesRef = useRef([])
  episodesRef.current = episodes
  const seasonChosen = useRef(false)

  const bodyRef = useRef(null)
  const actionRefs = useRef({})
  const rateRef = useRef(null)
  const similarRef = useRef(null)
  const similarRefs = useRef({})
  const episodeListRef = useRef(null)
  const episodeRefs = useRef({})
  const seasonListRef = useRef(null)
  const seasonRefs = useRef({})
  const releaseListRef = useRef(null)
  const releaseRefs = useRef({})
  const trackListRef = useRef(null)
  const trackRefs = useRef({})
  const creditsRef = useRef(null)
  const creditRefs = useRef({})

  const releases = card.releases || []
  const primary = releases.find((r) => r.id === card.primary_release_id) || releases[0]
  const download = (primary && downloads[primary.id]) || card.download || (primary && primary.download)
  const state = titleState(download, card)
  const nextUp = card.next_up || null
  const season = seasons[seasonIndex]

  const playTarget = isSeries ? (nextUp ? nextUp.play_id : null) : state.id === 'play' ? state.playId : null
  const resuming = isSeries
    ? Boolean(nextUp && nextUp.kind === 'resume')
    : state.id === 'play' && (card.resume_percent || 0) > 1 && (card.resume_percent || 0) < 95

  useEffect(() => {
    if (!card.media_id) return undefined
    let alive = true
    api.similar(card.media_id).then((data) => alive && setSimilar(data.items || [])).catch(() => {})
    return () => { alive = false }
  }, [card.media_id])

  useEffect(() => {
    if (!isSeries || !season) return undefined
    let alive = true
    setLoadingEpisodes(true)
    const load = () =>
      api
        .season(card.media_id, season.number)
        .then((data) => {
          if (!alive) return
          const list = data.episodes || []
          setEpisodes(list)
          setEpisodesFor(season.number)
          setSeasonPack(data.season_pack || null)
          setLoadingEpisodes(false)
          if (pendingEpisode.current !== null) {
            const at = list.findIndex((e) => e.episode === pendingEpisode.current)
            pendingEpisode.current = null
            setEpisodeIndex(at >= 0 ? at : 0)
          }
        })
        .catch(() => alive && setLoadingEpisodes(false))
    load()
    const timer = setInterval(() => {
      if (episodesRef.current.some((e) => e.preparing || (e.download && !e.available))) load()
    }, 5000)
    return () => {
      alive = false
      clearInterval(timer)
    }
     
  }, [card.media_id, isSeries, season && season.number, seasonRevision])

  useEffect(() => {
    if (seasonChosen.current || !seasons.length) return
    setSeasonIndex(pickSeason())
    if (pendingEpisode.current === null) {
      pendingEpisode.current = focus ? focus.episode : card.next_up ? card.next_up.number : null
    }
     
  }, [seasons.length, card.next_up && card.next_up.play_id])

  const shownEpisodes = season && episodesFor === season.number ? episodes : []

  const actions = []
  if (isSeries) {
    if (nextUp) {
      actions.push({
        id: 'next-up',
        icon: 'play',
        label: `${nextUp.kind === 'resume' ? t('Resume') : t('Play')} ${nextUp.label.replace(':E', ': Ep. ')}`,
        percent: nextUp.kind === 'resume' ? nextUp.resume_percent : 0,
      })
      if (resuming) actions.push({ id: 'restart', icon: 'replay', label: t('Start Over') })
    }
    actions.push({ id: 'episodes', icon: 'episodes', label: t('Episodes') })
  } else {
    if (state.id === 'play') {
      actions.push({
        id: 'play',
        icon: 'play',
        label: resuming ? t('Resume') : t('Play'),
        percent: resuming ? card.resume_percent : 0,
      })
      if (resuming) actions.push({ id: 'restart', icon: 'replay', label: t('Start Over') })
    }
    if (state.busy) {
      actions.push({ id: 'status', busy: true, percent: state.percent || 0, spin: Boolean(state.spin),
        label: t(stateLabel(state), stateVars(state)) })
    }
    if (state.id === 'download' || state.id === 'failed') {
      actions.push({ id: 'download', icon: state.icon, label: t(state.label), failed: state.id === 'failed' })
    }
  }
  if (playTarget) actions.push({ id: 'audio', icon: 'subtitles', label: t('Audio & Subtitles') })
  if (inContinue && card.media_id) {
    actions.push({ id: 'hide', icon: 'close', label: t('Hide from Resume Watching') })
  }
  if (card.media_id) {
    actions.push({
      id: 'mylist',
      icon: inMyList ? 'check' : 'plus',
      label: inMyList ? t('Remove from Watchlist') : t('Add to Watchlist'),
    })
  }
  if (similar.length) actions.push({ id: 'similar', icon: 'grid', label: t('Similar') })
  actions.push({ id: 'credits', icon: 'credits', label: t('Credits & Details') })
  if (releases.length > 1) {
    actions.push({ id: 'releases', icon: 'list', label: t('Versions ({n})', { n: releases.length }) })
  }

  const actionIds = actions.map((a) => a.id).join(',')
  useEffect(() => {
    setActionIndex((i) => Math.min(i, Math.max(0, actions.length - 1)))
     
  }, [actionIds])

  const playEpisode = useCallback(
    (episode, fromStart = false) => {
      onPlay(card, episode.play_id, { season: episode.season, episode: episode.episode }, { fromStart })
    },
    [card, onPlay],
  )

  const openEpisodes = useCallback(() => {
    if (nextUp && season && nextUp.season === season.number) {
      const at = shownEpisodes.findIndex((e) => e.episode === nextUp.number)
      if (at >= 0) setEpisodeIndex(at)
    }
    setEpColumn('episodes')
    setView('episodes')
  }, [nextUp, season, shownEpisodes])

  const openAudio = useCallback(() => {
    if (!playTarget) return
    setTrackInfo(null)
    setTrackIndex(0)
    setView('audio')
    api.playInfo(playTarget).then(setTrackInfo).catch(() => setTrackInfo({ audio: [], subtitles: [] }))
  }, [playTarget])

  const queueDownload = useCallback(
    async (releaseId, options, label) => {
      setBusy(true)
      setNote(null)
      try {
        await onDownload(releaseId, options)
        setNote(label
          ? t('{label} queued. It will play here once it has arrived.', { label })
          : t('Queued. It will play here once it has arrived.'))
        setSeasonRevision((n) => n + 1)
      } catch (e) {
        onError(errorText(e))
      } finally {
        setBusy(false)
      }
    },
    [onDownload, onError],
  )

  const run = useCallback(
    (id) => {
      if (id === 'status') return
      if (id === 'play') onPlay(card, state.playId || download)
      else if (id === 'restart') {
        if (isSeries && nextUp) {
          onPlay(card, nextUp.play_id, { season: nextUp.season, episode: nextUp.number }, { fromStart: true })
        } else onPlay(card, state.playId || download, null, { fromStart: true })
      } else if (id === 'next-up' && nextUp) {
        onPlay(card, nextUp.play_id, { season: nextUp.season, episode: nextUp.number })
      } else if (id === 'episodes') openEpisodes()
      else if (id === 'download') {
        if (!busy) queueDownload(card.primary_release_id)
      } else if (id === 'audio') openAudio()
      else if (id === 'hide') onHideContinue(card.media_id)
      else if (id === 'mylist') onToggleMyList(card.media_id)
      else if (id === 'similar') {
        setZone('similar')
        setSimilarIndex(0)
      } else if (id === 'credits') {
        setCreditIndex(0)
        setView('credits')
      } else if (id === 'releases') {
        setReleaseIndex(0)
        setView('releases')
      }
    },
    [card, state, download, isSeries, nextUp, busy, onPlay, openEpisodes, queueDownload, openAudio,
      onHideContinue, onToggleMyList],
  )

  const openRelease = useCallback(
    (release) => {
      const rdl = release.download
      if (rdl && rdl.playable) {
        onPlay(card, rdl)
        return
      }
      if (rdl && (['downloading', 'adding', 'requested'].indexOf(rdl.state) >= 0 || rdl.preparing)) return
      if (!busy) queueDownload(release.id)
    },
    [card, onPlay, busy, queueDownload],
  )

  const pressEpisode = useCallback(
    (episode) => {
      if (!episode) return
      if (episode.playable && episode.play_id) playEpisode(episode)
      else if (!episode.available && !episode.download && episode.releases && episode.releases.length && !busy) {
        const release = episode.releases[0]
        queueDownload(
          release.id,
          release.season_pack ? { episode: episode.id } : undefined,
          t('S{s}:E{e}', { s: episode.season, e: episode.episode }),
        )
      }
    },
    [playEpisode, queueDownload, busy],
  )

  const seasonButton = Boolean(
    seasonPack && !seasonPack.complete_request && shownEpisodes.some((e) => !e.available),
  )
  const seasonButtonLabel = seasonPack
    ? `${seasonPack.download ? t('Download Rest of Season') : t('Download Season')} · ${Number(seasonPack.size_gb).toFixed(1)} GB`
    : ''
  const pressSeason = useCallback(() => {
    if (!seasonPack || busy) return
    queueDownload(seasonPack.id, seasonPack.download ? { scope: 'all' } : undefined, season ? season.name : '')
  }, [seasonPack, busy, queueDownload, season])

  const trackItems = useMemo(() => {
    if (!trackInfo) return []
    const order = [getLanguage(), 'en', 'de', 'ro'].filter((c, i, all) => all.indexOf(c) === i)
    const rank = (code) => (order.indexOf(code) >= 0 ? order.indexOf(code) : 99)
    const items = [{ kind: 'head', label: t('Subtitles') }, { kind: 'subs', value: 'off', label: t('Off') }]
    const subs = []
    const seenSubs = new Set()
    ;(trackInfo.subtitles || []).forEach((s) => {
      const code = languageCode(s.language)
      if (!code || seenSubs.has(code) || s.forced) return
      seenSubs.add(code)
      subs.push({ kind: 'subs', value: code, label: trackName(s), rank: rank(code) })
    })
    const pickedSub = prefs && prefs.subs
    const mainSubs = subs.filter((x) => x.rank < 99 || x.value === pickedSub).sort((a, b) => a.rank - b.rank)
    const otherSubs = subs.filter((x) => mainSubs.indexOf(x) < 0)
    items.push(...mainSubs)
    if (otherSubs.length) {
      if (moreSubs) items.push(...otherSubs)
      else items.push({ kind: 'more-subs', label: t('Show More ({n})', { n: otherSubs.length }) })
    }
    items.push({ kind: 'head', label: t('Audio') })
    const audio = []
    const seenAudio = new Set()
    ;(trackInfo.audio || []).forEach((a) => {
      const code = languageCode(a.language) || `#${a.index}`
      if (seenAudio.has(code)) return
      seenAudio.add(code)
      audio.push({
        kind: 'audio', value: code, original: a.default, rank: a.default ? -1 : rank(code),
        label: a.default ? t('{lang} [Original]', { lang: trackName(a) }) : trackName(a),
      })
    })
    const pickedAudio = prefs && prefs.audio
    const mainAudio = audio.filter((x) => x.rank < 99 || x.value === pickedAudio).sort((a, b) => a.rank - b.rank)
    const otherAudio = audio.filter((x) => mainAudio.indexOf(x) < 0)
    items.push(...mainAudio)
    if (otherAudio.length) {
      if (moreAudio) items.push(...otherAudio)
      else items.push({ kind: 'more-audio', label: t('Show More ({n})', { n: otherAudio.length }) })
    }
    return items
  }, [trackInfo, prefs, moreSubs, moreAudio])

  const chosen = useCallback(
    (item) => {
      if (!trackInfo) return false
      if (item.kind === 'subs') {
        if (prefs && prefs.subs) return item.value === prefs.subs
        const def = (trackInfo.subtitles || []).find((s) => s.default)
        return def ? sameLanguage(def.language, item.value) : item.value === 'off'
      }
      if (item.kind === 'audio') {
        if (prefs && prefs.audio) return sameLanguage(prefs.audio, item.value)
        return Boolean(item.original)
      }
      return false
    },
    [prefs, trackInfo],
  )

  const chooseTrack = useCallback(
    (item) => {
      if (!item || item.kind === 'head') return
      if (item.kind === 'more-subs') {
        setMoreSubs(true)
        return
      }
      if (item.kind === 'more-audio') {
        setMoreAudio(true)
        return
      }
      const next = { ...(prefs || {}) }
      if (item.kind === 'subs') next.subs = item.value
      else next.audio = item.original ? null : item.value
      setPrefs(next)
      saveTrackPrefs(card.media_id, next)
    },
    [prefs, card.media_id],
  )

  useEffect(() => {
    if (view === 'audio' && trackItems.length && trackItems[trackIndex] && trackItems[trackIndex].kind === 'head') {
      setTrackIndex(trackIndex + 1)
    }
  }, [view, trackItems, trackIndex])

  const credits = useMemo(() => {
    const list = []
    const cast = facts.cast_all && facts.cast_all.length ? facts.cast_all : facts.cast
    if (cast && cast.length) list.push({ id: 'cast', label: t('Cast'), lines: cast })
    if (facts.crew && facts.crew.length) {
      const heading = facts.crew_heading === 'Creators'
        ? (facts.crew.length === 1 ? t('Creator') : t('Creators'))
        : (facts.crew.length === 1 ? t('Director') : t('Directors'))
      list.push({ id: 'crew', label: heading, lines: facts.crew })
    }
    if (card.genres && card.genres.length) {
      list.push({ id: 'genres', label: t('Genres'), lines: card.genres.map(genreName) })
    }
    const cert = facts.certification
    list.push({
      id: 'rating',
      label: t('Maturity Rating'),
      lines: cert
        ? [cert, /^\d+/.test(cert) ? t('Recommended for ages {n} and up', { n: parseInt(cert, 10) }) : null].filter(Boolean)
        : [t('Not rated')],
    })
    return list
  }, [facts, card.genres])

  // The whole left column scrolls, so no action is ever cut in half at the edge of a box.
  useEffect(() => {
    if (view !== 'main') return
    const body = bodyRef.current
    if (!body) return
    if (zone === 'similar') {
      body.scrollTop = 0
      return
    }
    if (zone === 'rate' || (zone === 'actions' && actionIndex === 0)) {
      if (zone === 'rate') body.scrollTop = 0
      else keepInView(body, actionRefs.current[0], 24)
    } else if (zone === 'actions') {
      keepInView(body, actionRefs.current[actionIndex], 24)
    }
  }, [view, zone, actionIndex])
  useEffect(() => {
    if (view === 'main' && zone === 'similar') keepInRow(similarRef.current, similarRefs.current[similarIndex])
  }, [view, zone, similarIndex])
  // With the pointer the episode list only keeps the focus in view; centring would move the list under the cursor.
  const episodesShown = useRef(false)
  useEffect(() => {
    if (view !== 'episodes') {
      episodesShown.current = false
      return
    }
    const list = episodeListRef.current
    const element = episodeRefs.current[episodeIndex]
    if (inputMode() === 'pointer') keepInView(list, element)
    else centreInList(list, element, episodesShown.current)
    episodesShown.current = true
  }, [view, episodeIndex, shownEpisodes.length])
  useEffect(() => {
    if (view === 'episodes') keepInView(seasonListRef.current, seasonRefs.current[seasonIndex])
  }, [view, seasonIndex])
  useEffect(() => {
    if (view === 'releases') keepInView(releaseListRef.current, releaseRefs.current[releaseIndex], 12)
  }, [view, releaseIndex])
  useEffect(() => {
    if (view === 'audio') keepInView(trackListRef.current, trackRefs.current[trackIndex], 60)
  }, [view, trackIndex])
  useEffect(() => {
    if (view === 'credits') keepInView(creditsRef.current, creditRefs.current[creditIndex], 0)
  }, [view, creditIndex])

  const changeSeason = useCallback((index) => {
    seasonChosen.current = true
    setSeasonIndex(index)
    if (pendingEpisode.current === null) setEpisodeIndex(0)
    if (episodeListRef.current) episodeListRef.current.scrollTop = 0
  }, [])

  const backToMain = useCallback((from) => {
    setView('main')
    setZone('actions')
    const at = actions.findIndex((a) => a.id === from)
    if (at >= 0) setActionIndex(at)
     
  }, [actionIds])

  useEffect(() => {
    registerHandler({
      onDirection: (dir) => {
        if (view === 'episodes') {
          if (epColumn === 'seasons') {
            if (dir === 'up' && seasonIndex > 0) changeSeason(seasonIndex - 1)
            if (dir === 'down' && seasonIndex < seasons.length - 1) changeSeason(seasonIndex + 1)
            if (dir === 'right' && (shownEpisodes.length || seasonButton)) setEpColumn('episodes')
            return
          }
          if (dir === 'down') setEpisodeIndex((i) => Math.min(shownEpisodes.length - 1, i + 1))
          if (dir === 'up') setEpisodeIndex((i) => Math.max(seasonButton ? -1 : 0, i - 1))
          if (dir === 'left') setEpColumn('seasons')
          return
        }
        if (view === 'releases') {
          if (dir === 'down') setReleaseIndex((i) => Math.min(releases.length - 1, i + 1))
          if (dir === 'up') setReleaseIndex((i) => Math.max(0, i - 1))
          return
        }
        if (view === 'audio') {
          const step = dir === 'down' ? 1 : dir === 'up' ? -1 : 0
          if (!step) return
          setTrackIndex((i) => {
            let next = i + step
            while (trackItems[next] && trackItems[next].kind === 'head') next += step
            return trackItems[next] ? next : i
          })
          return
        }
        if (view === 'credits') {
          if (dir === 'down') setCreditIndex((i) => Math.min(credits.length - 1, i + 1))
          if (dir === 'up') setCreditIndex((i) => Math.max(0, i - 1))
          return
        }
        if (zone === 'rate') {
          if (dir === 'left') setRateIndex((i) => Math.max(0, i - 1))
          if (dir === 'right') setRateIndex((i) => Math.min(1, i + 1))
          if (dir === 'down') setZone('actions')
          return
        }
        if (zone === 'similar') {
          if (dir === 'left') setSimilarIndex((i) => Math.max(0, i - 1))
          if (dir === 'right') setSimilarIndex((i) => Math.min(similar.length - 1, i + 1))
          if (dir === 'up') {
            setZone('actions')
            setActionIndex(actions.length - 1)
          }
          return
        }
        if (dir === 'up') {
          if (actionIndex > 0) setActionIndex((i) => i - 1)
          else if (card.media_id && onRate) setZone('rate')
          return
        }
        if (dir === 'down') {
          if (actionIndex < actions.length - 1) setActionIndex((i) => i + 1)
          else if (similar.length) {
            setZone('similar')
            setSimilarIndex(0)
          }
          return
        }
        if (dir === 'right' && isSeries) openEpisodes()
      },
      onEnter: () => {
        if (view === 'episodes') {
          if (epColumn === 'seasons') {
            if (shownEpisodes.length) setEpColumn('episodes')
            return
          }
          if (episodeIndex === -1) pressSeason()
          else pressEpisode(shownEpisodes[episodeIndex])
          return
        }
        if (view === 'releases') {
          const release = releases[releaseIndex]
          if (release) openRelease(release)
          return
        }
        if (view === 'audio') {
          chooseTrack(trackItems[trackIndex])
          return
        }
        if (view === 'credits') return
        if (zone === 'rate') {
          onRate(card.media_id, [-1, 1][rateIndex])
          return
        }
        if (zone === 'similar') {
          const other = similar[similarIndex]
          if (other) onOpenTitle(other)
          return
        }
        const action = actions[actionIndex]
        if (action) run(action.id)
      },
      onBack: () => {
        if (view === 'episodes') backToMain('episodes')
        else if (view === 'audio') backToMain('audio')
        else if (view === 'credits') backToMain('credits')
        else if (view === 'releases') backToMain('releases')
        else if (zone !== 'actions') {
          setZone('actions')
          if (zone === 'similar') setActionIndex(actions.length - 1)
        } else onClose()
        return true
      },
    })
  }, [
    registerHandler, view, zone, epColumn, rateIndex, actionIndex, releaseIndex, trackIndex,
    creditIndex, similarIndex, actions, releases, shownEpisodes, episodeIndex, seasons,
    seasonIndex, similar, trackItems, credits, isSeries, card, onRate, run, openRelease,
    onClose, onOpenTitle, pressEpisode, changeSeason, openEpisodes, seasonButton, pressSeason,
    chooseTrack, backToMain,
  ])

  useEffect(() => {
    if (episodeIndex === -1 && !seasonButton) setEpisodeIndex(0)
  }, [episodeIndex, seasonButton])

  const seasonCount = seasons.filter((s) => s.number > 0).length
  const bits = metaBits({ ...card, certification: facts.certification, limited: facts.limited },
    { seasons: facts.seasons || seasonCount })
  const badges = []
  if (card.quality && card.quality.resolution === '2160p') badges.push('4K')
  if (card.quality && card.quality.hdr) badges.push(card.quality.hdr)
  if (card.quality && card.quality.audio) badges.push(card.quality.audio)

  const heading = card.logo ? (
    <img className="detail-logo" src={card.logo} alt={card.title} />
  ) : (
    <h1 className="detail-title">{card.title}</h1>
  )
  const smallHeading = card.logo ? (
    <img className="detail-logo small" src={card.logo} alt={card.title} />
  ) : (
    <h1 className="detail-title small">{card.title}</h1>
  )
  const shortMeta = (
    <div className="detail-meta">
      {[card.year, isSeries && seasonCount ? tp('{n} Season', '{n} Seasons', seasonCount) : null]
        .filter(Boolean).join(' • ')}
      {facts.certification && <span className="badge cert">{facts.certification}</span>}
    </div>
  )

  return (
    <div className={`detail view-${view}`}>
      <button
        className="back-btn"
        onClick={view === 'main' ? onClose : () => backToMain(view)}
        title={t('Back')}
        aria-label={t('Back')}
      >
        <BackIcon size={26} />
      </button>
      <div
        className="detail-art"
        style={card.backdrop ? { backgroundImage: `url(${card.backdrop})` } : undefined}
      />
      <div className="detail-shade" />

      {view === 'main' && (
        <div className={`detail-body ${zone === 'similar' ? 'lowered' : ''}`} ref={bodyRef}>
          {heading}
          <div className="detail-meta">
            <span>{bits.filter((b) => b !== facts.certification).join(' • ')}</span>
            {badges.map((b) => <span key={b} className="badge">{b}</span>)}
          </div>
          {facts.certification && (
            <div className="detail-cert">
              <span className="badge cert">{facts.certification}</span>
              {facts.keywords && facts.keywords.length > 0 && (
                <span className="detail-keywords">{facts.keywords.slice(0, 4).join(', ')}</span>
              )}
            </div>
          )}

          {isSeries && nextUp && (
            <div className="detail-episode">
              {t('Episode {n}', { n: nextUp.number })}{nextUp.name ? `: ${nextUp.name}` : ''}
            </div>
          )}
          {card.overview && <p className="detail-overview">{card.overview}</p>}

          {(facts.cast && facts.cast.length > 0) && (
            <div className="detail-facts">
              {t('Cast')}: {facts.cast.slice(0, 3).join(', ')}
              {facts.crew && facts.crew.length > 0 && (
                <div>
                  {facts.crew_heading === 'Creators' ? t('Creator') : t('Director')}: {facts.crew.join(', ')}
                </div>
              )}
            </div>
          )}

          {state.busy && !isSeries && (
            <div className="detail-progress">
              <div>
                {t(stateLabel(state), stateVars(state))}
                {download && download.dl_speed > 0 ? ` · ${formatSpeed(download.dl_speed)}` : ''}
                {download && download.eta_seconds ? ` · ${t('{time} left', { time: formatEta(download.eta_seconds) })}` : ''}
              </div>
              <div className="dim">
                {state.id === 'preparing'
                  ? t('Building the playable version. This takes a few minutes and only happens once.')
                  : t('{size} downloaded', { size: formatBytes(download.downloaded_bytes) })}
              </div>
            </div>
          )}
          {download && download.prepare_error && (
            <div className="detail-note">{t('It arrived but could not be made playable. Try again.')}</div>
          )}
          {note && <div className="detail-note">{note}</div>}

          {card.media_id && onRate && (
            <div className="rate-row" ref={rateRef}>
              {[
                { value: -1, icon: 'dislike', title: t('Not for me') },
                { value: 1, icon: 'like', title: t('Like it!') },
              ].map((r, i) => (
                <button
                  key={r.value}
                  className={[
                    'rate-btn',
                    rating === r.value ? 'active' : '',
                    zone === 'rate' && rateIndex === i ? 'focused' : '',
                  ].join(' ')}
                  onMouseEnter={() => {
                    setZone('rate')
                    setRateIndex(i)
                  }}
                  onClick={() => onRate(card.media_id, r.value)}
                  title={r.title}
                >
                  <Icon name={r.icon} size={28} />
                </button>
              ))}
              {zone === 'rate' && <span className="rate-label">{[t('Not for me'), t('Like it!')][rateIndex]}</span>}
            </div>
          )}

          <div className="action-list">
            {actions.map((a, i) => (
              <div
                key={a.id}
                ref={(el) => { actionRefs.current[i] = el }}
                className={[
                  'action',
                  a.busy ? 'status' : '',
                  zone === 'actions' && actionIndex === i ? 'focused' : '',
                ].join(' ')}
                onMouseEnter={() => {
                  setZone('actions')
                  setActionIndex(i)
                }}
                onClick={() => run(a.id)}
              >
                {a.busy ? (
                  <ProgressRing percent={a.percent} size={28} stroke={4} indeterminate={a.spin} />
                ) : (
                  <Icon name={a.icon} size={28} />
                )}
                <span className="action-label">{busy && a.id === 'download' ? t('Queuing...') : a.label}</span>
                {a.failed && !busy && <span className="fail-badge corner">!</span>}
                {a.percent > 0 && !a.busy && (
                  <span className="action-progress"><span style={{ width: `${a.percent}%` }} /></span>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {view === 'main' && similar.length > 0 && (
        <div className={`detail-similar ${zone === 'similar' ? 'raised' : ''}`}>
          <h2 className="row-title">
            <Icon name="grid" size={24} /> {t('Similar')}
          </h2>
          <div className="row-strip" ref={similarRef}>
            <div className="row-track">
            {similar.map((other, i) => (
              <div
                key={other.media_id || i}
                ref={(el) => { similarRefs.current[i] = el }}
                className={`tile small ${zone === 'similar' && similarIndex === i ? 'focused' : ''}`}
                onMouseEnter={() => {
                  setZone('similar')
                  setSimilarIndex(i)
                }}
                onClick={() => onOpenTitle(other)}
              >
                {other.poster ? <img src={tilePoster(other.poster)} alt="" /> : <div className="tile-fallback">{other.title}</div>}
              </div>
            ))}
            </div>
          </div>
        </div>
      )}

      {view === 'episodes' && (
        <div className="episodes-view">
          <div className="side-rail">
            {smallHeading}
            {shortMeta}
            <div className="seasons-list" ref={seasonListRef}>
              {seasons.map((s, i) => (
                <div
                  key={s.number}
                  ref={(el) => { seasonRefs.current[i] = el }}
                  className={[
                    'menu-item',
                    i === seasonIndex ? 'active' : '',
                    epColumn === 'seasons' && i === seasonIndex ? 'focused' : '',
                  ].join(' ')}
                  onMouseEnter={() => setEpColumn('seasons')}
                  onClick={() => changeSeason(i)}
                >
                  <span>{s.name}</span>
                  <span className="menu-aside">
                    {s.downloaded && <span className="season-dot" />}
                    {s.episode_count ? tp('{n} episode', '{n} episodes', s.episode_count) : ''}
                  </span>
                </div>
              ))}
            </div>
          </div>

          <div className="episode-list" ref={episodeListRef}>
            {/* One child, so the slide moves one layer and leaves each episode's own scale alone. */}
            <div className="episode-track">
              {season && (
                <div className="episode-season">
                  {season.name}
                  {facts.certification && <span className="badge cert">{facts.certification}</span>}
                </div>
              )}
              {seasonButton && (
                <div
                  ref={(el) => { episodeRefs.current[-1] = el }}
                  className={`action season-download ${epColumn === 'episodes' && episodeIndex === -1 ? 'focused' : ''}`}
                  onMouseEnter={() => {
                    setEpColumn('episodes')
                    setEpisodeIndex(-1)
                  }}
                  onClick={pressSeason}
                >
                  <SeasonDownloadIcon size={28} />
                  <span className="action-label">{busy ? t('Queuing...') : seasonButtonLabel}</span>
                </div>
              )}
              {note && <div className="episode-note">{note}</div>}
              {loadingEpisodes && shownEpisodes.length === 0 && (
                <div className="episode-note">{t('Loading episodes...')}</div>
              )}
              {!loadingEpisodes && shownEpisodes.length === 0 && (
                <div className="episode-note">{t('No episodes listed for this season yet.')}</div>
              )}
              {shownEpisodes.map((e, i) => {
                const current = episodeIndex === i
                const focused = epColumn === 'episodes' && current
                const downloading = !e.available && e.download
                const progress = episodeProgress(e)
                return (
                  <div
                    key={e.id}
                    ref={(el) => { episodeRefs.current[i] = el }}
                    className={[
                      'episode',
                      current ? 'current' : '',
                      focused ? 'focused' : '',
                      e.available ? '' : 'unavailable',
                    ].join(' ')}
                    onMouseEnter={() => {
                      setEpColumn('episodes')
                      setEpisodeIndex(i)
                    }}
                    onClick={() => pressEpisode(e)}
                  >
                    <div
                      className="episode-still"
                      style={!e.still && card.backdrop ? { backgroundImage: `url(${card.backdrop})` } : undefined}
                    >
                      {e.still && <img src={e.still} alt="" />}
                      <span className="episode-code">{t('S{s}:E{e}', { s: e.season, e: e.episode })}</span>
                      {e.playable && focused && <span className="episode-play"><PlayIcon size={34} /></span>}
                      {progress && !progress.failed && (
                        <span className="episode-ring">
                          <ProgressRing
                            percent={progress.percent}
                            size={62}
                            stroke={5}
                            label={`${Math.round(progress.percent)}%`}
                            indeterminate={progress.spin}
                          />
                        </span>
                      )}
                      {e.resume_percent > 1 && !e.watched && (
                        <span className="episode-resume"><span style={{ width: `${e.resume_percent}%` }} /></span>
                      )}
                    </div>
                    <div className="episode-body">
                      <div className="episode-title">{e.name || t('Episode {n}', { n: e.episode })}</div>
                      {e.overview && <p className="episode-overview">{e.overview}</p>}
                      <div className="episode-status">
                        {e.runtime ? <span>({t('{n}m', { n: e.runtime })})</span> : null}
                        {e.watched && <span className="watched">{t('Watched')}</span>}
                        {progress && !progress.failed && <span className="progress">{progress.label}</span>}
                        {progress && progress.failed && (
                          <span className="failed"><span className="fail-badge small">!</span>{progress.label}</span>
                        )}
                        {e.prepare_error && (
                          <span className="failed"><span className="fail-badge small">!</span>{t('Could not prepare')}</span>
                        )}
                        {!e.available && !downloading && <span>{episodeWait(e)}</span>}
                      </div>
                    </div>
                  </div>
                )
              })}
              <div className="list-spacer flow" />
            </div>
          </div>
        </div>
      )}

      {view === 'audio' && (
        <div className="side-view">
          <div className="side-rail">
            {smallHeading}
            {shortMeta}
            <p className="side-hint">{t('Plays with these the next time you press Play.')}</p>
          </div>
          <div className="track-columns" ref={trackListRef}>
            {!trackInfo && <div className="episode-note">{t('Loading...')}</div>}
            {trackItems.map((item, i) =>
              item.kind === 'head' ? (
                <h3 key={`h${i}`} className="track-head">{item.label}</h3>
              ) : (
                <div
                  key={`${item.kind}-${item.value}`}
                  ref={(el) => { trackRefs.current[i] = el }}
                  className={['menu-item', 'track', trackIndex === i ? 'focused' : ''].join(' ')}
                  onMouseEnter={() => setTrackIndex(i)}
                  onClick={() => chooseTrack(item)}
                >
                  <span className="track-tick">{chosen(item) ? <Icon name="check" size={24} /> : null}</span>
                  <span>{item.label}</span>
                </div>
              ),
            )}
            <div className="list-spacer" />
          </div>
        </div>
      )}

      {view === 'credits' && (
        <div className="side-view">
          <div className="side-rail">
            {smallHeading}
            {shortMeta}
            <div className="menu">
              {credits.map((c, i) => (
                <div
                  key={c.id}
                  className={`menu-item ${creditIndex === i ? 'focused' : ''}`}
                  onMouseEnter={() => setCreditIndex(i)}
                >
                  {c.label}
                </div>
              ))}
            </div>
          </div>
          <div className="credits" ref={creditsRef}>
            {credits.map((c, i) => (
              <section key={c.id} ref={(el) => { creditRefs.current[i] = el }} className="credit-section">
                <h3>{c.label}</h3>
                <div className={`credit-lines ${c.lines.length > 12 ? 'columns' : ''}`}>
                  {c.lines.map((line) => <div key={line}>{line}</div>)}
                </div>
              </section>
            ))}
            <div className="list-spacer" />
          </div>
        </div>
      )}

      {view === 'releases' && (
        <div className="side-view">
          <div className="side-rail">
            {smallHeading}
            {shortMeta}
            <h2 className="side-heading">{t('Versions')}</h2>
          </div>
          <div className="versions-list" ref={releaseListRef}>
            {releases.map((r, i) => (
              <div
                key={r.id}
                ref={(el) => { releaseRefs.current[i] = el }}
                className={`release-row ${releaseIndex === i ? 'focused' : ''}`}
                onMouseEnter={() => setReleaseIndex(i)}
                onClick={() => openRelease(r)}
              >
                <div className="rel-name">{r.name}</div>
                <div className="rel-tags">
                  {r.id === card.primary_release_id && <span className="rel-tag primary">{t('Best')}</span>}
                  {r.origin_label && <span className="rel-tag origin">{r.origin_label}</span>}
                  {r.debrid && <span className="rel-tag origin">Debrid</span>}
                  {r.resolution && <span className="rel-tag">{r.resolution}</span>}
                  {r.hdr && <span className="rel-tag">{r.hdr}</span>}
                  {r.video_codec && <span className="rel-tag">{r.video_codec}</span>}
                  {r.audio_codec && <span className="rel-tag">{r.audio_codec}</span>}
                  <span className="rel-tag">{r.size_gb} GB</span>
                  <span className="rel-tag">{t('{n} seeders', { n: r.seeders })}</span>
                  {r.download && <span className="rel-tag">{releaseState(r.download)}</span>}
                </div>
              </div>
            ))}
            <div className="list-spacer" />
          </div>
        </div>
      )}
    </div>
  )
}
