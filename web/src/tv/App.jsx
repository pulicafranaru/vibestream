import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, errorText, setActiveProfile } from '../api'
import Debug from './Debug'
import Detail from './Detail'
import Downloads from './Downloads'
import Home from './Home'
import Intro, { preloadIntro } from './Intro'
import Player from './Player'
import Profiles from './Profiles'
import Search from './Search'
import { MENU_ITEMS, NotificationsPanel, ProfileMenu } from './TopNav'
import { markNotesRead, useNotes, watchNotes } from './notes'
import { logInput, startInputLog } from './inputLog'
import { onCastControl, reportCastState, startCast, stopCast } from './cast'

const CAST_REMOTE = { subscribe: onCastControl, report: reportCastState }

startInputLog()
import { liveFor, titleState } from '../shared/titleState'
import { onLanguage, setLanguage, t } from '../shared/i18n'
import { createKeyGate, keyName, setInputMode } from './navigation'
import { buildPath, navigate, parseLocation } from './router'
import '../shared/fonts/figtree.css'
import './tv.css'

const SECTION_TYPES = { home: null, shows: 'tv', movies: 'movie' }

// Boot spinner, then the intro, then the screen: once per launch, so module level.
let introPlayed = false
const HERO_WAIT_MS = 4000

// The remembered profile expires after this long unused, and a launch asks again.
const PROFILE_KEY = 'vibestream.profile'
const PROFILE_AT_KEY = 'vibestream.profileAt'
const REMEMBER_MS = 4 * 60 * 60 * 1000

function rememberedProfileId() {
  try {
    const id = Number(localStorage.getItem(PROFILE_KEY) || 0)
    const at = Number(localStorage.getItem(PROFILE_AT_KEY) || 0)
    return id && at && Date.now() - at < REMEMBER_MS ? id : 0
  } catch {
    return 0
  }
}

function forgetProfile() {
  try {
    localStorage.removeItem(PROFILE_KEY)
  } catch {
    /* nothing kept, nothing to forget */
  }
}

function touchProfile(id) {
  try {
    if (id) localStorage.setItem(PROFILE_KEY, String(id))
    localStorage.setItem(PROFILE_AT_KEY, String(Date.now()))
  } catch {
    /* a TV that will not store it asks every time */
  }
}

