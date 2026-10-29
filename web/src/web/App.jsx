import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { api, errorText, setActiveProfile } from '../api'
import Player from '../shared/Player'
import Browse from './Browse'
import MyList from './MyList'
import Detail from './Detail'
import Downloads from './Downloads'
import Header from './Header'
import Inbox from './Inbox'
import TabBar from './TabBar'
import { useNotifications } from './notifications'
import { ProfileGate, useProfileEditor } from './Profiles'
import Search from './Search'
import { GenrePage, PersonPage } from './Collection'
import SpaceDialog from './SpaceDialog'
import { buildPath, navigate, onRouteChange, parseLocation, sectionFor } from './router'

const PROFILE_KEY = 'vibestream.profile'

export default function App() {
  const [route, setRoute] = useState(() => parseLocation())
  const [profile, setProfile] = useState(null)
  const [profiles, setProfiles] = useState([])
  // Parental controls: the admin makes profiles, and adults keep a PIN.
  const [guarded, setGuarded] = useState(false)
  const [ratings, setRatings] = useState({})
  const [myList, setMyList] = useState(() => new Set())
  const [downloads, setDownloads] = useState({})
  const pollRef = useRef(null)

  const go = useCallback((next, options) => {
    navigate(next, options)
    setRoute(parseLocation())
  }, [])

  useEffect(() => onRouteChange(setRoute), [])

  /* A title opens over the page it came from, which stays mounted so closing keeps its rows and scroll. */
  const behind = route.screen === 'detail'
    ? route.background || { screen: 'home', section: 'home' }
    : route
  // Where the title grew from and what is known about it, for the first frame. Not in history.
  const opening = useRef({ from: null, preview: null })

  /*
   * Scroll restored here on close: full screen in the dialog scrolls the window to the top,
   * and Safari does not reliably restore it on Back.
   */
  const pageScroll = useRef(null)
  useLayoutEffect(() => {
    if (route.screen === 'detail' || !pageScroll.current) return
    const saved = pageScroll.current
    pageScroll.current = null
    if (buildPath(route) !== saved.path) return
    window.scrollTo(0, saved.y)
    // Again once the browser has done its own restoring, which can land later and elsewhere.
    requestAnimationFrame(() => window.scrollTo(0, saved.y))
  }, [route])

  const chooseProfile = useCallback((chosen) => {
    setProfile(chosen)
    setActiveProfile(chosen ? chosen.id : null)
    if (chosen) {
      localStorage.setItem(PROFILE_KEY, String(chosen.id))
      api.useProfile(chosen.id).catch(() => {})
      api.ratings(chosen.id).then(setRatings).catch(() => setRatings({}))
      api.myList(chosen.id).then((ids) => setMyList(new Set(ids))).catch(() => setMyList(new Set()))
    } else {
      localStorage.removeItem(PROFILE_KEY)
      setRatings({})
      setMyList(new Set())
    }
  }, [])

  const loadProfiles = useCallback(
    async (select = true) => {
      const data = await api.profiles().catch(() => ({ profiles: [] }))
      const list = data.profiles || []
      setProfiles(list)
      setGuarded(!!data.parental_controls)
      if (!select) return list
      const stored = Number(localStorage.getItem(PROFILE_KEY))
      const match = list.find((p) => p.id === stored)
      // One that has to choose a PIN first goes through the picker.
      if (match && !match.needs_pin) chooseProfile(match)
      return list
    },
    [chooseProfile],
  )

  useEffect(() => {
    loadProfiles()
  }, [loadProfiles])

  const ownProfile = useProfileEditor({
    guarded,
    onSaved: async (saved, opened) => {
      const list = await loadProfiles(false)
      if (!saved) chooseProfile(null)
      else setProfile(list.find((p) => p.id === opened.id) || saved)
    },
    onPinChanged: async (opened) => {
      const list = await loadProfiles(false)
      const fresh = list.find((p) => p.id === opened.id)
      if (fresh) setProfile(fresh)
    },
  })

  const rate = useCallback(
    async (mediaId, value) => {
      if (!profile) return
      const next = ratings[mediaId] === value ? 0 : value
      setRatings((all) => {
        const copy = { ...all }
        if (next) copy[mediaId] = next
        else delete copy[mediaId]
        return copy
      })
      await api.rate(profile.id, mediaId, next).catch(() => {})
    },
    [profile, ratings],
  )

  // Optimistic; reverted if the server says no.
  const toggleMyList = useCallback(
    async (mediaId) => {
      if (!profile || !mediaId) return
      const adding = !myList.has(mediaId)
      const flip = (on) =>
        setMyList((all) => {
          const copy = new Set(all)
          if (on) copy.add(mediaId)
          else copy.delete(mediaId)
          return copy
        })
      flip(adding)
      await api.setInMyList(profile.id, mediaId, adding).catch(() => flip(!adding))
    },
    [profile, myList],
  )

  /* One poll for the whole app: quick while something is arriving, lazy otherwise. */
  /* Every Download goes through startDownload, so a failed start is toasted here once. */
  const [toast, setToast] = useState(null)
  const toastTimer = useRef(null)
  const showError = useCallback((message) => {
    setToast({ message: message || 'Something went wrong. Try again.', key: Date.now() })
    clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), 4500)
  }, [])

  // Failures already present at the first look were said before.
  const failuresSeen = useRef(null)
  useEffect(() => {
    let alive = true
    const tick = async () => {
      const rows = await api.downloads().catch(() => null)
      if (!alive) return
      let busy = false
      if (rows) {
        const failed = rows.filter((row) => row.state === 'error')
        if (failuresSeen.current) {
          const fresh = failed.find((row) => !failuresSeen.current[row.id])
          if (fresh) showError(fresh.error_message)
        } else {
          failuresSeen.current = {}
        }
        failed.forEach((row) => { failuresSeen.current[row.id] = true })
        const map = {}
        rows.forEach((row) => {
          map[row.torrent_id] = row
          if (
            ['downloading', 'adding', 'requested'].includes(row.state) ||
            row.preparing
          ) {
            busy = true
          }
        })
        setDownloads(map)
      }
      pollRef.current = setTimeout(tick, busy ? 2000 : 15000)
    }
    tick()
    return () => {
      alive = false
      clearTimeout(pollRef.current)
    }
  }, [showError])

  const refreshDownloads = useCallback(async () => {
    const rows = await api.downloads().catch(() => null)
    if (!rows) return
    const map = {}
    rows.forEach((row) => {
      map[row.torrent_id] = row
    })
    setDownloads(map)
  }, [])

  /*
   * Low on space the server answers 507 with what removing finished sources would free.
   * Asked here, then retried. Null means called off. "Download anyway" holds for a couple of minutes.
   */
  const [spaceAsk, setSpaceAsk] = useState(null)
  const spaceWaived = useRef(0)
  const startDownload = useCallback(
    async (torrentId, options = {}) => {
      let opts = { ...options, ignoreSpace: options.ignoreSpace || Date.now() < spaceWaived.current }
      for (let attempt = 0; ; attempt += 1) {
        try {
          const started = await api.startDownload(torrentId, opts)
          setDownloads((all) => ({ ...all, [started.torrent_id]: started }))
          return started
        } catch (e) {
          // Null is "nothing started", which every caller already handles.
          if (e.status !== 507 || attempt > 0 || !e.body?.space) {
            showError(errorText(e))
            return null
          }
          const answer = await new Promise((resolve) => setSpaceAsk({ space: e.body.space, resolve }))
          setSpaceAsk(null)
          if (answer === 'cancel') return null
          if (answer === 'free') {
            let result
            try {
              result = await api.removeFinishedSources()
            } catch (freeError) {
              showError(errorText(freeError))
              return null
            }
            const left = result.space?.free_bytes ?? 0
            if (left - e.body.space.needed_bytes > 0) opts = { ...opts, ignoreSpace: true }
          } else {
            spaceWaived.current = Date.now() + 120000
            opts = { ...opts, ignoreSpace: true }
          }
        }
      }
    },
    [showError],
  )

  const cancelDownload = useCallback(async (download) => {
    await api.cancelDownload(download.id)
    setDownloads((all) => {
      const copy = { ...all }
      delete copy[download.torrent_id]
      return copy
    })
  }, [])

  const openTitle = useCallback(
    (card, from, playId = null) => {
      opening.current = { from: from || null, preview: card }
      const { background: _ignored, ...page } = behind
      if (route.screen !== 'detail') pageScroll.current = { path: buildPath(page), y: window.scrollY }
      const inTitle = route.screen === 'detail'
      go({
        // A title opened cold from a link has no page in the history to go back to.
        screen: 'detail', mediaId: card.media_id ?? card.id, play: playId,
        background: inTitle ? route.background : page,
        depth: inTitle ? (route.depth || 1) + 1 : 1,
      })
    },
    [go, behind, route.screen, route.depth, route.background],
  )

  // Back past every stacked title; a title opened from a link has no page behind it, so Home.
  const closeTitle = useCallback(() => {
    if (route.background) window.history.go(-(route.depth || 1))
    else go({ screen: 'home', section: 'home' }, { replace: true })
  }, [route.background, route.depth, go])
  /* Play inside the title's dialog; only a play id with no known title takes the whole window. */
  const play = useCallback((playId, card) => {
    if (route.screen === 'detail') {
      go({ ...route, play: playId }, { replace: true })
      return
    }
    if (card && (card.media_id ?? card.id)) {
      openTitle(card, null, playId)
      return
    }
    go({ screen: 'player', playId })
  }, [route, go, openTitle])
  const stopPlaying = useCallback(() => {
    if (route.screen === 'detail') go({ ...route, play: null }, { replace: true })
  }, [route, go])

  // Download failures and space notices go to Downloads; the rest to their title.
  const chooseNotification = useCallback((item) => {
    if (item.kind === 'failed' || item.kind === 'space') go({ screen: 'downloads' })
    else if (item.media_id) openTitle({ media_id: item.media_id })
  }, [go, openTitle])
  const chooseDownload = useCallback((job) => {
    if (job.state === 'failed' || !job.media_id) go({ screen: 'downloads' })
    else openTitle({ media_id: job.media_id })
  }, [go, openTitle])
  const downloading = Object.values(downloads).some(
    (row) => ['downloading', 'adding', 'requested'].includes(row.state) || row.preparing,
  )
  // Before any early return: it keeps listening during playback too.
  const notes = useNotifications(profile?.id, chooseNotification)
  const search = useCallback((query) => go({ screen: 'search', query }, { replace: route.screen === 'search' }), [go, route.screen])

  const shell = useMemo(
    () => ({
      downloads, startDownload, cancelDownload, refreshDownloads, openTitle, play,
      ratings, rate, myList, toggleMyList, profile, go, showError,
    }),
    [downloads, startDownload, cancelDownload, refreshDownloads, openTitle, play,
      ratings, rate, myList, toggleMyList, profile, go, showError],
  )

  if (route.screen === 'player') {
    // In a frame that outlives each episode, so the next one stays full screen.
    return (
      <div className="player-frame" data-player-frame>
        <Player
          key={route.playId}
          playId={route.playId}
          title=""
          onExit={() => window.history.back()}
          // Replace, so Back from the next episode returns to the list, not the last one.
          onNext={(next) => go({ screen: 'player', playId: next.play_id }, { replace: true })}
          registerHandler={() => {}}
          variant="browser"
        />
      </div>
    )
  }

  if (!profile) {
    return (
      <ProfileGate
        profiles={profiles}
        guarded={guarded}
        onChoose={chooseProfile}
        onChanged={() => loadProfiles(false)}
      />
    )
  }

  return (
    <div className="app">
      <Header
        section={behind.screen === 'home' ? (sectionFor(behind.section).parent || behind.section) : null}
        query={behind.screen === 'search' ? behind.query : ''}
        profile={profile}
        onNavigate={(id) => go({ screen: 'home', section: id })}
        onSearch={search}
        onDownloads={() => go({ screen: 'downloads' })}
        onDownload={chooseDownload}
        downloading={downloading}
        onManageProfile={() => ownProfile.open(profile)}
        onSwitchProfile={() => chooseProfile(null)}
        notes={notes}
        onNotification={chooseNotification}
        onAllNotifications={() => go({ screen: 'notifications' })}
      />

      <main className="main">
        {behind.screen === 'home' && behind.section === 'mylist' && <MyList shell={shell} />}
        {behind.screen === 'home' && behind.section !== 'mylist' && (
          <Browse key={behind.section} section={sectionFor(behind.section)} shell={shell} />
        )}
        {behind.screen === 'search' && (
          <Search query={behind.query} onQuery={search} shell={shell} />
        )}
        {behind.screen === 'downloads' && <Downloads shell={shell} onPlay={play} />}
        {behind.screen === 'notifications' && <Inbox notes={notes} onChoose={chooseNotification} />}
        {behind.screen === 'genre' && <GenrePage key={behind.slug} slug={behind.slug} shell={shell} />}
        {behind.screen === 'person' && (
          <PersonPage key={behind.personId} personId={behind.personId} shell={shell} />
        )}
        {route.screen === 'detail' && (
          <Detail
            key={route.mediaId}
            mediaId={route.mediaId}
            shell={shell}
            from={opening.current.from}
            preview={
              opening.current.preview?.media_id === route.mediaId ? opening.current.preview : null
            }
            onClose={closeTitle}
            playing={route.play || null}
            onStop={stopPlaying}
          />
        )}
      </main>
      <TabBar
        section={behind.screen === 'home' ? (sectionFor(behind.section).parent || behind.section) : behind.screen}
        profile={profile}
        onNavigate={(id) => go({ screen: 'home', section: id })}
        onSearch={() => go({ screen: 'search', query: '' })}
      />
      {ownProfile.element}
      {spaceAsk && <SpaceDialog space={spaceAsk.space} onAnswer={spaceAsk.resolve} />}
      {toast && (
        <div className="toast" role="alert" key={toast.key} onClick={() => setToast(null)}>
          <span className="fail-badge">!</span>
          {toast.message}
        </div>
      )}
    </div>
  )
}

export { buildPath }
