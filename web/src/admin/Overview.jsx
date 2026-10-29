import { useEffect, useState } from 'react'
import { Icon } from '../shared/icons'
import { admin } from './api'
import { ago, bytes, CopyButton, duration, PageHead, Panel, Ring, useToast } from './ui'

const INTEGRATIONS = [
  { id: 'filelist', name: 'Filelist', what: 'Where new releases come from.' },
  { id: 'addons', name: 'Stremio addons', what: 'Releases from Torrentio and the like.' },
  { id: 'torbox', name: 'TorBox', what: 'Fetches addon releases for this server.' },
  { id: 'tmdb', name: 'TMDB', what: 'Titles, posters and descriptions.' },
  { id: 'qbittorrent', name: 'qBittorrent', what: 'Downloads the releases.' },
]

// The configured sources, or filelist alone when none is.
function shown(health) {
  const on = (id) => health && health.integrations[id] && health.integrations[id].configured
  const none = !on('filelist') && !on('addons')
  return INTEGRATIONS.filter((i) => (i.id === 'filelist' ? on('filelist') || none
    : i.id === 'addons' || i.id === 'torbox' ? on(i.id) : true))
}

/* Download posters arrive as a bare TMDB path (/abc.jpg). */
const TMDB_IMAGES = 'https://image.tmdb.org/t/p'
const posterSrc = (path) => (path && path.charAt(0) === '/' ? `${TMDB_IMAGES}/w185${path}` : path)

