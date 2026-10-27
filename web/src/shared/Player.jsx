import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import ProgressRing from './ProgressRing'
import ClipEditor from './ClipEditor'
import PlayerChrome, { SPEEDS, speedLabel } from './PlayerChrome'
import PlayerSettings from './PlayerSettings'
import PlayerEpisodes from './PlayerEpisodes'
import PlayerStats from './PlayerStats'
import './player.css'
import { PlayIcon } from './icons'
import { getLanguage, t } from './i18n'
import { applyTrackPrefs, languageCode, loadTrackPrefs, saveTrackPrefs } from './trackPrefs'
import { useInputMode } from './input'
import { Filmstrip, useTrickplay } from './trickplay'
import {
  SUBTITLE_BOTTOM_RATIO,
  SUBTITLE_SIZES,
  SUBTITLE_STYLES,
  cueFontSize,
  loadAppearance,
  saveAppearance,
} from './tracks'

// Fallback D-pad stride before thumbnails exist, and the skip keys' step.
const SEEK_STEP = 10
const OVERLAY_TIMEOUT = 4000

function fmtTime(seconds) {
  if (!Number.isFinite(seconds) || seconds < 0) return '0:00'
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  return h
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`
}

// TV focus moves over PlayerChrome's four rows. Returning chrome lands on the
// scrubber so left and right seek at once.
const ROWS = ['top', 'centre', 'scrub', 'row']

// Share of the screen the picture keeps beside Settings and Episodes.
const BOX = 0.58
const STATS_KEY = 'vibestream.player.stats'

function loadStats() {
  try {
    return localStorage.getItem(STATS_KEY) === '1'
  } catch {
    return false
  }
}

function languageName(track) {
  if (!track) return ''
  const code = languageCode(track.language)
  if (code === 'en') return t('English')
  if (code === 'de') return t('German')
  if (code === 'ro') return t('Romanian')
  return shortTrackLabel(track.label, 'x', 16)
}

const RATING_CARD_MS = 6000

// Step per press, in thumbnail intervals: single frames first, then wider, since
// at eleven repeats a second single steps would take minutes to cross a film.
const SEEK_STRIDE_FAST = 4
const SEEK_STRIDE_FASTER = 12
const SEEK_STREAK_MS = 500

/** Shorten verbose container track names, e.g. "English (Original | English (United Kingdom))". */
function shortTrackLabel(label, id, limit = 22) {
  if (!id) return 'Off'
  if (!label) return 'On'
  let short = label.replace(/\s*\([^)]*\)\s*/g, ' ').trim()
  if (!short) short = label.trim()
  return short.length > limit ? `${short.slice(0, limit - 1).trimEnd()}...` : short
}

// Native HLS for Apple's player and webOS (hardware HEVC, so 4K HDR works);
// hls.js over MSE elsewhere. Chrome's native HLS seeks by downloading every
// segment in between.
function platformHls() {
  const nav = typeof navigator === 'undefined' ? {} : navigator
  return /Apple/.test(nav.vendor || '') || /Web0S|webOS/i.test(nav.userAgent || '')
}

const UP_NEXT_LEAD = 20
const UP_NEXT_AFTER_END = 5

// Scale of the 1920x1080 TV layout: 1 on the TV, the player's share of a 1920x1080
// screen in a browser, floored at 0.45 for readability.
function usePlayerScale(enabled, rootRef) {
  const measure = () => {
    if (!enabled || typeof window === 'undefined') return 1
    const el = rootRef.current
    const w = el && el.clientWidth ? el.clientWidth : window.innerWidth
    const h = el && el.clientHeight ? el.clientHeight : window.innerHeight
    return Math.max(0.45, Math.min(1, Math.min(w / 1920, h / 1080)))
  }
  const [scale, setScale] = useState(measure)
  useEffect(() => {
    if (!enabled) return undefined
    const onResize = () => setScale(measure())
    onResize()
    window.addEventListener('resize', onResize)
    const observer = typeof ResizeObserver !== 'undefined' && rootRef.current
      ? new ResizeObserver(onResize) : null
    if (observer) observer.observe(rootRef.current)
    return () => {
      window.removeEventListener('resize', onResize)
      if (observer) observer.disconnect()
    }
  }, [enabled])
  return scale
}

/** `variant`: "tv" (remote via registerHandler) or "browser" (mouse, touch, keyboard). */
export default function Player({
  playId, title, onExit, onNext, registerHandler, variant = 'tv', fromStart = false,
  // Start position from another device handing over.
  startAt = null,
  // Remote control from another device: { subscribe(fn), report(state) }.
  remote = null,
  // Browser only: playing inline in the title dialog.
  inline = false,
  onFull = null,
  // Start full screen: the previous episode was playing full screen.
  startFull = false,
}) {
  const browser = variant === 'browser'
  const rootRef = useRef(null)
  const scale = usePlayerScale(browser, rootRef)
  const lastPointer = useRef('mouse')
  const [fullscreen, setFullscreen] = useState(() => browser && Boolean(
    document.fullscreenElement || document.webkitFullscreenElement))
  const videoRef = useRef(null)
  const hlsRef = useRef(null)
  const overlayTimer = useRef(null)
  const cueLayerRef = useRef(null)
  const activeTrackLabel = useRef(null)
  // The app's own <track>, known by identity: the stream's tracks share its label.
  const ownTrack = useRef(null)
  const resumeApplied = useRef(false)
  const scrubRef = useRef(null)
  // Mirrors seekTarget for closures built a render ago.
  const seekTargetRef = useRef(null)
  // Until a seek lands, time updates still carry the old position; this keeps the
  // scrubber from jumping back.
  const pendingSeekRef = useRef(null)
  const seekStreak = useRef({ dir: 0, count: 0, at: 0 })
  const resumeAfterSeek = useRef(false)

  const [info, setInfo] = useState(null)
  const [error, setError] = useState(null)
  const [ready, setReady] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)
  const [buffered, setBuffered] = useState(0)
  const [overlay, setOverlay] = useState(true)
  const [zone, setZone] = useState('scrub')
  const [control, setControl] = useState(0)   // index within the focused row
  const [seekTarget, setSeekTarget] = useState(null)
  const [hover, setHover] = useState(null)
  const [dragTime, setDragTime] = useState(null)
  const [side, setSide] = useState(null) // null | 'settings' | 'episodes'
  const [settingsPage, setSettingsPage] = useState(null)
  const [tray, setTray] = useState(null) // null | 'speed'
  const [trayIndex, setTrayIndex] = useState(2)
  const [statsShown, setStatsShown] = useState(loadStats)
  const [rate, setRate] = useState(1)
  const [volume, setVolume] = useState({ level: 1, muted: false })
  const [box, setBox] = useState(null)
  const sideRef = useRef(null)
  const rowIdsRef = useRef([])
  const stageRef = useRef(null)
  const [clipping, setClipping] = useState(false)
  const [subtitleId, setSubtitleId] = useState(null)
  const [audioIndex, setAudioIndex] = useState(null)
  const [appearance, setAppearance] = useState(loadAppearance)
  const [prepared, setPrepared] = useState(false)
  const [ended, setEnded] = useState(false)
  const [creditsChosen, setCreditsChosen] = useState(false)
  const [upNextFocus, setUpNextFocus] = useState('next')
  const [fill, setFill] = useState(null)
  // Bumped on every completed seek so the up-next fill is re-timed.
  const [seekEpoch, setSeekEpoch] = useState(0)
  // hls.js clears every text track on the media (`_cleanTracks`) when it loads a
  // source and attaches. The app's <track> is appended only after MANIFEST_PARSED, or its
  // cues can be wiped. The native path needs no wait.
  const [cuesSafe, setCuesSafe] = useState(false)
  const [_preparation, setPreparation] = useState(null)

  const mode = useInputMode()
  const pointer = mode === 'pointer'
  const trick = useTrickplay(playId, prepared)

  const showOverlay = useCallback(() => {
    setOverlay(true)
    clearTimeout(overlayTimer.current)
    overlayTimer.current = setTimeout(() => {
      if (seekTargetRef.current !== null) return
      setOverlay(false)
    }, OVERLAY_TIMEOUT)
  }, [])

  // Hiding the chrome resets focus, so it returns on the scrubber.
  useEffect(() => {
    if (!overlay) {
      setZone('scrub')
      setControl(0)
    }
  }, [overlay])

  useEffect(() => {
    let alive = true
    api
      .playInfo(playId)
      .then((data) => {
        if (!alive) return
        setInfo(data)
        const def = data.subtitles?.find((s) => s.default) || null
        const chosen = applyTrackPrefs(loadTrackPrefs(data.media_id), data)
        setSubtitleId(chosen.subtitleId !== undefined ? chosen.subtitleId : def ? def.id : null)
        if (chosen.audioIndex !== null) setAudioIndex(chosen.audioIndex)
      })
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [playId])

  useEffect(() => {
    saveAppearance(appearance)
  }, [appearance])

  // Subtitles are drawn by us. ::cue support is narrow and inconsistent (partial on
  // webOS) and cannot position cues on the picture. A `hidden` track still parses
  // and times cues without the browser drawing them.
  useEffect(() => {
    const video = videoRef.current
    const layer = cueLayerRef.current
    if (!video || !layer) return undefined

    let track = null

    const paint = () => {
      layer.textContent = ''
      const active = track?.activeCues
      if (!active || !active.length) return
      for (const cue of active) {
        const line = document.createElement('div')
        line.className = 'cue-line'
        // getCueAsHTML keeps italics and bold, and builds nodes rather than parsing HTML.
        line.appendChild(cue.getCueAsHTML())
        layer.appendChild(line)
      }
    }

    // The app's track hidden, every other one off. Safari turns on the manifest's
    // subtitle rendition, which shares its label, and would draw a second copy.
    const attach = () => {
      const own = ownTrack.current?.track || null
      const found = !subtitleId ? null : own || Array.from(video.textTracks).find(
        (t) => t.mode !== 'disabled' || t.label === activeTrackLabel.current,
      )
      Array.from(video.textTracks).forEach((t) => {
        if (t === found) {
          if (t.mode !== 'hidden') t.mode = 'hidden'
        } else if (t.mode !== 'disabled') {
          t.mode = 'disabled'
        }
      })
      if (track === found) return
      if (track) track.removeEventListener('cuechange', paint)
      track = found || null
      if (track) {
        track.mode = 'hidden' // parsed and timed, but not drawn by the browser
        track.addEventListener('cuechange', paint)
      }
      paint()
    }

    attach()
    video.textTracks.addEventListener?.('addtrack', attach)
    video.textTracks.addEventListener?.('change', attach)
    const poll = setInterval(attach, 1000)

    return () => {
      clearInterval(poll)
      video.textTracks.removeEventListener?.('addtrack', attach)
      video.textTracks.removeEventListener?.('change', attach)
      if (track) track.removeEventListener('cuechange', paint)
      layer.textContent = ''
    }
  }, [subtitleId, prepared])

  // Position cues against the displayed picture, not the element: with object-fit:
  // contain, the element bottom is inside the letterbox bar.
  useEffect(() => {
    const video = videoRef.current
    const layer = cueLayerRef.current
    if (!video || !layer) return undefined

    const place = () => {
      const ew = video.clientWidth
      const eh = video.clientHeight
      const vw = video.videoWidth
      const vh = video.videoHeight
      if (!ew || !eh) return
      let pictureHeight = eh
      let barBottom = 0
      if (vw && vh) {
        const scale = Math.min(ew / vw, eh / vh)
        pictureHeight = vh * scale
        barBottom = (eh - pictureHeight) / 2
      }
      layer.style.bottom = `${barBottom + pictureHeight * SUBTITLE_BOTTOM_RATIO}px`
      layer.style.left = '6%'
      layer.style.right = '6%'
    }

    place()
    const timer = setInterval(place, 1000)
    window.addEventListener('resize', place)
    video.addEventListener('loadedmetadata', place)
    return () => {
      clearInterval(timer)
      window.removeEventListener('resize', place)
      video.removeEventListener('loadedmetadata', place)
    }
  }, [prepared])

  // The rendition must be complete before the element loads it: a playlist without
  // an end tag is live, and players join live streams at the live edge.
  useEffect(() => {
    if (!info) return undefined
    let alive = true
    let timer = null

    const poll = async () => {
      try {
        const state = await api.prepare(playId, audioIndex)
        if (!alive) return
        setPreparation(state)
        if (state.error) {
          setError(state.error)
          return
        }
        if (state.ready) {
          setPrepared(true)
          return
        }
        timer = setTimeout(poll, 2000)
      } catch (e) {
        if (!alive) return
        timer = setTimeout(poll, 4000)
      }
    }

    setPrepared(false)
    poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [info, playId, audioIndex])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !info || !prepared) return undefined

    const src =
      audioIndex === null
        ? info.playback.hls
        : `${info.playback.hls}?audio=${audioIndex}`
    let cancelled = false

    const startHlsJs = async () => {
      try {
        const mod = await import('hls.js')
        if (cancelled) return
        const Hls = mod.default
        if (!Hls.isSupported()) {
          // No MediaSource (iPhone before iOS 17): use the element's own HLS.
          if (video.canPlayType('application/vnd.apple.mpegurl')) startNative()
          else setError("This browser can't play this video.")
          return
        }
        const hls = new Hls({
          enableWorker: true,
          lowLatencyMode: false,
          fragLoadingTimeOut: 120000,
          manifestLoadingTimeOut: 60000,
          // Off: otherwise hls.js adopts the app's <track> (same label and language) and
          // parses the same VTT again, drawing every line twice. Deselecting the rendition
          // instead makes hls.js disable every text track, the app's included.
          renderTextTracksNatively: false,
        })
        // hls.js sets the selected subtitle track to 'showing' on every switch, which makes
        // the browser draw a second copy. This is a setter on the instance; as a config
        // key it is silently ignored.
        hls.subtitleDisplay = false
        hlsRef.current = hls
        hls.on(Hls.Events.ERROR, (_evt, data) => {
          if (data.fatal) {
            setError(/codec|incompatible|mediaerror/i.test(`${data.details} ${data.type}`)
              ? "This browser can't play this video."
              : "The video stopped loading. Try again.")
          }
        })
        hls.loadSource(src)
        hls.attachMedia(video)
        hls.on(Hls.Events.MANIFEST_PARSED, () => {
          // Both calls above clear text tracks; see `cuesSafe`.
          setCuesSafe(true)
          video.play().catch(() => {})
        })
      } catch (e) {
        setError(`Could not load the player: ${e.message}`)
      }
    }

    // In a browser the element gets the media playlist, not the master: Safari drops a
    // PQ variant on an SDR screen and then refuses the title. A media playlist plays
    // tone mapped.
    const startNative = () => {
      video.src = browser ? src.replace(/master\.m3u8/, 'index.m3u8') : src
      setCuesSafe(true) // nothing here clears text tracks
      video.play().catch(() => {})
    }

    // The legacy (webOS 4.5) build uses MSE: its native player reports healthy
    // playback while the picture freezes, undetectably.
    if (!import.meta.env.LEGACY_TV && platformHls() && video.canPlayType('application/vnd.apple.mpegurl')) startNative()
    else startHlsJs()

    return () => {
      cancelled = true
      setCuesSafe(false)
      if (hlsRef.current) {
        hlsRef.current.destroy()
        hlsRef.current = null
      }
      video.removeAttribute('src')
      video.load()
    }
    // `prepared` MUST be a dependency: the effect returns early while preparing.
  }, [info, audioIndex, prepared, browser])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    const onTime = () => {
      const pending = pendingSeekRef.current
      if (pending && Date.now() - pending.at < 15000) return
      setCurrent(video.currentTime)
      if (video.buffered.length) {
        setBuffered(video.buffered.end(video.buffered.length - 1))
      }
    }
    const onMeta = () => {
      // A growing EVENT playlist reports Infinity duration; fall back to ffprobe's.
      const probed = info?.media?.duration || 0
      setDuration(Number.isFinite(video.duration) && video.duration > 0
        ? video.duration
        : probed)
      setReady(true)
    }
    const onPlay = () => {
      setPlaying(true)
      setEnded(false)
    }
    const onPause = () => setPlaying(false)
    const onEnded = () => setEnded(true)
    const onSeeked = () => {
      if (!video.seeking) {
        pendingSeekRef.current = null
        setCurrent(video.currentTime)
      }
      setSeekEpoch((n) => n + 1)
    }
    const onError = () => setError("This browser can't play this video.")

    video.addEventListener('timeupdate', onTime)
    video.addEventListener('loadedmetadata', onMeta)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    video.addEventListener('error', onError)
    video.addEventListener('ended', onEnded)
    video.addEventListener('seeked', onSeeked)
    return () => {
      video.removeEventListener('ended', onEnded)
      video.removeEventListener('seeked', onSeeked)
      video.removeEventListener('timeupdate', onTime)
      video.removeEventListener('loadedmetadata', onMeta)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
      video.removeEventListener('error', onError)
    }
  }, [info])

  useEffect(() => {
    const video = videoRef.current
    if (!video || !cuesSafe) return
    Array.from(video.querySelectorAll('track[data-vibestream]')).forEach((t) => t.remove())
    ownTrack.current = null
    if (!subtitleId) {
      Array.from(video.textTracks).forEach((t) => (t.mode = 'disabled'))
      return
    }
    const chosen = info?.subtitles?.find((s) => s.id === subtitleId)
    const track = document.createElement('track')
    track.kind = 'subtitles'
    track.src = `/api/play/${playId}/subs/${subtitleId}.vtt`
    track.default = true
    track.setAttribute('data-vibestream', '1')
    track.srclang = chosen?.language || 'und'
    track.label = chosen?.label || 'Subtitles'
    video.appendChild(track)
    ownTrack.current = track
    activeTrackLabel.current = track.label
    setTimeout(() => {
      Array.from(video.textTracks).forEach((t) => {
        t.mode = t === track.track ? 'hidden' : 'disabled'
      })
    }, 60)
  }, [subtitleId, playId, info, cuesSafe])

  // Position is reported periodically and on unmount. `resumeApplied` stops the
  // periodic report from re-seeking to the stored position.
  useEffect(() => {
    if (!prepared || !ready) return undefined
    const video = videoRef.current
    if (!video) return undefined

    if (!resumeApplied.current) {
      resumeApplied.current = true
      const start = fromStart ? 0 : info?.resume?.seconds || 0
      if (typeof startAt === 'number' && Number.isFinite(video.duration)) {
        video.currentTime = Math.max(0, Math.min(startAt, video.duration - 1))
      } else if (start > 30 && Number.isFinite(video.duration) && start < video.duration - 60) {
        video.currentTime = start
      }
    }

    const report = () => {
      if (!video.duration || !Number.isFinite(video.duration)) return
      api
        .reportProgress(playId, Math.floor(video.currentTime), Math.floor(video.duration))
        .catch(() => {})
    }

    const timer = setInterval(() => {
      if (!video.paused) report()
    }, 10000)

    return () => {
      clearInterval(timer)
      report() // final position on the way out
    }
     
  }, [prepared, ready, playId, info])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) video.play().catch(() => {})
    else video.pause()
    showOverlay()
  }, [showOverlay])

  const jumpTo = useCallback((time) => {
    const video = videoRef.current
    if (!video) return
    pendingSeekRef.current = { time, at: Date.now() }
    setCurrent(time)
    video.currentTime = time
  }, [])

  const seekBy = useCallback(
    (delta) => {
      const video = videoRef.current
      if (!video || !Number.isFinite(video.duration)) return
      const from = pendingSeekRef.current ? pendingSeekRef.current.time : video.currentTime
      jumpTo(Math.max(0, Math.min(video.duration - 1, from + delta)))
      showOverlay()
    },
    [showOverlay],
  )

  /* Remote control from another device; state is reported every 2s and on play/pause. */
  useEffect(() => {
    if (!remote) return undefined
    return remote.subscribe((command) => {
      const video = videoRef.current
      if (!video) return
      if (command.type === 'pause') video.pause()
      else if (command.type === 'resume') video.play().catch(() => {})
      else if (command.type === 'seek' && typeof command.position === 'number' &&
        Number.isFinite(video.duration)) {
        jumpTo(Math.max(0, Math.min(command.position, video.duration - 1)))
      } else if (command.type === 'skip' && typeof command.delta === 'number') seekBy(command.delta)
      else if (command.type === 'stop') onExit()
      showOverlay()
    })
  }, [remote, seekBy, onExit, showOverlay])

  const castTracks = useRef({})
  const castSend = useRef(null)
  useEffect(() => {
    if (!remote) return undefined
    const video = videoRef.current
    const send = () => {
      const v = videoRef.current
      if (!v || !Number.isFinite(v.duration)) return
      const ep = info?.presentation?.episode
      remote.report({
        play_id: playId,
        media_id: info?.media_id ?? null,
        title: info?.presentation?.title || title,
        detail: ep ? `S${ep.season}:E${ep.number}${ep.name ? `  ${ep.name}` : ''}` : null,
        position: Math.floor(v.currentTime),
        duration: Math.floor(v.duration),
        paused: v.paused,
        presentation: info?.presentation || null,
        subtitles: info?.subtitles || [],
        audio: info?.audio || [],
        ...castTracks.current,
      })
    }
    castSend.current = send
    const timer = setInterval(send, 2000)
    if (video) {
      video.addEventListener('play', send)
      video.addEventListener('pause', send)
      video.addEventListener('seeked', send)
    }
    return () => {
      clearInterval(timer)
      if (video) {
        video.removeEventListener('play', send)
        video.removeEventListener('pause', send)
        video.removeEventListener('seeked', send)
      }
    }
  }, [remote, playId, info, title, ready])

  useEffect(() => () => { if (remote) remote.report(null) }, [remote])

  const restart = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    jumpTo(0)
    video.play().catch(() => {})
    showOverlay()
  }, [showOverlay])

  /* An iPhone only allows the video element itself to go full screen. */
  const canFullscreen = browser && typeof document !== 'undefined' && Boolean(
    document.fullscreenEnabled || document.webkitFullscreenEnabled ||
      (typeof HTMLVideoElement !== 'undefined' &&
        'webkitEnterFullscreen' in HTMLVideoElement.prototype),
  )

  // Full screen goes on the frame around the player when there is one: the browser
  // exits full screen when its element is removed, and each episode is a new player.
  const screenTarget = () =>
    rootRef.current?.closest('[data-player-frame]') || rootRef.current

  const toggleFullscreen = useCallback(() => {
    const root = screenTarget()
    const video = videoRef.current
    const active = document.fullscreenElement || document.webkitFullscreenElement
    if (active) {
      (document.exitFullscreen || document.webkitExitFullscreen)?.call(document)
      return
    }
    const enter = root?.requestFullscreen || root?.webkitRequestFullscreen
    if (enter && (document.fullscreenEnabled || document.webkitFullscreenEnabled)) {
      Promise.resolve(enter.call(root))
        .then(() => window.screen?.orientation?.lock?.('landscape'))
        .catch(() => {})
    } else if (video?.webkitEnterFullscreen) {
      video.webkitEnterFullscreen()
    }
  }, [])

  /* Where the browser has no full screen API (iPhone), the player still fills the window. */
  const [immersive, setImmersive] = useState(inline && startFull)
  const enterFull = useCallback(() => {
    setImmersive(true)
    const root = screenTarget()
    const enter = root && (root.requestFullscreen || root.webkitRequestFullscreen)
    if (enter && (document.fullscreenEnabled || document.webkitFullscreenEnabled)) {
      Promise.resolve(enter.call(root))
        .then(() => window.screen?.orientation?.lock?.('landscape'))
        .catch(() => {})
    }
  }, [])
  const exitFull = useCallback(() => {
    setImmersive(false)
    if (document.fullscreenElement || document.webkitFullscreenElement) {
      (document.exitFullscreen || document.webkitExitFullscreen)?.call(document)
    }
  }, [])

  const [sideways, setSideways] = useState(false)
  useEffect(() => {
    if (!inline || !window.matchMedia) return undefined
    const query = window.matchMedia('(orientation: landscape) and (max-height: 500px)')
    const sync = () => setSideways(query.matches)
    sync()
    if (query.addEventListener) query.addEventListener('change', sync)
    return () => query.removeEventListener && query.removeEventListener('change', sync)
  }, [inline])

  const full = !inline || immersive || sideways
  useEffect(() => {
    if (onFull) onFull(full)
  }, [full, onFull])

  useEffect(() => {
    if (!browser) return undefined
    const sync = () => {
      const now = Boolean(document.fullscreenElement || document.webkitFullscreenElement)
      setFullscreen(now)
      if (!now) setImmersive(false)
    }
    document.addEventListener('fullscreenchange', sync)
    document.addEventListener('webkitfullscreenchange', sync)
    return () => {
      document.removeEventListener('fullscreenchange', sync)
      document.removeEventListener('webkitfullscreenchange', sync)
    }
  }, [browser])

  useEffect(() => {
    if (!browser || !videoRef.current) return
    try {
      const saved = Number(localStorage.getItem('vibestream.volume'))
      if (saved >= 0 && saved <= 1 && localStorage.getItem('vibestream.volume') !== null) {
        videoRef.current.volume = saved
      }
    } catch {
    }
  }, [browser])

  // A mouse click plays or pauses; a tap toggles the controls, or pausing would be
  // the only way to reach them.
  const onPictureClick = useCallback(() => {
    if (side) {
      togglePlay()
      return
    }
    if (tray) {
      setTray(null)
      return
    }
    if (lastPointer.current === 'mouse') {
      togglePlay()
      return
    }
    if (overlay) {
      clearTimeout(overlayTimer.current)
      setOverlay(false)
    } else {
      showOverlay()
    }
  }, [side, tray, overlay, togglePlay, showOverlay])

  // The D-pad picks a target and OK commits it: a real seek per press on a 4K
  // stream would keep the decoder catching up.
  const nudgeSeek = useCallback(
    (direction) => {
      const video = videoRef.current
      if (!video || !duration) return

      const now = Date.now()
      const streak = seekStreak.current
      if (streak.dir !== direction || now - streak.at > SEEK_STREAK_MS) {
        streak.dir = direction
        streak.count = 0
      }
      streak.count += 1
      streak.at = now

      const unit = trick?.interval || SEEK_STEP
      let stride = unit
      if (streak.count > SEEK_STRIDE_FASTER) stride = unit * SEEK_STRIDE_FASTER
      else if (streak.count > SEEK_STRIDE_FAST) stride = unit * SEEK_STRIDE_FAST

      if (seekTargetRef.current === null) {
        resumeAfterSeek.current = !video.paused
        video.pause()
      }

      const base = seekTargetRef.current === null ? video.currentTime : seekTargetRef.current
      const next = Math.max(0, Math.min(duration - 1, base + direction * stride))
      seekTargetRef.current = next
      setSeekTarget(next)
      showOverlay()
    },
    [duration, trick, showOverlay],
  )

  const commitSeek = useCallback(() => {
    const target = seekTargetRef.current
    if (target === null) return
    seekTargetRef.current = null
    setSeekTarget(null)
    const video = videoRef.current
    if (video) {
      jumpTo(target)
      if (resumeAfterSeek.current) video.play().catch(() => {})
    }
    showOverlay()
  }, [showOverlay])

  const cancelSeek = useCallback(() => {
    if (seekTargetRef.current === null) return
    seekTargetRef.current = null
    setSeekTarget(null)
    if (resumeAfterSeek.current) videoRef.current?.play().catch(() => {})
    showOverlay()
  }, [showOverlay])

  const ratioAt = useCallback((clientX) => {
    const el = scrubRef.current
    if (!el) return 0
    const rect = el.getBoundingClientRect()
    return Math.min(1, Math.max(0, (clientX - rect.left) / rect.width))
  }, [])

  const trackHover = useCallback(
    (clientX) => {
      const el = scrubRef.current
      if (!el || !duration) return
      const ratio = ratioAt(clientX)
      setHover({ time: ratio * duration, left: ratio * el.clientWidth })
    },
    [duration, ratioAt],
  )

  /* Listeners on the window, so a drag that leaves the thin bar keeps going. */
  const startDrag = useCallback(
    (event) => {
      const video = videoRef.current
      if (!video || !duration) return
      event.preventDefault()

      const move = (e) => {
        trackHover(e.clientX)
        setDragTime(ratioAt(e.clientX) * duration)
      }
      const up = (e) => {
        window.removeEventListener('mousemove', move)
        window.removeEventListener('mouseup', up)
        jumpTo(ratioAt(e.clientX) * duration)
        setDragTime(null)
        showOverlay()
      }

      window.addEventListener('mousemove', move)
      window.addEventListener('mouseup', up)
      move(event) // a click with no drag still lands on the right frame
    },
    [duration, ratioAt, trackHover, showOverlay],
  )

  /* Choices are remembered per title by language, for the next episode and the title page. */
  const rememberTracks = useCallback((subId, audioIdx) => {
    const mediaId = info?.media_id
    if (!mediaId) return
    const next = { ...(loadTrackPrefs(mediaId) || {}) }
    if (subId !== undefined) {
      const sub = (info.subtitles || []).find((x) => x.id === subId)
      next.subs = subId === null ? 'off' : languageCode(sub && sub.language) || next.subs || null
    }
    if (audioIdx !== undefined) {
      const track = (info.audio || []).find((x) => x.index === audioIdx)
      next.audio = audioIdx === null || !track || track.default ? null : languageCode(track.language)
    }
    saveTrackPrefs(mediaId, next)
  }, [info])

  const next = info?.next || null
  const remaining = duration > 0 ? duration - current : Infinity
  const upNext = Boolean(
    next && onNext && prepared && ready && !error && !side &&
      (ended || (!creditsChosen && remaining <= UP_NEXT_LEAD)),
  )
  const clock = useRef({ current: 0, duration: 0 })
  clock.current = { current, duration }
  const fillRef = useRef(null)
  fillRef.current = fill
  const advanced = useRef(false)

  const goNext = useCallback(() => {
    if (advanced.current || !next || !onNext) return
    advanced.current = true
    onNext(next)
  }, [next, onNext])

  const chooseCredits = useCallback(() => {
    setCreditsChosen(true)
    setFill(null)
  }, [])

  // The up-next fill is timed to the episode's end, so it can never cut it short.
  useEffect(() => {
    if (!upNext) {
      if (fillRef.current) setFill(null)
      return
    }
    if (ended) {
      if (fillRef.current && fillRef.current.toEnd) goNext()
      else setFill({ key: Date.now(), duration: UP_NEXT_AFTER_END, delay: 0, toEnd: false })
      return
    }
    const left = Math.max(0, clock.current.duration - clock.current.current)
    const done = UP_NEXT_LEAD - Math.min(left, UP_NEXT_LEAD)
    setFill({ key: Date.now(), duration: UP_NEXT_LEAD, delay: -done, toEnd: true })
  }, [upNext, ended, seekEpoch, goNext])

  useEffect(() => {
    if (upNext) setUpNextFocus('next')
  }, [upNext])

  useEffect(() => {
    if (creditsChosen && remaining > UP_NEXT_LEAD + 5) setCreditsChosen(false)
  }, [creditsChosen, remaining])

  useEffect(() => {
    if (ended && (!next || !onNext)) onExit()
  }, [ended, next, onNext, onExit])

  const effectiveAudio = audioIndex === null
    ? ((info?.audio || []).find((a) => a.default) || {}).index
    : audioIndex

  castTracks.current = {
    subtitle_id: subtitleId || null,
    audio_index: effectiveAudio ?? null,
    subtitle_size: appearance.size,
    subtitle_style: appearance.style,
  }
  useEffect(() => {
    if (castSend.current) castSend.current()
  }, [subtitleId, effectiveAudio, appearance])
  useEffect(() => {
    if (!remote) return undefined
    return remote.subscribe((command) => {
      if (command.type === 'subtitle') {
        const id = command.subtitle_id && command.subtitle_id !== 'off' ? command.subtitle_id : null
        setSubtitleId(id)
        rememberTracks(id, undefined)
      } else if (command.type === 'audio' && typeof command.audio_index === 'number') {
        const track = (info?.audio || []).find((a) => a.index === command.audio_index)
        const value = !track || track.default ? null : track.index
        setAudioIndex(value)
        rememberTracks(undefined, value)
      } else if (command.type === 'appearance') {
        setAppearance((a) => ({
          size: SUBTITLE_SIZES.some((x) => x.id === command.subtitle_size) ? command.subtitle_size : a.size,
          style: SUBTITLE_STYLES.some((x) => x.id === command.subtitle_style) ? command.subtitle_style : a.style,
        }))
      }
    })
  }, [remote, info, rememberTracks])

  /* Once per title, not after every pause or seek. */
  const [ratingCard, setRatingCard] = useState(false)
  const ratingShown = useRef(false)
  const certification = info?.presentation?.certification
  useEffect(() => {
    if (browser || !certification || ratingShown.current || !playing) return undefined
    ratingShown.current = true
    setRatingCard(true)
    const timer = setTimeout(() => setRatingCard(false), RATING_CARD_MS)
    return () => clearTimeout(timer)
  }, [browser, certification, playing])

  const ep = info?.presentation?.episode || null

  const openSide = useCallback((which) => {
    cancelSeek() // a panel and a half-finished seek must not share the screen
    setTray(null)
    setSide(which)
  }, [cancelSeek])

  const closeSide = useCallback(() => {
    const opener = side
    setSide(null)
    setZone('row')
    setControl(Math.max(0, rowIdsRef.current.indexOf(opener)))
    showOverlay()
  }, [side, showOverlay])

  // A transform rather than a resize, so it only composites and the cues shrink with it.
  useEffect(() => {
    const root = rootRef.current
    if (!side || !root || (inline && !full)) {
      setBox(null)
      return undefined
    }
    const measure = () => {
      const w = root.clientWidth
      const h = root.clientHeight
      // 16:9 first, so the rounded corners are the film's, not a letterbox band's.
      const sw = Math.min(w, (h * 16) / 9)
      const sh = (sw * 9) / 16
      if (h > w) {
        setBox({ portrait: true, x: 0, y: 12 * scale, s: 1, w: sw, h: sh, top: sh + 24 * scale })
      } else {
        const s = Math.min((w * BOX) / sw, (h - 96 * scale) / sh)
        setBox({ portrait: false, x: 40 * scale, y: (h - sh * s) / 2, s, w: sw, h: sh })
      }
    }
    measure()
    window.addEventListener('resize', measure)
    return () => window.removeEventListener('resize', measure)
  }, [side, scale, inline, full])

  useEffect(() => {
    try {
      localStorage.setItem(STATS_KEY, statsShown ? '1' : '0')
    } catch {
    }
  }, [statsShown])

  // The element is the source of truth for speed and volume.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    const sync = () => {
      setRate(video.playbackRate)
      setVolume({ level: video.volume, muted: video.muted })
    }
    sync()
    video.addEventListener('ratechange', sync)
    video.addEventListener('volumechange', sync)
    return () => {
      video.removeEventListener('ratechange', sync)
      video.removeEventListener('volumechange', sync)
    }
  }, [])

  const applyRate = useCallback((value) => {
    const video = videoRef.current
    if (video) video.playbackRate = value
  }, [])

  const openSpeed = useCallback(() => {
    if (tray === 'speed') {
      setTray(null)
      return
    }
    setTrayIndex(Math.max(0, SPEEDS.indexOf(rate)))
    setTray('speed')
  }, [tray, rate])

  const setLevel = useCallback((value) => {
    const video = videoRef.current
    if (!video) return
    video.volume = value
    video.muted = value === 0
    try {
      localStorage.setItem('vibestream.volume', String(value))
    } catch {
    }
  }, [])

  const toggleMute = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    video.muted = !video.muted
    if (!video.muted && video.volume === 0) video.volume = 0.5
  }, [])

  const canPip = browser && typeof document !== 'undefined' && Boolean(document.pictureInPictureEnabled)
  const togglePip = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (document.pictureInPictureElement) document.exitPictureInPicture().catch(() => {})
    else if (video.requestPictureInPicture) video.requestPictureInPicture().catch(() => {})
  }, [])

  const pipItem = canPip ? [{ id: 'pip', icon: 'pip', label: t('Picture in Picture'), onPress: togglePip }] : []
  const strip = inline && !full
  const topRight = strip ? [] : pipItem
  const fullItem = inline
    ? { id: 'full', icon: full ? 'fullscreen-exit' : 'fullscreen', label: full ? t('Exit Full Screen') : t('Full Screen'), onPress: full ? exitFull : enterFull }
    : { id: 'full', icon: fullscreen ? 'fullscreen-exit' : 'fullscreen', label: fullscreen ? t('Exit Full Screen') : t('Full Screen'), onPress: toggleFullscreen }
  const topItems = [{ id: 'close', onPress: onExit }].concat(topRight)

  const leftItems = browser
    ? (duration > 0 && !strip ? [{ id: 'clip', icon: 'clip', label: t('Clip'), onPress: () => { setTray(null); setClipping(true) } }] : [])
    : [{ id: 'restart', icon: 'replay', label: t('Start Over'), onPress: restart }]
  const rightItems = [
    ...(ep && info?.media_id && onNext && !strip
      ? [{ id: 'episodes', icon: 'episodes', label: t('Episodes'), onPress: () => openSide('episodes') }]
      : []),
    ...(next && onNext ? [{ id: 'next', icon: 'next-episode', label: t('Next Episode'), onPress: goNext }] : []),
    { id: 'speed', icon: 'speed', label: `${t('Speed')} (${speedLabel(rate)})`, onPress: openSpeed, on: tray === 'speed' },
    { id: 'settings', icon: 'gear', label: t('Settings'), onPress: () => openSide('settings') },
    ...(strip ? pipItem : []),
    ...(browser && (canFullscreen || inline) && !sideways ? [fullItem] : []),
  ]
  const rowItems = leftItems.concat(rightItems)
  rowIdsRef.current = rowItems.map((item) => item.id)

  const subtitleChoices = useMemo(() => {
    const order = [getLanguage(), 'en', 'de', 'ro'].filter((c, i, all) => all.indexOf(c) === i)
    const rank = (track) => {
      const at = order.indexOf(languageCode(track.language))
      return at >= 0 ? at : 99
    }
    const list = (info?.subtitles || []).slice().sort((a, b) => rank(a) - rank(b))
    return [{ id: null, label: t('Off') }].concat(list.map((x) => ({ id: x.id, label: x.label })))
  }, [info])
  const audioChoices = useMemo(() => (info?.audio || []).map((a) => ({
    id: a.index,
    default: a.default,
    label: a.default ? t('{lang} [Original]', { lang: languageName(a) }) : a.label || languageName(a),
  })), [info])

  const chooseSubtitle = useCallback((id) => {
    setSubtitleId(id)
    rememberTracks(id, undefined)
  }, [rememberTracks])
  const chooseAudio = useCallback((id) => {
    const track = (info?.audio || []).find((a) => a.index === id)
    const value = !track || track.default ? null : id
    setAudioIndex(value)
    rememberTracks(undefined, value)
  }, [info, rememberTracks])

  useEffect(() => {
    registerHandler({
      onDirection: (dir) => {
        if (side) {
          if (sideRef.current) sideRef.current.onDirection(dir)
          return
        }
        if (upNext && upNextFocus) {
          if (dir === 'left' && !ended) setUpNextFocus('credits')
          else if (dir === 'right') setUpNextFocus('next')
          else if (dir === 'up' || dir === 'down') {
            setUpNextFocus(null)
            showOverlay()
          }
          return
        }
        /* A press against hidden chrome only wakes it: that press is made blind. */
        if (!overlay) {
          showOverlay()
          return
        }
        showOverlay()

        if (tray === 'speed') {
          if (dir === 'left') setTrayIndex((i) => Math.max(0, i - 1))
          else if (dir === 'right') setTrayIndex((i) => Math.min(SPEEDS.length - 1, i + 1))
          else if (dir === 'down') setTray(null)
          return
        }

        // Leaving the scrubber abandons a half-finished seek.
        const rowIndex = ROWS.indexOf(zone)
        if (dir === 'up' || dir === 'down') {
          const to = ROWS[rowIndex + (dir === 'down' ? 1 : -1)]
          if (!to) return
          cancelSeek()
          setZone(to)
          setControl(to === 'centre' ? 1 : 0)
          return
        }

        if (zone === 'scrub') {
          nudgeSeek(dir === 'left' ? -1 : 1)
          return
        }

        const count = zone === 'top' ? topItems.length : zone === 'centre' ? 3 : rowItems.length
        setControl((c) => Math.max(0, Math.min(count - 1, c + (dir === 'right' ? 1 : -1))))
      },

      onEnter: () => {
        if (side) {
          if (sideRef.current) sideRef.current.onEnter()
          return
        }
        if (upNext && upNextFocus) {
          if (upNextFocus === 'credits') chooseCredits()
          else goNext()
          return
        }
        if (!overlay) {
          showOverlay()
          return
        }
        showOverlay()
        if (tray === 'speed') {
          applyRate(SPEEDS[trayIndex])
          setTray(null)
          return
        }
        if (zone === 'top') {
          const item = topItems[control]
          if (item) item.onPress()
          return
        }
        if (zone === 'centre') {
          if (control === 0) seekBy(-10)
          else if (control === 2) seekBy(10)
          else togglePlay()
          return
        }
        if (zone === 'scrub') {
          if (seekTargetRef.current !== null) commitSeek()
          else togglePlay()
          return
        }
        const item = rowItems[control]
        if (item) item.onPress()
      },

      onBack: () => {
        if (side) {
          if (!sideRef.current || !sideRef.current.onBack()) closeSide()
          return true
        }
        if (tray) {
          setTray(null)
          showOverlay()
          return true
        }
        // Back abandons a seek in progress and stays in the film.
        if (seekTargetRef.current !== null) {
          cancelSeek()
          return true
        }
        onExit()
        return true
      },

      onMedia: (which) => {
        if (which === 'play' || which === 'pause') {
          if (seekTargetRef.current !== null) commitSeek()
          else togglePlay()
        }
        if (which === 'stop') onExit()
        if (which === 'rewind') seekBy(-30)
        if (which === 'forward') seekBy(30)
      },
    })
  })

  useEffect(() => {
    if (!overlay && upNext) setUpNextFocus('next')
  }, [overlay, upNext])

  useEffect(() => {
    showOverlay()
    return () => clearTimeout(overlayTimer.current)
  }, [showOverlay])

  // Browser keys: space/K play, arrows skip and volume, F full screen, M mute,
  // N next episode, Escape closes a menu.
  useEffect(() => {
    if (!browser) return undefined
    const onKey = (event) => {
      if (clipping) return
      if (event.metaKey || event.ctrlKey || event.altKey) return
      if (event.target instanceof HTMLInputElement && event.target.type !== 'range') return
      const video = videoRef.current
      if (!video) return
      const key = event.key
      const volumeBy = (delta) => {
        video.muted = false
        video.volume = Math.max(0, Math.min(1, Math.round((video.volume + delta) * 20) / 20))
      }
      let handled = true
      if (key === ' ' || key === 'k' || key === 'K') togglePlay()
      else if (key === 'ArrowLeft') seekBy(-10)
      else if (key === 'ArrowRight') seekBy(10)
      // Inline, up and down scroll the page.
      else if (key === 'ArrowUp' && full) volumeBy(0.05)
      else if (key === 'ArrowDown' && full) volumeBy(-0.05)
      else if (key === 'f' || key === 'F') {
        if (!inline) toggleFullscreen()
        else if (full) exitFull()
        else enterFull()
      }
      else if (key === 'm' || key === 'M') video.muted = !video.muted
      else if ((key === 'n' || key === 'N') && next && onNext) goNext()
      else if (key === 'Escape' && side) closeSide()
      else if (key === 'Escape' && tray) setTray(null)
      else if (key === 'Escape' && inline && immersive) exitFull()
      else handled = false
      if (handled) {
        event.preventDefault()
        showOverlay()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [browser, clipping, togglePlay, seekBy, toggleFullscreen, next, onNext, goNext, side, tray, closeSide, showOverlay, full, inline, immersive, enterFull, exitFull])

  // Closing a menu restarts the hide countdown, or the chrome stays up for good.
  useEffect(() => {
    if (!browser) return
    if (tray) clearTimeout(overlayTimer.current)
    else showOverlay()
  }, [browser, tray, showOverlay])

  const previewing = side === 'settings' && settingsPage === 'appearance'

  /* Hide live cues under the Subtitle Appearance sample and the seek filmstrip. */
  useEffect(() => {
    const layer = cueLayerRef.current
    const inTheWay = previewing || seekTarget !== null
    if (layer) layer.style.display = inTheWay ? 'none' : ''
  }, [previewing, seekTarget])

  /* Lift cues while the chrome is up, or they overlap the scrubber on 16:9 films. */
  useEffect(() => {
    const layer = cueLayerRef.current
    if (layer) layer.classList.toggle('lifted', Boolean(overlay && !side))
  }, [overlay, side])

  const shown = dragTime ?? seekTarget ?? current
  const pct = duration ? (shown / duration) * 100 : 0
  const bufPct = duration ? (buffered / duration) * 100 : 0
  const seeking = seekTarget !== null

  /* Pointer events so touch can drag; capture keeps the drag going off the bar. */
  const scrubDragging = useRef(false)
  const browserScrub = {
    onPointerDown: (event) => {
      if (!duration) return
      event.preventDefault()
      if (event.currentTarget.setPointerCapture) event.currentTarget.setPointerCapture(event.pointerId)
      scrubDragging.current = true
      setDragTime(ratioAt(event.clientX) * duration)
      showOverlay()
    },
    onPointerMove: (event) => {
      const el = scrubRef.current
      if (!el || !duration) return
      const ratio = ratioAt(event.clientX)
      if (scrubDragging.current) {
        setDragTime(ratio * duration)
        showOverlay()
      }
      if (event.pointerType === 'mouse' || scrubDragging.current) {
        setHover({ time: ratio * duration, left: ratio * el.clientWidth })
      }
    },
    onPointerUp: (event) => {
      if (!scrubDragging.current) return
      scrubDragging.current = false
      if (duration) jumpTo(ratioAt(event.clientX) * duration)
      setDragTime(null)
      if (event.pointerType !== 'mouse') setHover(null)
      showOverlay()
    },
    onPointerLeave: (event) => {
      if (event.pointerType === 'mouse' && !scrubDragging.current) setHover(null)
    },
  }
  browserScrub.onPointerCancel = browserScrub.onPointerUp

  // The paused card only once playback is under way, and not during a D-pad seek
  // (which pauses on purpose) or while a menu is open.
  const presentation = info?.presentation || null
  const paused = Boolean(
    !playing && ready && prepared && !error && !seeking && !side && presentation,
  )

  const episodeLine = ep
    ? (ep.name ? `S${ep.season}:E${ep.number}  ${ep.name}` : `S${ep.season}:E${ep.number}`)
    : null

  // The stage is what moves into the box beside Settings and Episodes.
  const stageStyle = box
    ? {
      right: 'auto',
      bottom: 'auto',
      width: box.w,
      height: box.h,
      transform: `translate(${box.x}px, ${box.y}px) scale(${box.s})`,
      borderRadius: box.portrait ? 0 : Math.round((22 * scale) / box.s),
    }
    : undefined

  const scrub = {
    scrubRef, shown, current, duration, pct, bufPct, seeking, trick, fmtTime, hover,
    dragging: dragTime !== null,
    previewWidth: Math.round(Math.max(140, 260 * scale)),
    handlers: browser ? browserScrub : {
      onMouseDown: startDrag,
      onMouseMove: (e) => trackHover(e.clientX),
      onMouseLeave: () => dragTime === null && setHover(null),
    },
  }
  if (!browser && !pointer) scrub.hover = null

  return (
    <div
      ref={rootRef}
      className={[
        'player', browser ? 'browser' : '', clipping ? 'clipping' : '',
        inline ? (full ? 'inline full' : 'inline strip') : '',
        side ? (inline && !full ? 'side-over' : 'boxed') : '', box && box.portrait ? 'portrait' : '',
        overlay && !side && !clipping ? 'chrome-up' : '',
      ].join(' ')}
      style={browser ? { '--u': `${scale}px` } : undefined}
      onMouseMove={browser ? undefined : showOverlay}
      // Not on the TV: Chromium 53 has no pointer events.
      onPointerDown={browser ? (e) => { lastPointer.current = e.pointerType } : undefined}
      onPointerMove={browser ? (e) => {
        if (e.pointerType === 'mouse') {
          lastPointer.current = 'mouse'
          showOverlay()
        }
      } : undefined}
    >
      <div ref={stageRef} className="stage" style={stageStyle}>
        <video
          ref={videoRef}
          playsInline
          crossOrigin="anonymous"
          onClick={browser ? onPictureClick : side ? togglePlay : togglePlay}
          onDoubleClick={browser && !side
            ? (inline ? (full ? exitFull : enterFull) : canFullscreen ? toggleFullscreen : undefined)
            : undefined}
        />

        <div
          ref={cueLayerRef}
          className="cue-layer"
          data-style={appearance.style}
          style={{ fontSize: Math.round(cueFontSize(appearance.size) * scale) }}
        />

        {previewing && (
          <div
            className="cue-layer cue-sample"
            data-style={appearance.style}
            style={{ fontSize: Math.round(cueFontSize(appearance.size) * scale) }}
          >
            <div className="cue-line">{t('This is how subtitles will look.')}</div>
          </div>
        )}

        {statsShown && prepared && (
          <PlayerStats videoRef={videoRef} hlsRef={hlsRef} info={info} playId={playId} stageRef={stageRef} />
        )}

        {side && ready && !playing && (
          <div className="stage-paused"><PlayIcon size={Math.round(110 * scale)} /></div>
        )}
      </div>

      {!prepared && !error && (
        <div className="center-note">
          <ProgressRing
            percent={0}
            size={Math.round(104 * scale)}
            stroke={Math.max(3, Math.round(6 * scale))}
            indeterminate
          />
        </div>
      )}

      {upNext && (
        <div className={`postplay ${overlay ? 'raised' : ''}`}>
          <div className="postplay-caption">
            Next: S{next.season}:E{next.number} {next.name}
          </div>
          <div className="postplay-pills">
            {!ended && (
              <button
                type="button"
                className={`postplay-pill ghost ${upNextFocus === 'credits' ? 'focused' : ''}`}
                onMouseEnter={() => setUpNextFocus('credits')}
                onClick={chooseCredits}
              >
                {t('Watch Credits')}
              </button>
            )}
            <button
              type="button"
              className={`postplay-pill next ${upNextFocus === 'next' ? 'focused' : ''}`}
              onMouseEnter={() => setUpNextFocus('next')}
              onClick={goNext}
            >
              {fill && (
                <span
                  key={fill.key}
                  className="postplay-fill"
                  style={{
                    animationDuration: `${fill.duration}s`,
                    animationDelay: `${fill.delay}s`,
                    animationPlayState: playing || ended ? 'running' : 'paused',
                  }}
                  onAnimationEnd={goNext}
                >
                  <span className="postplay-label">
                    <PlayIcon size={Math.round(22 * scale)} />
                    <span>{t('Next Episode')}</span>
                  </span>
                </span>
              )}
              <span className="postplay-label">
                <PlayIcon size={Math.round(22 * scale)} />
                <span>{t('Next Episode')}</span>
              </span>
            </button>
          </div>
        </div>
      )}

      {prepared && !ready && !error && (
        <div className="center-note">
          <div className="spinner" />
          <div>{t('Starting playback...')}</div>
        </div>
      )}

      {error && (
        <div className="center-note">
          <div style={{ color: 'var(--accent)', fontWeight: 700 }}>
            {t('Cannot play this title')}
          </div>
          <div style={{ fontSize: Math.round(20 * scale) }}>{error}</div>
          {!browser && (
            <div style={{ fontSize: Math.round(18 * scale), color: 'var(--text-faint)' }}>
              {t('Press Back to return')}
            </div>
          )}
        </div>
      )}

      {paused && !clipping && !strip && (!browser || !overlay) && <div className="paused-wash" />}
      {paused && !clipping && !strip && (!browser || !overlay) && (
        <div className="paused-card">
          <div className="paused-eyebrow">{t("You're watching")}</div>
          {presentation.logo && !browser ? (
            <img className="paused-logo" src={presentation.logo} alt={presentation.title} />
          ) : (
            <div className="paused-title">{presentation.title}</div>
          )}
          {episodeLine && <div className="paused-episode">{episodeLine}</div>}
          {presentation.overview && (
            <p className="paused-overview">{presentation.overview}</p>
          )}
        </div>
      )}
      {paused && !overlay && !clipping && <div className="paused-flag">Paused</div>}

      {browser && clipping && (
        <ClipEditor
          videoRef={videoRef}
          duration={duration}
          playId={playId}
          trick={trick}
          fmtTime={fmtTime}
          onClose={() => {
            setClipping(false)
            showOverlay()
          }}
        />
      )}

      {!clipping && !side && (
        <PlayerChrome
          browser={browser}
          visible={overlay || dragTime !== null || Boolean(tray)}
          focus={browser || !overlay ? null : tray === 'speed' ? { zone: 'tray', index: trayIndex } : { zone, index: control }}
          onFocus={(z, index) => { setZone(z); setControl(index) }}
          title={presentation?.title || title}
          episodeLine={episodeLine}
          playing={playing}
          ready={ready && prepared && !error}
          onTogglePlay={togglePlay}
          onSkip={seekBy}
          onExit={onExit}
          topRight={topRight}
          leftItems={leftItems}
          rightItems={rightItems}
          volume={browser ? { ...volume, setLevel, toggleMute } : null}
          scrub={scrub}
          filmstrip={seeking && !pointer && trick ? <Filmstrip manifest={trick} time={seekTarget} /> : null}
          tray={tray}
          rate={rate}
          onRate={(value) => { applyRate(value); setTray(null) }}
          trayIndex={trayIndex}
          unit={scale}
          compact={strip}
        />
      )}

      {side && (
        <div
          className="side-panel"
          style={box && box.portrait ? { top: box.top } : undefined}
        >
          {side === 'settings' ? (
            <PlayerSettings
              ref={sideRef}
              browser={browser}
              subtitles={subtitleChoices}
              subtitleId={subtitleId}
              onSubtitle={chooseSubtitle}
              audio={audioChoices}
              audioId={effectiveAudio}
              onAudio={chooseAudio}
              appearance={appearance}
              onAppearance={setAppearance}
              statsShown={statsShown}
              onStats={setStatsShown}
              onPage={setSettingsPage}
              onClose={closeSide}
              unit={scale}
            />
          ) : (
            <PlayerEpisodes
              ref={sideRef}
              browser={browser}
              mediaId={info?.media_id}
              episode={ep}
              playId={playId}
              onPlay={(id) => onNext({ play_id: id })}
              onClose={closeSide}
              unit={scale}
            />
          )}
        </div>
      )}

      {!browser && ratingCard && !side && (
        <div className="rating-card">
          <div className="rating-card-title">{t('RATED {r}', { r: certification })}</div>
        </div>
      )}

    </div>
  )
}
