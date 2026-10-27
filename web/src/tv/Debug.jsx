import { useCallback, useEffect, useRef, useState } from 'react'
import { api, formatBytes } from '../api'
import { Icon } from './icons'
import { LANGUAGES, t } from '../shared/i18n'
import { lastIntroPlayback } from './Intro'
import { inputLog } from './inputLog'

const INFO = [
  { id: 'profile', icon: 'user', label: 'Profile' },
  { id: 'device', icon: 'tv', label: 'Device' },
  { id: 'network', icon: 'wifi', label: 'Network' },
  { id: 'server', icon: 'server', label: 'Server' },
  { id: 'playback', icon: 'film', label: 'Playback' },
  { id: 'storage', icon: 'storage', label: 'Storage' },
  { id: 'log', icon: 'list', label: 'Server log' },
  { id: 'input', icon: 'activity', label: 'Remote input' },
]
const TOOLS = [
  { id: 'check', icon: 'activity', label: 'Check connection' },
  { id: 'reload', icon: 'replay', label: 'Reload VibeStream' },
  { id: 'clear', icon: 'trash', label: 'Clear app data' },
  { id: 'switch', icon: 'user', label: 'Switch Profile' },
  { id: 'exit', icon: 'exit', label: 'Exit VibeStream' },
]
const ITEMS = [{ id: 'back', icon: 'back', label: 'Go back' }, ...INFO, ...TOOLS]

function deviceInfo() {
  const raw = (window.webOSSystem && window.webOSSystem.deviceInfo) ||
    (window.PalmSystem && window.PalmSystem.deviceInfo)
  if (!raw) return {}
  try {
    return typeof raw === 'string' ? JSON.parse(raw) : raw
  } catch {
    return {}
  }
}

function chromeVersion() {
  const match = /Chrome\/([\d.]+)/.exec(navigator.userAgent)
  return match ? match[1] : null
}

function webosFromAgent() {
  const match = /Web0S|webOS/.exec(navigator.userAgent)
  return match ? 'webOS' : null
}

function uptime(seconds) {
  if (!seconds && seconds !== 0) return null
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  return d ? `${d}d ${h}h ${m}m` : h ? `${h}h ${m}m` : `${m}m`
}

// Asked of both a video element and MSE: the TV plays HLS natively, a browser goes through MSE, and they can disagree.
const VIDEO_TYPES = [
  ['H.264', 'video/mp4; codecs="avc1.640028"'],
  ['HEVC', 'video/mp4; codecs="hvc1.1.6.L150.B0"'],
  ['HEVC 10 bit', 'video/mp4; codecs="hvc1.2.4.L153.B0"'],
  ['Dolby Vision', 'video/mp4; codecs="dvh1.05.06"'],
  ['VP9', 'video/webm; codecs="vp9"'],
  ['AV1', 'video/mp4; codecs="av01.0.08M.08"'],
]
const AUDIO_TYPES = [
  ['AAC', 'audio/mp4; codecs="mp4a.40.2"'],
  ['AC-3', 'audio/mp4; codecs="ac-3"'],
  ['E-AC-3', 'audio/mp4; codecs="ec-3"'],
  ['Opus', 'audio/webm; codecs="opus"'],
  ['FLAC', 'audio/mp4; codecs="flac"'],
]

function supports(type) {
  const video = document.createElement('video')
  const native = video.canPlayType ? video.canPlayType(type) : ''
  const mse = window.MediaSource && window.MediaSource.isTypeSupported
    ? window.MediaSource.isTypeSupported(type)
    : false
  return Boolean(native) || mse
}

function Fact({ label, value }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className="fact">
      <div className="fact-label">{label}</div>
      <div className="fact-value">{value}</div>
    </div>
  )
}