// One global key listener dispatches to the top screen's registered handler, so two screens never both react to Back.
export default function App() {
  const initial = parseLocation()
  const [screen, setScreen] = useState(initial.screen)
  const [section, setSection] = useState(initial.section)
  const [category, setCategory] = useState(initial.genre || null)
  const [home, setHome] = useState(null)
  const [categoryData, setCategoryData] = useState(null)
  const [genres, setGenres] = useState([])
  const [totals, setTotals] = useState(null)
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState(null)
  const [playing, setPlaying] = useState(null)
  const [toast, setToast] = useState(null)
  const [downloads, setDownloads] = useState({})
  const [profiles, setProfiles] = useState([])
  // Parental controls: the admin makes profiles, and adults keep a PIN.
  const [guarded, setGuarded] = useState(false)
  const [profile, setProfile] = useState(null)
  // null, 'start' (full screen picker) or 'switch' (side panel).
  const [picking, setPicking] = useState(null)
  const [menu, setMenu] = useState(null) // null, or the focused index
  const [bell, setBell] = useState(null) // the bell's list: null, or the focused index
  const [ratings, setRatings] = useState({})
  const [myList, setMyList] = useState(() => new Set())
  const [continueIds, setContinueIds] = useState(() => new Set())
  const [language, setLanguageState] = useState('en')
  const [detailFrom, setDetailFrom] = useState('home')
  const [detailFocus, setDetailFocus] = useState(null)
  const screenRef = useRef(screen)
  screenRef.current = screen
  // loading | picker | failed | intro | done
  const [boot, setBoot] = useState(introPlayed ? 'done' : 'loading')
  const [bootError, setBootError] = useState(null)
  const bootTries = useRef(0)
  const [stageShown, setStageShown] = useState(introPlayed)
  const [heroReady, setHeroReady] = useState(false)
  // The intro video: the element, null if it would not load, undefined until known.
  const [introVideo, setIntroVideo] = useState(undefined)
  const bootRef = useRef(boot)
  bootRef.current = boot

  const handlerRef = useRef({})
  const menuRef = useRef(null)
  const gate = useRef(createKeyGate(45))

  const registerHandler = useCallback((handler) => {
    handlerRef.current = handler
  }, [])

  useEffect(() => onLanguage(setLanguageState), [])

  useEffect(() => {
    const setMode = (mode) => {
      const body = document.body
      const want = `input-${mode}`
      setInputMode(mode)
      if (body.classList.contains(want)) return
      body.classList.remove('input-pointer', 'input-dpad')
      body.classList.add(want)
    }
    setMode('pointer')
    let lastX = null
    let lastY = null
    const onMove = (e) => {
      if (lastX !== null && Math.abs(e.clientX - lastX) < 2 && Math.abs(e.clientY - lastY) < 2) return
      lastX = e.clientX
      lastY = e.clientY
      setMode('pointer')
    }
    const onKeyMode = (e) => {
      if ([37, 38, 39, 40, 13].indexOf(e.keyCode || e.which) >= 0) setMode('dpad')
    }
    window.addEventListener('mousemove', onMove, { passive: true })
    window.addEventListener('keydown', onKeyMode, true)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('keydown', onKeyMode, true)
    }
  }, [])

  // Each toast its full four seconds: an earlier one's timer must not close it.
  const toastTimer = useRef(null)
  const notify = useCallback((message, isError = false) => {
    setToast({ message, isError })
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 4000)
  }, [])

  // The address is only ever replaced, with one spare history entry as a trap: webOS 4.5 turns Back into history.back().
  const backRef = useRef(() => {})
  const lastBackKey = useRef(0)
  const routeRef = useRef(null)
  routeRef.current = { screen, section, genre: category, mediaId: selected && selected.media_id, playId: playing && playing.playId }

  useEffect(() => {
    navigate(routeRef.current, { replace: true })
  }, [screen, section, category, selected, playing])

  useEffect(() => {
    window.history.pushState(null, '', window.location.pathname)
    const onPop = () => {
      window.history.pushState(null, '', buildPath(routeRef.current))
      if (Date.now() - lastBackKey.current < 800) {
        logInput('  pop ignored: a Back key just came')
        return
      }
      backRef.current()
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // Only the title opened last may land; a late answer for an earlier one is dropped.
  const openedId = useRef(initial.screen === 'detail' ? initial.mediaId || null : null)
  const fetchSelected = useCallback((mediaId) => api.media(mediaId).then((card) => {
    if (openedId.current === mediaId) setSelected(card)
  }), [])

  useEffect(() => {
    if (!profile || !selected || !selected.media_id) return
    fetchSelected(selected.media_id).catch(() => {})
     
  }, [profile && profile.id])

  useEffect(() => {
    if (initial.screen === 'detail' && initial.mediaId) {
      fetchSelected(initial.mediaId).catch(() => {})
    }
    if (initial.screen === 'player' && initial.playId) {
      setPlaying({ playId: initial.playId, title: '' })
    }
     
  }, [])

  const loadProfiles = useCallback(async () => {
    const data = await api.profiles()
    const list = data.profiles || []
    setProfiles(list)
    setGuarded(!!data.parental_controls)
    // The profile in use may just have been renamed or given a new language.
    setProfile((current) => {
      if (!current) return current
      const fresh = list.find((p) => p.id === current.id)
      return fresh || current
    })
    return list
  }, [])

  useEffect(() => {
    setLanguage(profile ? profile.language : 'en')
  }, [profile])

  useEffect(() => {
    let alive = true
    loadProfiles()
      .then((list) => {
        if (!alive) return
        const stored = rememberedProfileId()
        // Remembered, it needs no PIN again; the only profile is taken
        // without asking, unless it has one.
        // One that has to choose a PIN first goes through the picker.
        const found = [list.find((p) => p.id === stored) ||
          (list.length === 1 && !list[0].has_pin ? list[0] : null)].find((p) => p && !p.needs_pin)
        if (found) {
          setProfile(found)
          setActiveProfile(found.id)
          touchProfile(found.id)
          api.ratings(found.id).then(setRatings).catch(() => {})
          api.myList(found.id).then((ids) => setMyList(new Set(ids))).catch(() => {})
        } else {
          setPicking('start')
          if (bootRef.current === 'loading') {
            setBoot('picker')
            setStageShown(true)
          }
        }
      })
      .catch(() => {
        setPicking('start')
        if (bootRef.current === 'loading') {
          setBoot('picker')
          setStageShown(true)
        }
      })
    return () => { alive = false }
  }, [loadProfiles])

  const pickProfile = useCallback(async (chosen) => {
    setProfile(chosen)
    setActiveProfile(chosen.id)
    touchProfile(chosen.id)
    setPicking(null)
    if (bootRef.current === 'picker') {
      setStageShown(false)
      setBoot('loading')
    }
    api.useProfile(chosen.id).catch(() => {})
    api.ratings(chosen.id).then(setRatings).catch(() => setRatings({}))
    api.myList(chosen.id).then((ids) => setMyList(new Set(ids))).catch(() => setMyList(new Set()))
    if (screenRef.current !== 'player') setScreen('home')
  }, [])

  const dropProfile = useCallback(() => {
    setProfile(null)
    setActiveProfile(null)
    forgetProfile()
    setRatings({})
    setMyList(new Set())
    setMenu(null)
    setBell(null)
    setPicking('start')
  }, [])

  const rate = useCallback(async (mediaId, value) => {
    if (!profile) return
    const next = ratings[mediaId] === value ? 0 : value
    setRatings((r) => ({ ...r, [mediaId]: next }))
    try {
      await api.rate(profile.id, mediaId, next)
    } catch (e) {
      notify(t('Could not save rating: {error}', { error: e.message }), true)
    }
  }, [profile, ratings, notify])

  const toggleMyList = useCallback(async (mediaId) => {
    if (!profile || !mediaId) return
    const adding = !myList.has(mediaId)
    const flip = (on) => setMyList((all) => {
      const copy = new Set(all)
      if (on) copy.add(mediaId)
      else copy.delete(mediaId)
      return copy
    })
    flip(adding)
    try {
      await api.setInMyList(profile.id, mediaId, adding)
      notify(adding ? t('Added to Watchlist') : t('Removed from Watchlist'))
    } catch (e) {
      flip(!adding)
      notify(t('Could not update the Watchlist: {error}', { error: e.message }), true)
    }
  }, [profile, myList, notify])

  const hideContinue = useCallback(async (mediaId) => {
    if (!profile || !mediaId) return
    try {
      await api.hideContinue(profile.id, mediaId)
      setContinueIds((all) => {
        const copy = new Set(all)
        copy.delete(mediaId)
        return copy
      })
      setHome((current) => current && current.rows
        ? { ...current, rows: current.rows.map((row) => row.id === 'continue'
          ? { ...row, items: row.items.filter((item) => item.media_id !== mediaId) }
          : row).filter((row) => row.items.length) }
        : current)
      notify(t('Hidden from Resume Watching'))
    } catch (e) {
      notify(e.message, true)
    }
  }, [profile, notify])

  // Sections are requested faster than they answer: only the newest request may land.
  const homeSeq = useRef(0)
  const loadHome = useCallback((sectionId, quiet = false) => {
    const seq = ++homeSeq.current
    const latest = () => seq === homeSeq.current
    if (!quiet) setLoading(true)
    const request = sectionId === 'library' ? api.mine() : api.home(SECTION_TYPES[sectionId] || null)
    request
      .then((data) => {
        if (!latest()) return
        bootTries.current = 0
        setHome({ ...data, section: sectionId })
        const row = (data.rows || []).find((r) => r.id === 'continue')
        setContinueIds(new Set(row ? row.items.map((item) => item.media_id) : []))
      })
      .catch((e) => {
        if (!latest()) return
        if (bootRef.current === 'loading' && screenRef.current === 'home') {
          bootTries.current += 1
          setBootError(e.message)
          setBoot('failed')
          return
        }
        notify(t('Could not load the catalog: {error}', { error: e.message }), true)
      })
      .finally(() => {
        if (latest()) setLoading(false)
      })
    if (sectionId === 'library') {
      api.downloadManager().then((d) => latest() && setTotals(d.totals)).catch(() => {})
    } else {
      api.genres(SECTION_TYPES[sectionId] || undefined)
        .then((list) => latest() && setGenres(list || []))
        .catch(() => latest() && setGenres([]))
    }
  }, [notify])

  useEffect(() => {
    if (!profile) return
    loadHome(section)
  }, [section, loadHome, profile])

  const retryBoot = useCallback(() => {
    if (bootRef.current !== 'failed') return
    setBoot('loading')
    loadHome(routeRef.current.section)
  }, [loadHome])
  const retryBootRef = useRef(retryBoot)
  retryBootRef.current = retryBoot
  useEffect(() => {
    if (boot !== 'failed') return undefined
    const wait = Math.min(30000, 2000 * Math.pow(2, Math.max(0, bootTries.current - 1)))
    const timer = setTimeout(() => retryBootRef.current(), wait)
    return () => clearTimeout(timer)
  }, [boot])

  // webOS never closes the app, so the rows are refreshed on resume and every few minutes, quietly and never under the player.
  const refreshRef = useRef(null)
  refreshRef.current = () => {
    if (!profile || screenRef.current === 'player' || document.hidden) return
    loadHome(section, true)
  }
  useEffect(() => {
    const refresh = () => refreshRef.current && refreshRef.current()
    const onShow = () => { if (!document.hidden) refresh() }
    document.addEventListener('webOSRelaunch', refresh)
    document.addEventListener('visibilitychange', onShow)
    const timer = setInterval(refresh, 5 * 60 * 1000)
    return () => {
      document.removeEventListener('webOSRelaunch', refresh)
      document.removeEventListener('visibilitychange', onShow)
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    if (!category) return undefined
    let alive = true
    setCategoryData(null)
    const ask = (params) => api.browse({ genre: category, limit: 24, ...params }).then((d) => d.items || []).catch(() => [])
    Promise.all([
      ask({ sort: 'popular' }),
      ask({ sort: 'newest' }),
      ask({ media_type: 'movie', sort: 'popular' }),
      ask({ media_type: 'tv', sort: 'popular' }),
    ]).then(([popular, newest, films, shows]) => {
      if (!alive) return
      const rows = [
        { id: 'popular', title: 'Popular', items: popular },
        { id: 'newest', title: 'Newest', items: newest },
        { id: 'films', title: 'Movies', items: films },
        { id: 'shows', title: 'Shows', items: shows },
      ].filter((row) => row.items.length)
      const hero = popular.find((card) => card.backdrop) || null
      setCategoryData({ hero, rows })
    })
    return () => { alive = false }
  }, [category])

  const failuresSeen = useRef(null)
  useEffect(() => {
    let timer = null
    let alive = true
    const tick = async () => {
      try {
        const rows = await api.downloads()
        if (!alive) return
        const failed = rows.filter((d) => d.state === 'error')
        if (failuresSeen.current) {
          const fresh = failed.find((d) => !failuresSeen.current[d.id])
          if (fresh) notify(fresh.error_message || 'The download could not start. Try again.', true)
        } else {
          failuresSeen.current = {}
        }
        failed.forEach((d) => { failuresSeen.current[d.id] = true })
        let active = false
        rows.forEach((d) => {
          if (['downloading', 'adding', 'requested'].indexOf(d.state) >= 0) active = true
        })
        // Keep the same objects when nothing changed; a fresh map every poll redraws every screen mid-navigation.
        setDownloads((prev) => {
          const next = {}
          let changed = Object.keys(prev).length !== rows.length
          rows.forEach((d) => {
            const old = prev[d.torrent_id]
            if (old && JSON.stringify(old) === JSON.stringify(d)) {
              next[d.torrent_id] = old
            } else {
              next[d.torrent_id] = d
              changed = true
            }
          })
          return changed ? next : prev
        })
        timer = setTimeout(tick, active ? 2000 : 10000)
      } catch {
        if (alive) timer = setTimeout(tick, 10000)
      }
    }
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [notify])

  useEffect(() => {
    const ready = () => {
      const sys = window.webOSSystem || window.PalmSystem
      if (sys && sys.stageReady) sys.stageReady()
    }
    ready()
    const timer = setTimeout(ready, 200)
    return () => clearTimeout(timer)
  }, [])

  // A launcher that handles relaunch gets this event instead of the window coming forward; unanswered, the app never reappears.
  useEffect(() => {
    const activate = () => {
      const sys = window.webOSSystem || window.PalmSystem
      if (sys && sys.activate) sys.activate()
    }
    document.addEventListener('webOSRelaunch', activate)
    return () => document.removeEventListener('webOSRelaunch', activate)
  }, [])

  // webOS never closes the app, so it checks the served build on resume and every 15 minutes and reloads. Never mid-film.
  useEffect(() => {
    // The entry script is the only asset whose content-hashed name changes with every build.
    const entry = (html) => {
      const found = html.match(/assets\/tv-[A-Za-z0-9_-]+\.js/)
      return found ? found[0] : null
    }
    const running = entry(document.documentElement.innerHTML)
    const check = () => {
      if (!running || screenRef.current === 'player') return
      fetch(window.location.pathname, { cache: 'no-store' })
        .then((res) => (res.ok ? res.text() : ''))
        .then((html) => {
          const served = entry(html)
          if (served && served !== running) window.location.reload()
        })
        .catch(() => {})
    }
    const onShow = () => { if (!document.hidden) check() }
    document.addEventListener('webOSRelaunch', check)
    document.addEventListener('visibilitychange', onShow)
    const timer = setInterval(check, 15 * 60 * 1000)
    return () => {
      document.removeEventListener('webOSRelaunch', check)
      document.removeEventListener('visibilitychange', onShow)
      clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    const onKey = (event) => {
      const name = keyName(event)
      if (!name) return
      event.preventDefault()
      if (bootRef.current === 'failed') {
        if (name === 'enter') retryBootRef.current()
        else if (name === 'back') exitRef.current()
        return
      }
      if (bootRef.current === 'loading' || bootRef.current === 'intro') {
        if (bootRef.current === 'intro' && (name === 'enter' || name === 'back')) {
          introPlayed = true
          setStageShown(true)
          setBoot('done')
        }
        return
      }
      const handler = menuRef.current || handlerRef.current || {}
      if (name === 'back') {
        lastBackKey.current = Date.now()
        backRef.current()
        return
      }
      if (name === 'enter') {
        if (handler.onEnter) handler.onEnter()
        return
      }
      if (['play', 'pause', 'stop', 'rewind', 'forward'].indexOf(name) >= 0) {
        if (handler.onMedia) handler.onMedia(name)
        return
      }
      if (name.indexOf('digit') === 0) {
        if (handler.onDigit) handler.onDigit(Number(name.slice(5)))
        return
      }
      if (!gate.current()) return
      if (handler.onDirection) handler.onDirection(name)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const exitApp = useCallback(() => {
    if (window.webOSSystem && window.webOSSystem.platformBack) window.webOSSystem.platformBack()
    else window.close()
  }, [])
  const exitRef = useRef(exitApp)
  exitRef.current = exitApp

  backRef.current = () => {
    // webOS 4.5 delivers Back as a history pop, not a key; it lands here too.
    if (bootRef.current === 'failed') {
      exitApp()
      return
    }
    if (menuRef.current) {
      logInput('  back: closes the open menu')
      menuRef.current.onBack()
      return
    }
    logInput(`  back: to the screen (${screen}), menu ${menu !== null ? 'open' : 'shut'}, bell ${bell !== null ? 'open' : 'shut'}`)
    const handler = handlerRef.current || {}
    const consumed = handler.onBack ? handler.onBack() : false
    if (consumed) return
    if (!profile) {
      exitApp()
      return
    }
    if (screen !== 'home') {
      setScreen('home')
      return
    }
    exitApp()
  }

  const chooseMenu = useCallback((id) => {
    setMenu(null)
    if (id === 'profile') setPicking('switch')
    else if (id === 'debug') setScreen('debug')
    else if (id === 'exit') exitApp()
  }, [exitApp])

  useEffect(() => {
    watchNotes(profile ? profile.id : null)
  }, [profile && profile.id])

  const { items: noteItems } = useNotes()

  const chooseNote = useCallback((item) => {
    setBell(null)
    if (item.kind === 'failed') {
      setScreen('downloads')
      return
    }
    if (!item.media_id) return
    api.media(item.media_id).then((card) => openDetailRef.current(card)).catch(() => {})
  }, [])

  useEffect(() => {
    if (bell !== null) {
      menuRef.current = {
        onDirection: (dir) => {
          if (dir === 'up') setBell((i) => Math.max(0, i - 1))
          if (dir === 'down') setBell((i) => Math.min(Math.max(0, noteItems.length - 1), i + 1))
        },
        onEnter: () => { if (noteItems[bell]) chooseNote(noteItems[bell]) },
        onBack: () => setBell(null),
      }
      return
    }
    if (menu === null) {
      menuRef.current = null
      return
    }
    menuRef.current = {
      onDirection: (dir) => {
        if (dir === 'up') setMenu((i) => Math.max(0, i - 1))
        if (dir === 'down') setMenu((i) => Math.min(MENU_ITEMS.length - 1, i + 1))
      },
      onEnter: () => chooseMenu(MENU_ITEMS[menu]),
      onBack: () => setMenu(null),
    }
  }, [menu, chooseMenu, bell, noteItems, chooseNote])

  const onNav = useCallback((id) => {
    if (id === 'profile') {
      setMenu(0)
      return
    }
    if (id === 'bell') {
      setBell(0)
      markNotesRead()
      return
    }
    setCategory(null)
    if (id === 'search') {
      setScreen('search')
      return
    }
    if (id === 'downloads') {
      setScreen('downloads')
      return
    }
    setSection(id)
    setScreen('home')
  }, [])

  const openDetailRef = useRef(null)
  const openDetail = useCallback(async (card, from) => {
    openedId.current = card.media_id || null
    setSelected(card)
    setDetailFocus(null)
    setDetailFrom(from || screenRef.current || 'home')
    setScreen('detail')
    if (card.media_id) {
      try {
        await fetchSelected(card.media_id)
      } catch {
        /* the card already shown will do */
      }
    }
  }, [fetchSelected])
  openDetailRef.current = openDetail

  const startPlay = useCallback((card, what, episode, options) => {
    const playId = typeof what === 'string' ? what : String((what || card.download || {}).id || '')
    if (!playId) {
      notify(t('This title is not downloaded yet'), true)
      return
    }
    setPlaying({
      playId,
      title: card.title,
      from: screenRef.current,
      mediaId: card.media_id,
      season: episode ? episode.season : null,
      episode: episode ? episode.episode : null,
      fromStart: Boolean(options && options.fromStart),
    })
    setScreen('player')
  }, [notify])

  // Played as the sender's profile, so the progress lands where the phone will look for it.
  const castPlayRef = useRef(null)
  // A film sent before a profile is in or the intro is done is held until then.
  const pendingCast = useRef(null)
  castPlayRef.current = (command) => {
    const sys = window.webOSSystem || window.PalmSystem
    if (sys && sys.activate) sys.activate()
    const as = command.profile_id && profiles.find((p) => p.id === command.profile_id)
    if (bootRef.current !== 'done' || !profile) {
      pendingCast.current = command
      if (as && !profile) pickProfile(as)
      return
    }
    if (as && profile.id !== as.id) pickProfile(as)
    setPlaying({
      playId: String(command.play_id),
      title: command.title || '',
      from: screenRef.current === 'player' ? 'home' : screenRef.current,
      mediaId: null,
      season: null,
      episode: null,
      fromStart: false,
      startAt: typeof command.position === 'number' ? command.position : null,
    })
    setScreen('player')
    if (command.sender) notify(t('Playing from {name}', { name: command.sender }))
  }

  useEffect(() => {
    startCast(profile ? profile.id : null, (command) => castPlayRef.current && castPlayRef.current(command))
    return () => stopCast()
  }, [profile && profile.id])

  useEffect(() => {
    if (boot !== 'done' || !profile || !pendingCast.current) return
    const command = pendingCast.current
    pendingCast.current = null
    castPlayRef.current(command)
  }, [boot, profile])

  const exitPlayer = useCallback(() => {
    const was = playing || {}
    if (was.from === 'detail' && selected && selected.media_id === was.mediaId) {
      setDetailFocus(was.season ? { season: was.season, episode: was.episode } : null)
      fetchSelected(selected.media_id).catch(() => {})
      setScreen('detail')
    } else {
      setScreen(was.from && was.from !== 'player' ? was.from : 'home')
    }
    loadHome(section)
  }, [playing, selected, section, loadHome, fetchSelected])

  const closeDetail = useCallback(() => {
    setDetailFocus(null)
    setScreen(detailFrom === 'search' || detailFrom === 'category' ? detailFrom : 'home')
  }, [detailFrom])

  const download = useCallback(async (torrentId, options) => {
    const result = await api.startDownload(torrentId, options)
    setDownloads((all) => ({ ...all, [result.torrent_id]: result }))
    return result
  }, [])

  const heroPlay = useCallback(async (card) => {
    const state = titleState(liveFor(card, downloads), card)
    if (state.id === 'play') {
      // A show's download is a season pack, which names no single file, so play an episode instead.
      if (card.media_type === 'tv' && !card.resume_play_id) {
        openDetail(card)
        return
      }
      startPlay(card, state.playId)
      return
    }
    if (state.id === 'download' || state.id === 'failed') {
      if (!card.primary_release_id) {
        openDetail(card)
        return
      }
      try {
        await download(card.primary_release_id)
        notify(t('Downloading {title}', { title: card.title }))
      } catch (e) {
        notify(errorText(e), true)
      }
      return
    }
    openDetail(card)
  }, [startPlay, openDetail, downloads, download, notify])

  const openCard = useCallback((card) => {
    // Kept on a kids profile's watchlist above its ceiling: not opened, not played.
    if (card.locked) return
    const resume = card.resume_play_id || card.resume_download_id
    if (resume) {
      startPlay(card, String(resume))
      return
    }
    openDetail(card, screenRef.current)
  }, [startPlay, openDetail])

  const openGenre = useCallback((name) => {
    setCategory(name)
    setScreen('category')
  }, [])

  const searchSuggestions = useMemo(() => {
    const row = ((home && home.rows) || []).find(
      (r) => r.id !== 'continue' && r.id !== 'library' && r.id !== 'mylist' && (r.items || []).length,
    )
    return row ? row.items.slice(0, 24) : []
  }, [home])

  const backdrop = (home && home.hero && home.hero.backdrop) || (selected && selected.backdrop) || null
  const ready = profile && !picking

  // The hero's picture is decoded before the intro reveals the page, but only waited for so long.
  useEffect(() => {
    if (boot !== 'loading' || !home || !home.hero || !home.hero.backdrop) return undefined
    let alive = true
    const img = new Image()
    const settle = () => alive && setHeroReady(true)
    img.onload = settle
    img.onerror = settle
    img.src = home.hero.backdrop
    const timer = setTimeout(settle, HERO_WAIT_MS)
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [boot, home])

  useEffect(() => {
    if (introPlayed) return
    preloadIntro().then(setIntroVideo)
  }, [])

  const firstScreenReady = introVideo !== undefined &&
    !picking && (profile && (screen !== 'home' ||
      (home && home.section === section && !loading && (heroReady || !home.hero || !home.hero.backdrop))))

  useEffect(() => {
    if (boot === 'loading' && firstScreenReady) setBoot('intro')
  }, [boot, firstScreenReady])

  // The boot spinner is tv.html's own, outside React, so it never jumps.
  useEffect(() => {
    const el = document.getElementById('boot')
    if (!el) return
    const showing = boot === 'loading'
    if (showing && el.style.display === 'none') {
      const spinner = el.firstChild
      if (spinner) {
        const delay = `${-(Date.now() % 900)}ms`
        spinner.style.animationDelay = delay
        spinner.style.webkitAnimationDelay = delay
      }
    }
    el.style.display = showing ? '' : 'none'
  }, [boot])

  useEffect(() => {
    if (!profile) return undefined
    let lastKey = 0
    const onKey = () => {
      if (Date.now() - lastKey < 60000) return
      lastKey = Date.now()
      touchProfile(0)
    }
    const timer = setInterval(() => touchProfile(0), 5 * 60 * 1000)
    window.addEventListener('keydown', onKey, true)
    return () => {
      clearInterval(timer)
      window.removeEventListener('keydown', onKey, true)
    }
  }, [profile])

  return (
    <div className="tv" key={language}>
      {boot === 'intro' && (
        <Intro
          video={introVideo}
          onReveal={() => setStageShown(true)}
          onDone={() => {
            introPlayed = true
            setBoot('done')
          }}
        />
      )}
      {boot === 'failed' && (
        <div className="boot-failed">
          <p>{t('Could not load the catalog: {error}', { error: bootError || '' })}</p>
          <div className="pill-btn focused" onClick={retryBoot}>{t('Try again')}</div>
        </div>
      )}
      <div className={`tv-stage ${stageShown ? '' : 'waiting'}`}>
      {picking && (
        <Profiles
          profiles={profiles}
          active={profile}
          variant={picking === 'switch' ? 'switch' : 'start'}
          backdrop={backdrop}
          onPick={pickProfile}
          onChanged={loadProfiles}
          onActiveDeleted={dropProfile}
          guarded={guarded}
          onClose={profile ? () => setPicking(null) : null}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'home' && (
        <Home
          key={`home-${section}`}
          data={home && home.section === section ? home : null}
          profile={profile}
          downloads={downloads}
          totals={totals}
          genres={genres}
          loading={loading}
          section={section}
          onNav={onNav}
          onOpen={openCard}
          onPlay={heroPlay}
          onMoreInfo={(card) => openDetail(card, 'home')}
          onGenre={openGenre}
          onDownloads={() => setScreen('downloads')}
          onClose={() => {}}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'category' && category && (
        <Home
          key={`category-${category}`}
          data={categoryData}
          profile={profile}
          downloads={downloads}
          loading={!categoryData}
          section="category"
          category={category}
          onNav={onNav}
          onOpen={(card) => openDetail(card, 'category')}
          onPlay={heroPlay}
          onMoreInfo={(card) => openDetail(card, 'category')}
          onGenre={openGenre}
          onDownloads={() => setScreen('downloads')}
          onClose={() => {
            setCategory(null)
            setScreen('home')
          }}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'downloads' && (
        <Downloads
          onPlay={(job) => {
            setPlaying({ playId: String(job.play_id), title: job.title, from: 'downloads' })
            setScreen('player')
          }}
          onClose={() => {
            setSection('library')
            setScreen('home')
            loadHome('library')
          }}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'debug' && (
        <Debug
          profile={profile}
          onClose={() => setScreen('home')}
          onSwitchProfile={() => setPicking('switch')}
          onExit={exitApp}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'detail' && selected && (
        <Detail
          key={selected.media_id || selected.primary_release_id}
          card={selected}
          downloads={downloads}
          rating={ratings[selected.media_id] || 0}
          onRate={rate}
          inMyList={myList.has(selected.media_id)}
          inContinue={continueIds.has(selected.media_id)}
          onToggleMyList={toggleMyList}
          onHideContinue={hideContinue}
          focus={detailFocus}
          onPlay={startPlay}
          onDownload={download}
          onError={(message) => notify(message, true)}
          onOpenTitle={(card) => openDetail(card, detailFrom)}
          onClose={closeDetail}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'search' && (
        <Search
          profile={profile}
          onNav={onNav}
          onOpen={(card) => openDetail(card, 'search')}
          onGenre={openGenre}
          suggestions={searchSuggestions}
          genres={genres}
          onClose={() => setScreen('home')}
          registerHandler={registerHandler}
        />
      )}

      {ready && screen === 'player' && playing && (
        <Player
          key={playing.playId}
          playId={playing.playId}
          title={playing.title}
          fromStart={playing.fromStart}
          startAt={playing.startAt}
          remote={CAST_REMOTE}
          onNext={(next) =>
            setPlaying((p) => ({ ...p, playId: next.play_id, season: next.season, episode: next.number, fromStart: false, startAt: null }))
          }
          onExit={exitPlayer}
          registerHandler={registerHandler}
        />
      )}

      {bell !== null && ready && (
        <>
          <div className="menu-scrim" onClick={() => setBell(null)} />
          <NotificationsPanel index={bell} onHover={setBell} onChoose={chooseNote} />
        </>
      )}

      {menu !== null && ready && (
        <>
          <div className="menu-scrim" onClick={() => setMenu(null)} />
          <ProfileMenu
            profile={profile}
            index={menu}
            onHover={setMenu}
            onChoose={chooseMenu}
          />
        </>
      )}

      {toast && (
        <div className={`toast ${toast.isError ? 'error' : ''}`}>
          {toast.isError && <span className="fail-badge">!</span>}
          {toast.isError ? t(toast.message) : toast.message}
        </div>
      )}
      </div>
    </div>
  )
}
