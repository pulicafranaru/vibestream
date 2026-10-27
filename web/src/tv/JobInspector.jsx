import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText, formatBytes, formatEta, formatSpeed } from '../api'
import { BackIcon, Icon } from './icons'
import { t } from '../shared/i18n'
import { setPageScroll } from './navigation'
import {
  jobArt, jobStatus, jobSubtitle, seedingOwed, torrentState, trackerStatus, when,
} from './jobs'

const REFRESH_MS = 3000
const SCROLL_STEP = 320

const SECTIONS = [
  { id: 'activity', icon: 'activity' },
  { id: 'pieces', icon: 'grid' },
  { id: 'files', icon: 'film' },
  { id: 'peers', icon: 'user' },
  { id: 'trackers', icon: 'globe' },
  { id: 'info', icon: 'info' },
]

function sectionLabel(id) {
  if (id === 'activity') return t('Activity')
  if (id === 'pieces') return t('Pieces')
  if (id === 'files') return t('Files')
  if (id === 'peers') return t('Peers')
  if (id === 'trackers') return t('Trackers')
  if (id === 'info') return t('Information')
  return t('Remove Source')
}

const given = (value) => value !== null && value !== undefined && value !== ''

const speed = (value) => (value > 0 ? formatSpeed(value) : '0 B/s')

const bytes = (value) => (given(value) ? formatBytes(value) : null)

const duration = (seconds) => (given(seconds) && seconds >= 0 ? formatEta(seconds) : null)

/* qBittorrent reports -1 for an unknown swarm count. */
const count = (value) => (given(value) && value >= 0 ? String(value) : null)

function Row({ label, value, wrap }) {
  if (!given(value)) return null
  return (
    <div className="ins-row">
      <div className="ins-label">{label}</div>
      <div className={`ins-value ${wrap ? 'wrap' : ''}`}>{value}</div>
    </div>
  )
}

function shade(have) {
  if (!have) return 'rgba(255, 255, 255, 0.08)'
  return `rgba(255, 106, 0, ${(0.25 + 0.75 * have / 100).toFixed(2)})`
}

function fileName(path) {
  const name = path || ''
  return name.slice(name.lastIndexOf('/') + 1)
}

function Activity({ data }) {
  const tor = data.torrent || {}
  const seeding = data.job && data.job.seeding
  const progress = tor.progress || 0
  return (
    <>
      <Row label={t('State')} value={tor.state ? withRaw(torrentState(tor.state), tor.state) : null} />
      <Row label={t('Progress')} value={given(tor.progress) ? `${progress.toFixed(1)}%` : null} />
      <Row label={t('Have')} value={given(tor.size_bytes)
        ? t('{have} of {size}', { have: formatBytes(tor.size_bytes * progress / 100), size: formatBytes(tor.size_bytes) })
        : null} />
      <Row label={t('Torrent size')} value={bytes(tor.total_size_bytes)} />
      <Row label={t('Downloaded')} value={bytes(tor.downloaded_bytes)} />
      <Row label={t('Uploaded')} value={bytes(tor.uploaded_bytes)} />
      <Row label={t('Ratio')} value={given(tor.ratio) ? Number(tor.ratio).toFixed(2) : null} />
      <Row label={t('Download speed')} value={given(tor.dl_speed)
        ? t('{now} now, {avg} average', { now: speed(tor.dl_speed), avg: speed(tor.dl_speed_avg) })
        : null} />
      <Row label={t('Upload speed')} value={given(tor.up_speed)
        ? t('{now} now, {avg} average', { now: speed(tor.up_speed), avg: speed(tor.up_speed_avg) })
        : null} />
      <Row label={t('Remaining')} value={duration(tor.eta_seconds)} />
      <Row label={t('Wasted')} value={bytes(tor.wasted_bytes)} />
      <Row label={t('Time active')} value={duration(tor.elapsed_seconds)} />
      <Row label={t('Seeding time')} value={duration(tor.seeding_seconds)} />
      <Row label={t('Connections')} value={given(tor.connections)
        ? t('{n} of {max}', { n: tor.connections, max: tor.connections_limit })
        : null} />
      <Row label={t('Seeds')} value={given(tor.seeds)
        ? t('{n} connected of {total}', { n: tor.seeds, total: tor.seeds_total })
        : null} />
      <Row label={t('Leechers')} value={given(tor.leechers)
        ? t('{n} connected of {total}', { n: tor.leechers, total: tor.leechers_total })
        : null} />
      <Row label={t('Next announce')} value={duration(tor.reannounce_seconds)} />
      {seeding && (
        <Row label={t('Seeding requirement')} value={seeding.met ? t('Met') : seedingOwed(seeding)} wrap />
      )}
    </>
  )
}