export default function Debug({ profile, onClose, onSwitchProfile, onExit, registerHandler }) {
  const [index, setIndex] = useState(1)
  const [about, setAbout] = useState(null)
  const [aboutError, setAboutError] = useState(null)
  const [latency, setLatency] = useState(null)
  const [events, setEvents] = useState(null)
  const [storage, setStorage] = useState(null)
  const [check, setCheck] = useState(null)
  const listRef = useRef(null)
  const itemRefs = useRef({})

  const item = ITEMS[index]

  useEffect(() => {
    const started = Date.now()
    api.about()
      .then((data) => {
        setAbout(data)
        setLatency(Date.now() - started)
      })
      .catch((e) => setAboutError(e.message))
  }, [])

  useEffect(() => {
    // The event log needs an admin session; 401 shows as locked.
    if (item.id === 'log' && !events) {
      api.events(40).then(setEvents).catch((e) => setEvents(e.status === 401 ? 'locked' : []))
    }
    if (item.id === 'storage' && !storage) api.downloadManager().then((d) => setStorage(d.totals)).catch(() => setStorage({}))
  }, [item.id, events, storage])

  const runCheck = useCallback(async () => {
    setCheck({ running: true })
    const times = []
    try {
      for (let i = 0; i < 5; i += 1) {
        const started = Date.now()
        await api.about()
        times.push(Date.now() - started)
      }
      const avg = Math.round(times.reduce((a, b) => a + b, 0) / times.length)
      setCheck({ result: t('Average {avg} ms, fastest {min} ms, slowest {max} ms',
        { avg, min: Math.min(...times), max: Math.max(...times) }) })
    } catch (e) {
      setCheck({ error: t('The server did not answer: {error}', { error: e.message }) })
    }
  }, [])

  const runItem = useCallback((id) => {
    if (id === 'back') onClose()
    else if (id === 'check') runCheck()
    else if (id === 'reload') window.location.reload()
    else if (id === 'clear') {
      try {
        localStorage.clear()
        sessionStorage.clear()
      } catch {
        /* nothing to clear */
      }
      window.location.reload()
    } else if (id === 'switch') onSwitchProfile()
    else if (id === 'exit') onExit()
  }, [onClose, runCheck, onSwitchProfile, onExit])

  const activate = useCallback(() => runItem(ITEMS[index].id), [index, runItem])

  useEffect(() => {
    registerHandler({
      onDirection: (dir) => {
        if (dir === 'up') setIndex((i) => Math.max(0, i - 1))
        if (dir === 'down') setIndex((i) => Math.min(ITEMS.length - 1, i + 1))
      },
      onEnter: activate,
      onBack: () => {
        onClose()
        return true
      },
    })
  }, [registerHandler, activate, onClose])

  useEffect(() => {
    const list = listRef.current
    const el = itemRefs.current[index]
    if (!list || !el) return
    const top = el.offsetTop
    if (top < list.scrollTop) list.scrollTop = top - 12
    else if (top + el.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = top + el.offsetHeight - list.clientHeight + 12
    }
  }, [index])

  const device = deviceInfo()
  const yes = (value) => (value ? t('Yes') : t('No'))

  let content
  switch (item.id) {
    case 'back':
      content = <p className="debug-lead">{t('System information and tools for when something is not right.')}</p>
      break
    case 'profile':
      content = profile && (
        <>
          <Fact label={t('Profile name')} value={profile.name} />
          <Fact label={t('Profile ID')} value={String(profile.id)} />
          <Fact label={t('Language')} value={(LANGUAGES.find((l) => l.id === profile.language) || LANGUAGES[0]).name} />
          <Fact label={t('Icon')} value={profile.avatar} />
        </>
      )
      break
    case 'device':
      content = (
        <>
          <Fact label={t('Model')} value={device.modelName || device.modelNameAscii} />
          <Fact label={t('Firmware')} value={device.platformVersion || device.sdkVersion || device.firmwareVersion || webosFromAgent()} />
          <Fact label={t('App build')} value={import.meta.env.LEGACY_TV ? t('Legacy (webOS 4.5)') : t('Modern (webOS 6)')} />
          <Fact label={t('Intro playback')} value={lastIntroPlayback()} />
          <Fact label={t('Browser')} value={chromeVersion() ? `Chromium ${chromeVersion()}` : null} />
          <Fact label={t('Screen')} value={`${window.screen.width} × ${window.screen.height}, ${window.innerWidth} × ${window.innerHeight} @${window.devicePixelRatio || 1}x`} />
          <Fact label={t('User agent')} value={navigator.userAgent} />
        </>
      )
      break
    case 'network':
      content = (
        <>
          <Fact label={t('Server address')} value={window.location.origin} />
          <Fact label={t('This TV, as the server sees it')} value={about && about.client_ip} />
          <Fact label={t('Network')} value={navigator.onLine === false ? t('Offline') : t('Online')} />
          <Fact label="Ping" value={latency !== null ? `${latency} ms` : null} />
          {aboutError && <Fact label={t('Problem')} value={aboutError} />}
        </>
      )
      break
    case 'server':
      content = about ? (
        <>
          <Fact label={t('Version')} value={about.version} />
          <Fact label={t('Uptime')} value={uptime(about.uptime_seconds)} />
          <Fact label={t('Server time')} value={new Date(about.server_time * 1000).toLocaleString()} />
          <Fact label={t('Clock difference')} value={`${Math.round(Date.now() / 1000 - about.server_time)} s`} />
          <Fact label="Python" value={about.python} />
          <Fact label="Platform" value={about.platform} />
        </>
      ) : (
        <p className="debug-lead">{aboutError || t('Loading...')}</p>
      )
      break
    case 'playback':
      content = (
        <>
          <div className="fact">
            <div className="fact-label">{t('Video formats')}</div>
            <div className="codec-list">
              {VIDEO_TYPES.map(([name, type]) => (
                <span key={name} className={`codec ${supports(type) ? 'ok' : ''}`}>{name}</span>
              ))}
            </div>
          </div>
          <div className="fact">
            <div className="fact-label">{t('Audio formats')}</div>
            <div className="codec-list">
              {AUDIO_TYPES.map(([name, type]) => (
                <span key={name} className={`codec ${supports(type) ? 'ok' : ''}`}>{name}</span>
              ))}
            </div>
          </div>
          <Fact label={t('Display supports HDR')}
            value={yes(window.matchMedia && window.matchMedia('(dynamic-range: high)').matches)} />
          <Fact label="HLS" value={yes(document.createElement('video').canPlayType('application/vnd.apple.mpegurl'))} />
          <Fact label="Media Source" value={yes(window.MediaSource)} />
        </>
      )
      break
    case 'storage':
      content = storage ? (
        <>
          <Fact label={t('Downloads')} value={storage.count !== undefined ? String(storage.count) : null} />
          <Fact label={t('Torrent files')} value={storage.torrent_bytes !== undefined ? formatBytes(storage.torrent_bytes) : null} />
          <Fact label={t('Playback files')} value={storage.playback_bytes !== undefined ? formatBytes(storage.playback_bytes) : null} />
          <Fact label={t('Free space')} value={storage.free_bytes ? formatBytes(storage.free_bytes) : null} />
        </>
      ) : <p className="debug-lead">{t('Loading...')}</p>
      break
    case 'input': {
      const list = inputLog().reverse().slice(0, 16)
      content = list.length === 0 ? (
        <p className="debug-lead">{t('Nothing logged yet.')}</p>
      ) : (
        <div className="log">
          {list.map((e, i) => {
            const before = list[i + 1]
            return (
              <div key={`${e.at}-${i}`} className="log-line">
                <span className="log-time">{new Date(e.at).toLocaleTimeString()}</span>
                <span className="log-source">{before ? `+${e.at - before.at} ms` : ''}</span>
                <span className="log-message">{e.what}</span>
              </div>
            )
          })}
        </div>
      )
      break
    }
    case 'log':
      content = !events ? (
        <p className="debug-lead">{t('Loading...')}</p>
      ) : events === 'locked' ? (
        <p className="debug-lead">
          {t('The server log is in the admin dashboard: {address}', { address: `${window.location.host}/admin` })}
        </p>
      ) : events.length === 0 ? (
        <p className="debug-lead">{t('Nothing logged yet.')}</p>
      ) : (
        <div className="log">
          {events.slice(0, 14).map((e) => (
            <div key={e.id} className={`log-line ${e.level}`}>
              <span className="log-time">{new Date(e.ts).toLocaleString()}</span>
              <span className="log-source">{e.source}</span>
              <span className="log-message">{e.message}</span>
            </div>
          ))}
        </div>
      )
      break
    case 'check':
      content = (
        <>
          <p className="debug-lead">{t('Measure how quickly the server answers this TV.')}</p>
          <p className="debug-result">
            {check && check.running ? t('Running...') : check && (check.result || check.error)}
            {!check && t('Press OK to run it.')}
          </p>
        </>
      )
      break
    case 'reload':
      content = <><p className="debug-lead">{t('Reload the VibeStream app.')}</p><p className="debug-result">{t('Press OK to do it.')}</p></>
      break
    case 'clear':
      content = <><p className="debug-lead">{t('Forget what this TV remembers (the last profile, positions, preferences) and reload.')}</p><p className="debug-result">{t('Press OK to do it.')}</p></>
      break
    case 'switch':
      content = <p className="debug-lead">{t('Choose a Profile')}</p>
      break
    case 'exit':
      content = <p className="debug-lead">{t('Close the VibeStream app.')}</p>
      break
    default:
      content = null
  }

  return (
    <div className="debug">
      <div className="debug-menu" ref={listRef}>
        <h1>
          <Icon name="bug" size={36} />
          {t('Debug')}
        </h1>
        {ITEMS.map((entry, i) => (
          <div
            key={entry.id}
            ref={(el) => { itemRefs.current[i] = el }}
            className={[
              'menu-item',
              'with-icon',
              index === i ? 'focused' : '',
              entry.id === 'check' ? 'group-start' : '',
            ].join(' ')}
            onMouseEnter={() => setIndex(i)}
            onClick={() => {
              setIndex(i)
              if (entry.id === 'back' || TOOLS.some((tool) => tool.id === entry.id)) runItem(entry.id)
            }}
          >
            <Icon name={entry.icon} size={24} />
            <span>{t(entry.label)}</span>
          </div>
        ))}
        <div className="list-spacer small" />
      </div>
      <div className="debug-content">
        <h2>{t(item.label)}</h2>
        {content}
      </div>
    </div>
  )
}
