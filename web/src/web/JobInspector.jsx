import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api, errorText, formatBytes, formatEta, formatSpeed } from '../api'
import { Icon, PlayIcon } from '../shared/icons'
import { jobArt, jobStatus, jobSubtitle, seedingOwed, torrentState, when } from './jobs'

const REFRESH_MS = 3000

const SECTIONS = [
  ['activity', 'Activity'],
  ['pieces', 'Pieces'],
  ['files', 'Files'],
  ['peers', 'Peers'],
  ['trackers', 'Trackers'],
  ['info', 'Information'],
]

const given = (value) => value !== null && value !== undefined && value !== ''

/* A speed that reads as zero when it is zero, which formatSpeed leaves blank. */
const speed = (value) => (value > 0 ? formatSpeed(value) : '0 B/s')
const bytes = (value) => (given(value) ? formatBytes(value) : null)
const duration = (seconds) => (given(seconds) && seconds >= 0 ? formatEta(seconds) : null)
/* qBittorrent says -1 for a swarm count it does not know. */
const known = (value) => given(value) && value >= 0

function shade(have) {
  if (!have) return 'rgba(255, 255, 255, 0.07)'
  return `rgba(255, 106, 0, ${(0.25 + 0.75 * have / 100).toFixed(2)})`
}

const fileName = (path) => (path || '').slice((path || '').lastIndexOf('/') + 1)