function Pieces({ data }) {
  const tor = data.torrent || {}
  const pieces = data.pieces || {}
  const have = pieces.have || []
  const busy = pieces.busy || []
  if (!have.length) return <p className="ins-empty">{t('No pieces to show.')}</p>
  const per = pieces.count && pieces.count > have.length ? Math.round(pieces.count / have.length) : 1
  return (
    <>
      {tor.pieces_count ? (
        <p className="ins-lead">
          {t('{count} pieces of {size}, {have} have', {
            count: tor.pieces_count, size: formatBytes(tor.piece_size), have: tor.pieces_have || 0,
          })}
        </p>
      ) : null}
      <div className="ins-pieces">
        {have.map((value, i) => (
          <span key={i} className={`ins-piece ${busy[i] ? 'busy' : ''}`} style={{ background: shade(value) }} />
        ))}
      </div>
      <div className="ins-legend">
        <span><i style={{ background: shade(100) }} />{t('Have')}</span>
        <span><i style={{ background: shade(50) }} />{t('Partly')}</span>
        <span><i style={{ background: shade(0) }} />{t('Missing')}</span>
        <span><i className="busy" style={{ background: shade(0) }} />{t('Downloading now')}</span>
      </div>
      {per > 1 && <p className="ins-note">{t('Each square stands for about {n} pieces.', { n: per })}</p>}
    </>
  )
}