function greeting() {
  const h = new Date().getHours()
  if (h < 5) return 'Up late'
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export default function Overview({ go }) {
  const [o, setO] = useState(null)
  const [health, setHealth] = useState(null)
  const [checking, setChecking] = useState(false)
  const [recent, setRecent] = useState([])
  const [release, setRelease] = useState(null)
  const [news, setNews] = useState(null)
  const [running, setRunning] = useState(null)
  const say = useToast()

  const load = () => admin.overview().then(setO).catch(() => {})
  const check = () => {
    setChecking(true)
    admin.health().then(setHealth).catch(() => {}).finally(() => setChecking(false))
  }

  useEffect(() => {
    load()
    check()
    admin.events({ limit: 6 }).then(setRecent).catch(() => {})
    admin.version().then(setRelease).catch(() => {})
    admin.news().then(setNews).catch(() => {})
    const timer = setInterval(load, 10000)
    return () => clearInterval(timer)
  }, [])

  const job = async (id, fn, done) => {
    setRunning(id)
    try {
      say(done(await fn()))
      load()
    } catch (e) {
      say(e.message, true)
    } finally {
      setRunning(null)
    }
  }

  if (!o) return <Skeleton />

  const of = (id) => health && health.integrations[id]
  const broken = shown(health).filter((i) => of(i.id) && of(i.id).configured && !of(i.id).ok)
  const unset = shown(health).filter((i) => of(i.id) && !of(i.id).configured)
  const level = broken.length ? 'bad' : unset.length || o.problems_24h ? 'warn' : ''
  const headline = broken.length
    ? `${names(broken)} ${broken.length === 1 ? 'is' : 'are'} not answering`
    : unset.length
      ? `${names(unset)} ${unset.length === 1 ? 'is' : 'are'} not set up yet`
      : o.problems_24h
      ? `Running, with ${o.problems_24h} warning${o.problems_24h === 1 ? '' : 's'} today`
      : 'Everything is running smoothly'
  const downloading = o.moving.filter((m) => m.state === 'downloading').length
  const finished = (o.downloads.completed || 0) + (o.downloads.seeding || 0) + (o.downloads.linked || 0)

  return (
    <>
      <PageHead title={greeting()} text="Here is how your server is doing." />

      <section className="hello">
        <span className={`pulse ${level}`} />
        <div>
          <h2>{headline}</h2>
          <p>
            {o.problems_24h > 0
              ? <button className="link" onClick={() => go('activity')}>See what happened</button>
              : 'Nothing has gone wrong in the last 24 hours.'}
          </p>
        </div>
        <div className="hello-facts">
          <div><b>{duration(o.uptime_seconds)}</b><span>up</span></div>
          <div><b>{o.engine === 'live' ? 'Live' : 'Converted'}</b><span>playback</span></div>
          <div><b>{o.version}</b><span>{release && release.build ? `build ${release.build}` : 'version'}</span></div>
        </div>
      </section>

      {release && release.available && <Update release={release} />}
      {news && news.show && <WhatsNew news={news} onDone={() => { setNews(null); admin.newsSeen().catch(() => {}) }} />}

      <div className="grid four" style={{ marginBottom: 18 }}>
        <Stat icon="film" label="Movies" value={o.library.movies} foot="ready to play" />
        <Stat icon="tv" label="Shows" value={o.library.shows} foot="ready to play" />
        <Stat icon="download" label="Downloads" value={downloading}
          foot={`${finished} finished, ${o.downloads.error || 0} failed`} small="active" />
        <Stat icon="wifi" label="Watching now" value={o.live_streams}
          foot={`${o.devices_online} device${o.devices_online === 1 ? '' : 's'} open, ${o.profiles} profiles`} small="streams" />
      </div>

      <div className="grid two" style={{ marginBottom: 18 }}>
        <Panel title="Storage" icon="storage"
          action={<button className="btn small quiet" onClick={() => go('library')}>Manage</button>}>
          {o.disks.length === 0 && <div className="empty">No library folder found on the server.</div>}
          {o.disks.map((d, i) => {
            const used = d.total - d.free
            return (
              <div className="disk" key={i}>
                <Ring used={used} total={d.total} />
                <div>
                  <b>{d.labels.join(', ')}</b>
                  <div className="dim">{bytes(d.free)} free of {bytes(d.total)}</div>
                  <div className="paths mono">{d.paths.join('  ')}</div>
                </div>
              </div>
            )
          })}
        </Panel>

        <Panel title="Downloading" icon="download">
          {o.moving.length === 0 && <div className="empty">Nothing downloading right now.</div>}
          <div className="list">
            {o.moving.map((m) => (
              <div className="item" key={m.id}>
                {m.poster ? <img className="poster" src={posterSrc(m.poster)} alt="" /> : <div className="poster" />}
                <div className="item-main">
                  <b>{m.title}</b>
                  <div className="bar" style={{ margin: '7px 0 5px' }}><span style={{ width: `${Math.round(m.progress * 100)}%` }} /></div>
                  <span>
                    {m.state === 'downloading'
                      ? `${Math.round(m.progress * 100)}%  ·  ${bytes(m.speed)}/s${m.eta ? `  ·  ${duration(m.eta)} left` : ''}`
                      : m.state}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>

      <Panel title="Integrations" icon="server" className="span-2"
        action={(
          <button className="btn small" onClick={check} disabled={checking}>
            {checking ? <span className="spinner" /> : <Icon name="replay" size={15} />} Check again
          </button>
        )}>
        <div className={`grid ${shown(health).length === 4 ? 'four' : 'three'}`}>
          {shown(health).map((i) => {
            const h = health && health.integrations[i.id]
            const tone = !h ? '' : !h.configured ? 'warn' : h.ok ? 'good' : 'bad'
            return (
              <div className="integration" key={i.id}>
                <div className="integration-head">
                  <span className={`dot ${tone}`} />
                  <b>{i.name}</b>
                  {h && (
                    <span className={`badge ${tone}`}>
                      {!h.configured ? 'Not set up' : h.ok ? 'Connected' : 'Failing'}
                    </span>
                  )}
                </div>
                <p>{h ? (h.ok ? (h.names ? h.names.join(', ') : i.what) : h.detail) : 'Checking...'}</p>
                {i.id === 'filelist' && h && h.requests_remaining !== undefined && (
                  <span className="faint" style={{ fontSize: 12 }}>{h.requests_remaining} of 150 API requests left this hour</span>
                )}
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="grid two" style={{ marginTop: 18 }}>
        <Panel title="Run now" icon="replay" sub="These run on their own schedule too. Running one early is safe.">
          <div className="list">
            <JobRow title="Look for new releases" text="Filelist's newest, and the trending titles from your addons, from whichever is set up."
              busy={running === 'sweep'} onRun={() => job('sweep', admin.sweep,
                (r) => `Sweep done: ${r.inserted} new, ${r.updated} updated.`)} />
            <JobRow title="Fetch missing details" text="Posters, descriptions and matches from TMDB."
              busy={running === 'enrich'} onRun={() => job('enrich', admin.enrich,
                (r) => `Details: ${r.lookups.matched + r.details.matched} matched.`)} />
            <JobRow title="Preview a clean up" text="What a clean up would delete now. Deletes nothing."
              busy={running === 'reap'} onRun={() => job('reap', () => admin.reap(true),
                (r) => `${r.reaped.length || 0} title(s) would go, freeing ${r.gb_freed} GB.`)} />
          </div>
        </Panel>

        <Panel title="Recent activity" icon="activity"
          action={<button className="btn small quiet" onClick={() => go('activity')}>All activity</button>}>
          <div className="list">
            {recent.length === 0 && <div className="empty">Nothing logged yet.</div>}
            {recent.map((e) => (
              <div className="item" key={e.id}>
                <span className={`dot ${e.level === 'error' ? 'bad' : e.level === 'warn' ? 'warn' : ''}`} />
                <div className="item-main">
                  <b>{e.message}</b>
                  <span>{e.source}  ·  {ago(e.ts)}</span>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  )
}

function names(list) {
  const all = list.map((i) => i.name)
  return all.length < 3 ? all.join(' and ') : `${all.slice(0, -1).join(', ')} and ${all[all.length - 1]}`
}

function Stat({ icon, label, value, foot, small }) {
  return (
    <div className="panel stat">
      <div className="stat-label"><Icon name={icon} size={16} /> {label}</div>
      <div className="stat-value">{value}{small && <small>{small}</small>}</div>
      <div className="stat-foot">{foot}</div>
      <Icon name={icon} size={96} className="big" />
    </div>
  )
}

function JobRow({ title, text, busy, onRun }) {
  return (
    <div className="item">
      <div className="item-main">
        <b>{title}</b>
        <span>{text}</span>
      </div>
      <button className="btn small" onClick={onRun} disabled={busy}>
        {busy ? <span className="spinner" /> : <Icon name="play" size={14} />} Run
      </button>
    </div>
  )
}

function Skeleton() {
  return (
    <>
      <div className="skeleton" style={{ height: 34, width: 260, marginBottom: 30 }} />
      <div className="skeleton" style={{ height: 96, marginBottom: 18, borderRadius: 18 }} />
      <div className="grid four">
        {[0, 1, 2, 3].map((i) => <div key={i} className="skeleton" style={{ height: 130, borderRadius: 14 }} />)}
      </div>
    </>
  )
}

// After an update: what changed since the version this server ran before, until dismissed.
function WhatsNew({ news, onDone }) {
  return (
    <section className="update news">
      <Icon name="info" size={20} />
      <div className="update-main">
        <b>Updated to {news.version}</b>
        <span>From {news.updated_from}. What is new:</span>
        {news.releases.map((r) => (
          <div key={r.version} className="news-release">
            {news.releases.length > 1 && <h4>{r.version}</h4>}
            {r.intro && <p>{r.intro}</p>}
            <ul>
              {[...r.server, ...r.apps].map((item, i) => (
                <li key={i}><b>{item.title}</b>{item.text}</li>
              ))}
            </ul>
          </div>
        ))}
        <div><button className="btn small" onClick={onDone}>Got it</button></div>
      </div>
    </section>
  )
}

// A newer release: what it is, and the one command on the server that installs it.
function Update({ release }) {
  return (
    <section className="update">
      <Icon name="download" size={20} />
      <div className="update-main">
        <b>VibeStream {release.latest.version} is out</b>
        <span>
          This server runs {release.version}.{' '}
          {release.latest.url && <a href={release.latest.url} target="_blank" rel="noreferrer">What is new</a>}
        </span>
        <div className="gate-command">
          <code className="mono">{release.command}</code>
          <CopyButton text={release.command} />
        </div>
        <span className="faint">Run it on the server. The database is backed up first, and if the new version does not start, the old one comes back by itself.</span>
      </div>
    </section>
  )
}