function Facts({ rows }) {
  const shown = rows.filter(([, value]) => given(value))
  if (!shown.length) return null
  return (
    <dl className="ins-facts">
      {shown.map(([label, value, wrap]) => (
        <div key={label}>
          <dt>{label}</dt>
          <dd className={wrap ? 'wrap' : ''}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

function Activity({ data }) {
  const tor = data.torrent || {}
  const seeding = data.job?.seeding
  const progress = tor.progress || 0
  return (
    <Facts rows={[
      ['State', tor.state ? withRaw(torrentState(tor.state), tor.state) : null],
      ['Progress', given(tor.progress) ? `${progress.toFixed(1)}%` : null],
      ['Have', given(tor.size_bytes)
        ? `${formatBytes(tor.size_bytes * progress / 100)} of ${formatBytes(tor.size_bytes)}` : null],
      ['Torrent size', bytes(tor.total_size_bytes)],
      ['Downloaded', bytes(tor.downloaded_bytes)],
      ['Uploaded', bytes(tor.uploaded_bytes)],
      ['Ratio', given(tor.ratio) ? Number(tor.ratio).toFixed(2) : null],
      ['Download speed', given(tor.dl_speed) ? `${speed(tor.dl_speed)} now, ${speed(tor.dl_speed_avg)} average` : null],
      ['Upload speed', given(tor.up_speed) ? `${speed(tor.up_speed)} now, ${speed(tor.up_speed_avg)} average` : null],
      ['Remaining', duration(tor.eta_seconds)],
      ['Wasted', bytes(tor.wasted_bytes)],
      ['Time active', duration(tor.elapsed_seconds)],
      ['Seeding time', duration(tor.seeding_seconds)],
      ['Connections', given(tor.connections) ? `${tor.connections} of ${tor.connections_limit}` : null],
      ['Seeds', given(tor.seeds) ? `${tor.seeds} connected of ${tor.seeds_total}` : null],
      ['Leechers', given(tor.leechers) ? `${tor.leechers} connected of ${tor.leechers_total}` : null],
      ['Next announce', duration(tor.reannounce_seconds)],
      ['Seeding requirement', seeding ? (seeding.met ? 'Met' : seedingOwed(seeding)) : null, true],
    ]} />
  )
}

function Pieces({ data }) {
  const tor = data.torrent || {}
  const { have = [], busy = [], count = 0 } = data.pieces || {}
  if (!have.length) return <p className="note">No pieces to show.</p>
  const per = count > have.length ? Math.round(count / have.length) : 1
  return (
    <>
      {tor.pieces_count ? (
        <p className="ins-lead">
          {tor.pieces_count} pieces of {formatBytes(tor.piece_size)}, {tor.pieces_have || 0} have
          {per > 1 && <span className="faint">. Each square stands for about {per}.</span>}
        </p>
      ) : null}
      <div className="ins-pieces">
        {have.map((value, i) => (
          <span key={i} className={busy[i] ? 'busy' : ''} style={{ background: shade(value) }}
            title={`${value}% here${busy[i] ? ', downloading now' : ''}`} />
        ))}
      </div>
      <div className="ins-legend">
        <span><i style={{ background: shade(100) }} />Have</span>
        <span><i style={{ background: shade(50) }} />Partly</span>
        <span><i style={{ background: shade(0) }} />Missing</span>
        <span><i className="busy" style={{ background: shade(0) }} />Downloading now</span>
      </div>
    </>
  )
}

function Files({ data }) {
  const files = data.files || []
  if (!files.length) return <p className="note">No files to show.</p>
  return (
    <ul className="ins-files">
      {files.map((file, i) => {
        const skipped = file.priority === 0
        const progress = file.progress || 0
        return (
          <li key={`${file.name}-${i}`} className={`${file.mine ? 'mine' : ''} ${skipped ? 'skipped' : ''}`}>
            <div className="ins-file-name" title={file.name}>
              <span>{fileName(file.name)}</span>
              {file.mine && <em className="ins-tag">This download</em>}
            </div>
            <div className="ins-file-line">
              {skipped ? <span className="ins-skipped">Skipped</span> : (
                <div className="dl-progress"><span style={{ width: `${Math.min(100, progress)}%` }} /></div>
              )}
              <span className="ins-file-size">
                {skipped ? formatBytes(file.size_bytes) : `${progress.toFixed(progress < 100 ? 1 : 0)}% of ${formatBytes(file.size_bytes)}`}
              </span>
            </div>
          </li>
        )
      })}
    </ul>
  )
}

function Peers({ data }) {
  const peers = data.peers || []
  if (!peers.length) return <p className="note">No peers connected</p>
  return (
    <div className="ins-scroll">
      <table className="ins-table">
        <thead>
          <tr>
            <th>Address</th>
            <th>Client</th>
            <th>Flags</th>
            <th className="num">Progress</th>
            <th className="num">Down</th>
            <th className="num">Up</th>
          </tr>
        </thead>
        <tbody>
          {peers.map((peer, i) => (
            <tr key={`${peer.address}-${i}`}>
              <td className="addr" title={[peer.country, peer.connection].filter(Boolean).join(', ')}>
                {peer.country_code && <em className="ins-cc">{peer.country_code.toUpperCase()}</em>}
                {peer.address}
              </td>
              <td className="client">{peer.client}</td>
              <td className="flags">{peer.flags}</td>
              <td className="num">{Math.round(peer.progress || 0)}%</td>
              <td className="num">{peer.dl_speed > 0 ? formatSpeed(peer.dl_speed) : ''}</td>
              <td className="num">{peer.up_speed > 0 ? formatSpeed(peer.up_speed) : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Trackers({ data }) {
  const trackers = data.trackers || []
  if (!trackers.length) return <p className="note">No trackers to show.</p>
  return (
    <ul className="ins-trackers">
      {trackers.map((tracker, i) => {
        const numbers = [
          known(tracker.seeds) && `Seeds ${tracker.seeds}`,
          known(tracker.leechers) && `Leechers ${tracker.leechers}`,
          known(tracker.peers) && `Peers ${tracker.peers}`,
          known(tracker.downloaded) && `Downloaded ${tracker.downloaded}`,
        ].filter(Boolean)
        const tone = tracker.status === 'working' ? 'good' : tracker.status === 'not working' ? 'bad' : ''
        return (
          <li key={`${tracker.host}-${i}`}>
            <div className="ins-tracker-head">
              <strong>{tracker.host}</strong>
              <span className={`ins-chip ${tone}`}>{tracker.status}</span>
            </div>
            {numbers.length > 0 && <div className="ins-tracker-line">{numbers.join('  ·  ')}</div>}
            {tracker.message && <div className="ins-tracker-line faint">{tracker.message}</div>}
          </li>
        )
      })}
    </ul>
  )
}

function preparationText(prep) {
  if (!prep) return null
  if (prep.error) return `Failed: ${prep.error}`
  if (prep.ready) return 'Ready'
  const percent = Math.round(prep.percent || 0)
  return [prep.stage, percent ? `${percent}%` : null].filter(Boolean).join(' ') || 'Waiting'
}

function sourceText(library) {
  if (library.source_removed) return 'Removed. The title plays from what was built from it.'
  const size = formatBytes(library.source_bytes)
  return library.source_removable ? `${size}, can be removed. The title keeps playing.` : `${size}, kept for now`
}

function RemoveSource({ job, library, onDone }) {
  const [asking, setAsking] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const owed = job?.seeding && !job.seeding.met

  const remove = async () => {
    setBusy(true)
    try {
      await api.removeSource(job.download_id, owed)
      setAsking(false)
      await onDone()
    } catch (e) {
      setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="ins-source">
      <p>
        Removes the downloaded copy, {formatBytes(library.source_bytes)}. The title keeps playing
        from what was built from it.
        {job?.shares_torrent && ' Every download from this torrent loses it.'}
      </p>
      {owed && asking && (
        <p className="row-warn">{seedingOwed(job.seeding)} Removing it now counts as a hit and run on filelist.</p>
      )}
      {error && <p className="note error">{error}</p>}
      <div className="ins-source-actions">
        {asking ? (
          <>
            <button className="btn small danger" onClick={remove} disabled={busy}>
              {busy ? 'Removing...' : owed ? 'Remove Anyway' : 'Remove'}
            </button>
            <button className="btn small" onClick={() => setAsking(false)}>Keep</button>
          </>
        ) : (
          <button className="btn small" onClick={() => setAsking(true)}>
            <Icon name="source-remove" size={15} /> Remove Source
          </button>
        )}
      </div>
    </div>
  )
}

function Information({ data, onChanged }) {
  const release = data.release || {}
  const tor = data.torrent || {}
  const library = data.library || {}
  const job = data.job || {}
  const quality = [release.resolution, release.source, release.video_codec, release.audio_codec, release.hdr]
    .filter(Boolean).join(' · ')
  const flags = [release.freeleech && 'Freeleech', release.internal && 'Internal'].filter(Boolean).join(' · ')
  return (
    <>
      <h4 className="ins-group">Release</h4>
      <Facts rows={[
        ['Name', release.name || job.release, true],
        ['Category', release.category_name],
        ['Quality', quality],
        ['Group', release.release_group],
        ['Uploaded', when(release.upload_date)],
        ['On the tracker', given(release.seeders) ? `${release.seeders} seeders, ${release.leechers || 0} leechers` : null],
        ['Flags', flags],
      ]} />

      {data.live && (
        <>
          <h4 className="ins-group">Torrent</h4>
          <Facts rows={[
            ['Name', tor.name, true],
            ['Info hash', tor.info_hash, true],
            ['Save path', tor.save_path, true],
            ['Content path', tor.content_path, true],
            ['Created by', tor.created_by],
            ['Created', when(tor.created_at)],
            ['Added', when(tor.added_at)],
            ['Completed', when(tor.completed_at)],
            ['Last seen complete', when(tor.last_seen_complete)],
          ]} />
        </>
      )}

      <h4 className="ins-group">Library</h4>
      <Facts rows={[
        ['Requested', when(job.requested_at || library.requested_at)],
        ['Library path', library.library_path, true],
        ['Asked for', library.wanted?.length ? library.wanted.join(', ') : null, true],
        ['Preparation', preparationText(library.preparation), true],
        ['Source', given(library.source_removed) ? sourceText(library) : null, true],
      ]} />
      {library.source_removable && <RemoveSource job={job} library={library} onDone={onChanged} />}
    </>
  )
}

export default function JobInspector({ jobId, onClose, onChanged, onPlay }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const bodyRef = useRef(null)
  const sectionRefs = useRef({})

  const load = useCallback(async () => {
    try {
      setData(await api.inspectJob(jobId))
      setError(null)
    } catch (e) {
      setError(errorText(e))
    }
  }, [jobId])

  useEffect(() => {
    let alive = true
    let timer = null
    const tick = async () => {
      await load()
      if (alive) timer = setTimeout(tick, REFRESH_MS)
    }
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [load])

  // The page behind keeps its place but does not scroll under the panel.
  useEffect(() => {
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previous
    }
  }, [])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const changed = useCallback(async () => {
    await load()
    await onChanged()
  }, [load, onChanged])

  const jump = (id) => {
    const body = bodyRef.current
    const section = sectionRefs.current[id]
    if (body && section) body.scrollTo({ top: section.offsetTop - 56, behavior: 'smooth' })
  }

  const job = data?.job
  const art = job ? jobArt(job) : null
  const status = job ? jobStatus(job) : null
  const live = data?.live
  const counts = {
    files: data?.files?.length,
    peers: data?.peers?.length,
    trackers: data?.trackers?.length,
  }
  const sections = {
    activity: Activity, pieces: Pieces, files: Files, peers: Peers, trackers: Trackers,
  }

  return createPortal(
    <div className="ins-backdrop" onClick={onClose}>
      <aside className="inspector" ref={bodyRef} onClick={(e) => e.stopPropagation()}
        role="dialog" aria-label="Download details">
        <header className="ins-header">
          {art && (
            <div className={`ins-art ${art.wide ? 'wide' : ''}`}>
              {art.src && <img src={art.src} alt="" />}
            </div>
          )}
          <div className="ins-header-text">
            <h2>{job ? job.title : 'Details'}</h2>
            {job && jobSubtitle(job) && <div className="ins-sub">{jobSubtitle(job)}</div>}
            {status && (
              <div className={`dl-state job ${status.tone}`}>
                {status.failed ? <span className="fail-badge">!</span> : <i className="dot" />}
                <span>{status.text}</span>
              </div>
            )}
            {job?.play_id && (
              <button className="btn small primary ins-play" onClick={() => onPlay(job.play_id)}>
                <PlayIcon size={14} /> Play
              </button>
            )}
          </div>
        </header>

        <div className="ins-nav">
          <nav className="ins-tabs">
            {SECTIONS.map(([id, label]) => (
              <button key={id} onClick={() => jump(id)}>
                {label}
                {counts[id] ? <span>{counts[id]}</span> : null}
              </button>
            ))}
          </nav>
          <button className="ins-close" onClick={onClose} aria-label="Close"><Icon name="close" size={18} /></button>
        </div>

        {!data && !error && <p className="note ins-pad">Loading...</p>}
        {error && <p className="note error ins-pad">{error}</p>}
        {data && !live && (
          <p className="note ins-pad">qBittorrent is not answering, so there is nothing live to show.</p>
        )}

        {data && SECTIONS.map(([id, label]) => {
          const Section = sections[id]
          if (id !== 'info' && !live) return null
          return (
            <section key={id} className="ins-section" ref={(el) => { sectionRefs.current[id] = el }}>
              <h3>{label}</h3>
              {Section ? <Section data={data} /> : <Information data={data} onChanged={changed} />}
            </section>
          )
        })}
      </aside>
    </div>,
    document.body,
  )
}

function withRaw(words, raw) {
  return words.toLowerCase() === raw.toLowerCase() ? words : `${words} (${raw})`
}