function Files({ data }) {
  const files = data.files || []
  if (!files.length) return <p className="ins-empty">{t('No files to show.')}</p>
  return (
    <div className="ins-files">
      {files.map((file, i) => {
        const skipped = file.priority === 0
        const progress = file.progress || 0
        return (
          <div key={`${file.name}-${i}`} className={`ins-file ${file.mine ? 'mine' : ''} ${skipped ? 'skipped' : ''}`}>
            <div className="ins-file-name">
              <span className="ins-file-text">{fileName(file.name)}</span>
              {file.mine && <span className="ins-tag">{t('This download')}</span>}
            </div>
            <div className="ins-file-line">
              {!skipped && (
                <div className="dl-bar"><span style={{ width: `${Math.max(0, Math.min(100, progress))}%` }} /></div>
              )}
              <span className="ins-file-size">
                {skipped
                  ? `${t('Skipped')} · ${formatBytes(file.size_bytes)}`
                  : t('{percent}% of {size}', { percent: progress.toFixed(progress < 100 ? 1 : 0), size: formatBytes(file.size_bytes) })}
              </span>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Peers({ data }) {
  const peers = data.peers || []
  if (!peers.length) return <p className="ins-empty">{t('No peers connected')}</p>
  return (
    <div className="ins-table">
      <div className="ins-tr head">
        <span className="c-addr">{t('Address')}</span>
        <span className="c-client">{t('Client')}</span>
        <span className="c-flags">{t('Flags')}</span>
        <span className="c-num">{t('Progress')}</span>
        <span className="c-num">↓</span>
        <span className="c-num">↑</span>
      </div>
      {peers.map((peer, i) => (
        <div className="ins-tr" key={`${peer.address}-${i}`}>
          <span className="c-addr">
            {peer.country_code && <em className="ins-cc">{String(peer.country_code).toUpperCase()}</em>}
            {peer.address}
          </span>
          <span className="c-client">{peer.client || ''}</span>
          <span className="c-flags">{peer.flags || ''}</span>
          <span className="c-num">{`${Math.round(peer.progress || 0)}%`}</span>
          <span className="c-num">{peer.dl_speed > 0 ? formatSpeed(peer.dl_speed) : ''}</span>
          <span className="c-num">{peer.up_speed > 0 ? formatSpeed(peer.up_speed) : ''}</span>
        </div>
      ))}
    </div>
  )
}

function Trackers({ data }) {
  const trackers = data.trackers || []
  if (!trackers.length) return <p className="ins-empty">{t('No trackers to show.')}</p>
  return (
    <div className="ins-trackers">
      {trackers.map((tracker, i) => {
        const numbers = [
          count(tracker.seeds) !== null ? `${t('Seeds')} ${tracker.seeds}` : null,
          count(tracker.leechers) !== null ? `${t('Leechers')} ${tracker.leechers}` : null,
          count(tracker.peers) !== null ? `${t('Peers')} ${tracker.peers}` : null,
          count(tracker.downloaded) !== null ? `${t('Downloaded')} ${tracker.downloaded}` : null,
        ].filter(Boolean)
        return (
          <div className="ins-tracker" key={`${tracker.host}-${i}`}>
            <div className="ins-tracker-head">
              <span className="ins-tracker-host">{tracker.host}</span>
              <span className={`ins-chip ${tracker.status === 'working' ? 'good' : ''} ${tracker.status === 'not working' ? 'bad' : ''}`}>
                {trackerStatus(tracker.status)}
              </span>
            </div>
            {numbers.length > 0 && <div className="ins-tracker-line">{numbers.join(' · ')}</div>}
            {tracker.message && <div className="ins-tracker-line dim">{tracker.message}</div>}
          </div>
        )
      })}
    </div>
  )
}

function preparationText(prep) {
  if (!prep) return null
  if (prep.error) return t('Failed: {error}', { error: prep.error })
  if (prep.ready) return t('Ready')
  const percent = Math.round(prep.percent || 0)
  return [prep.stage, percent ? `${percent}%` : null].filter(Boolean).join(' ') || t('Waiting')
}

function sourceText(library) {
  if (library.source_removed) return t('Removed. The title plays from what was built from it.')
  const size = formatBytes(library.source_bytes)
  return library.source_removable
    ? t('{size}, can be removed. The title keeps playing.', { size })
    : t('{size}, kept for now', { size })
}

function Information({ data }) {
  const release = data.release || {}
  const tor = data.torrent || {}
  const library = data.library || {}
  const job = data.job || {}
  const quality = [release.resolution, release.source, release.video_codec, release.audio_codec, release.hdr]
    .filter(Boolean).join(' · ')
  const flags = [release.freeleech ? t('Freeleech') : null, release.internal ? t('Internal') : null]
    .filter(Boolean).join(' · ')
  return (
    <>
      <h3 className="ins-sub">{t('Release')}</h3>
      <Row label={t('Name')} value={release.name || job.release} wrap />
      <Row label={t('Category')} value={release.category_name} />
      <Row label={t('Quality')} value={quality} />
      <Row label={t('Group')} value={release.release_group} />
      <Row label={t('Uploaded')} value={when(release.upload_date)} />
      <Row label={t('On the tracker')} value={given(release.seeders)
        ? t('{seeders} seeders, {leechers} leechers', { seeders: release.seeders, leechers: release.leechers || 0 })
        : null} />
      <Row label={t('Flags')} value={flags} />

      {data.live && (
        <>
          <h3 className="ins-sub">{t('Torrent')}</h3>
          <Row label={t('Name')} value={tor.name} wrap />
          <Row label={t('Info hash')} value={tor.info_hash} wrap />
          <Row label={t('Save path')} value={tor.save_path} wrap />
          <Row label={t('Content path')} value={tor.content_path} wrap />
          <Row label={t('Created by')} value={tor.created_by} />
          <Row label={t('Created')} value={when(tor.created_at)} />
          <Row label={t('Added')} value={when(tor.added_at)} />
          <Row label={t('Completed')} value={when(tor.completed_at)} />
          <Row label={t('Last seen complete')} value={when(tor.last_seen_complete)} />
        </>
      )}

      <h3 className="ins-sub">{t('Library')}</h3>
      <Row label={t('Requested')} value={when(job.requested_at || library.requested_at)} />
      <Row label={t('Library path')} value={library.library_path} wrap />
      <Row label={t('Asked for')} value={library.wanted && library.wanted.length ? library.wanted.join(', ') : null} wrap />
      <Row label={t('Preparation')} value={preparationText(library.preparation)} wrap />
      <Row label={t('Source')} value={given(library.source_removed) ? sourceText(library) : null} wrap />
    </>
  )
}

export default function JobInspector({ jobId, registerHandler, onClose, onNote }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [index, setIndex] = useState(0)
  const [pane, setPane] = useState('rail') // rail | content
  const [confirming, setConfirming] = useState(false)
  const [confirmChoice, setConfirmChoice] = useState('cancel')
  const [busy, setBusy] = useState(false)
  const bodyRef = useRef(null)

  const library = (data && data.library) || {}
  const job = data && data.job
  const entries = library.source_removable
    ? SECTIONS.concat([{ id: 'remove', icon: 'source-remove' }])
    : SECTIONS
  const entry = entries[Math.min(index, entries.length - 1)]

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

  useEffect(() => {
    setIndex((i) => Math.min(i, entries.length - 1))
  }, [entries.length])

  useEffect(() => {
    if (bodyRef.current) bodyRef.current.scrollTop = 0
    setPane('rail')
  }, [entry.id])

  const scrollable = () => {
    const body = bodyRef.current
    return Boolean(body && body.scrollHeight > body.clientHeight + 4)
  }

  const scrollBy = (delta) => {
    const body = bodyRef.current
    if (!body) return
    const max = body.scrollHeight - body.clientHeight
    setPageScroll(body, Math.max(0, Math.min(max, body.scrollTop + delta)), { animate: true })
  }

  const removeSource = useCallback(async () => {
    if (!job) return
    setBusy(true)
    try {
      // Before seeding is done the server requires an explicit override.
      await api.removeSource(job.download_id, !(job.seeding && job.seeding.met))
      onNote(t('Removed the source of {title}', { title: job.title }))
      setConfirming(false)
      await load()
    } catch (e) {
      onNote(t('Could not remove it: {error}', { error: errorText(e) }))
    } finally {
      setBusy(false)
    }
  }, [job, load, onNote])

  useEffect(() => {
    registerHandler({
      onDirection: (dir) => {
        if (confirming) {
          if (dir === 'left' || dir === 'right') setConfirmChoice((c) => (c === 'cancel' ? 'remove' : 'cancel'))
          return
        }
        if (pane === 'content') {
          if (dir === 'up') scrollBy(-SCROLL_STEP)
          if (dir === 'down') scrollBy(SCROLL_STEP)
          if (dir === 'left') setPane('rail')
          return
        }
        if (dir === 'up') setIndex((i) => Math.max(0, i - 1))
        if (dir === 'down') setIndex((i) => Math.min(entries.length - 1, i + 1))
        if (dir === 'right' && scrollable()) setPane('content')
      },
      onEnter: () => {
        if (confirming) {
          if (confirmChoice === 'remove' && !busy) removeSource()
          else setConfirming(false)
          return
        }
        if (entry.id === 'remove') {
          setConfirming(true)
          setConfirmChoice('cancel')
        } else if (pane === 'rail' && scrollable()) setPane('content')
      },
      onBack: () => {
        if (confirming) setConfirming(false)
        else if (pane === 'content') setPane('rail')
        else onClose()
        return true
      },
    })
  }, [registerHandler, confirming, confirmChoice, busy, pane, entry, entries.length, removeSource, onClose])

  const art = job ? jobArt(job) : null
  const status = job ? jobStatus(job) : null
  const seeding = job && job.seeding
  const stillOwed = seeding && !seeding.met

  let content = null
  if (data) {
    const live = data.live
    if (entry.id === 'activity') content = live ? <Activity data={data} /> : null
    else if (entry.id === 'pieces') content = live ? <Pieces data={data} /> : null
    else if (entry.id === 'files') content = live ? <Files data={data} /> : null
    else if (entry.id === 'peers') content = live ? <Peers data={data} /> : null
    else if (entry.id === 'trackers') content = live ? <Trackers data={data} /> : null
    else if (entry.id === 'info') content = <Information data={data} />
    else if (entry.id === 'remove') {
      content = (
        <>
          <p className="ins-lead">
            {t('Removes the downloaded copy, {size}. The title keeps playing from what was built from it.',
              { size: formatBytes(library.source_bytes) })}
          </p>
          {job && job.shares_torrent && <p className="ins-lead">{t('Every download from this torrent loses it.')}</p>}
          {stillOwed && (
            <p className="ins-lead warn">{`${seedingOwed(seeding)} ${t('Removing it now counts as a hit and run on filelist.')}`}</p>
          )}
          <p className="debug-result">{t('Press OK to do it.')}</p>
        </>
      )
    }
  }
  const counts = data ? {
    files: (data.files || []).length,
    peers: (data.peers || []).length,
    trackers: (data.trackers || []).length,
  } : {}

  return (
    <div className="dl-inspect">
      <button className="back-btn" onClick={onClose} title={t('Back')} aria-label={t('Back')}>
        <BackIcon size={26} />
      </button>
      <div className="ins-side">
        {job && (
          <div className="ins-head">
            <div className={`ins-art ${art.wide ? 'wide' : ''}`}>{art.src ? <img src={art.src} alt="" /> : null}</div>
            <div className="ins-head-text">
              <div className="ins-title">{job.title}</div>
              {jobSubtitle(job) && <div className="ins-head-sub">{jobSubtitle(job)}</div>}
              <div className={`dl-entry-state ${status.tone}`}>
                {status.failed && <span className="fail-badge small">!</span>}
                {status.text}
              </div>
            </div>
          </div>
        )}
        {!job && <div className="ins-head-sub">{error || t('Loading...')}</div>}
        <div className="ins-menu">
          {entries.map((item, i) => (
            <div
              key={item.id}
              className={[
                'menu-item',
                'with-icon',
                item.id === 'remove' ? 'danger group-start' : '',
                i === index && pane === 'rail' && !confirming ? 'focused' : '',
                i === index && (pane === 'content' || confirming) ? 'active' : '',
              ].join(' ')}
              onMouseEnter={() => {
                setIndex(i)
                setPane('rail')
              }}
              onClick={() => {
                setIndex(i)
                if (item.id === 'remove') {
                  setConfirming(true)
                  setConfirmChoice('cancel')
                }
              }}
            >
              <Icon name={item.icon} size={24} />
              <span className="ins-menu-label">{sectionLabel(item.id)}</span>
              {counts[item.id] ? <span className="menu-aside">{counts[item.id]}</span> : null}
            </div>
          ))}
        </div>
      </div>

      <div className={`ins-body ${pane === 'content' ? 'focused' : ''}`} ref={bodyRef}>
        <h2>{sectionLabel(entry.id)}</h2>
        {data && !data.live && entry.id !== 'info' && entry.id !== 'remove' && (
          <p className="ins-empty">{t('qBittorrent is not answering, so there is nothing live to show.')}</p>
        )}
        {error && data && <p className="ins-note">{error}</p>}
        {content}
        <div className="list-spacer small" />
      </div>

      {confirming && job && (
        <div className="scrim">
          <div className="dialog">
            <h2>{t('Remove the source of {title}?', { title: job.title })}</h2>
            <p>
              {t('Removes the downloaded copy, {size}. The title keeps playing from what was built from it.',
                { size: formatBytes(library.source_bytes) })}
              {job.shares_torrent ? ` ${t('Every download from this torrent loses it.')}` : ''}
            </p>
            {stillOwed && (
              <p className="dialog-warn">{`${seedingOwed(seeding)} ${t('Removing it now counts as a hit and run on filelist.')}`}</p>
            )}
            <div className="dialog-actions">
              <div className={`pill-btn ${confirmChoice === 'cancel' ? 'focused' : ''}`}
                onMouseEnter={() => setConfirmChoice('cancel')} onClick={() => setConfirming(false)}>
                {t('Keep it')}
              </div>
              <div className={`pill-btn danger ${confirmChoice === 'remove' ? 'focused' : ''}`}
                onMouseEnter={() => setConfirmChoice('remove')} onClick={() => { if (!busy) removeSource() }}>
                {busy ? t('Removing...') : t('Remove')}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function withRaw(words, raw) {
  return words.toLowerCase() === raw.toLowerCase() ? words : `${words} (${raw})`
}
