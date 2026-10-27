import { useCallback, useEffect, useRef, useState } from 'react'
import { api, errorText, formatBytes, formatEta, formatSpeed } from '../api'
import { Icon, PlayIcon, TrashIcon } from './icons'
import { t } from '../shared/i18n'
import { clamp } from './navigation'
import JobInspector from './JobInspector'
import {
  deleteExplanation, deleteQuestion, hitAndRun, jobArt, jobStatus, jobSubtitle, when,
} from './jobs'

const REFRESH_MS = 3000

function actionsFor(job) {
  const list = []
  if (job.play_id) list.push('play')
  if (job.state === 'failed') list.push('retry')
  list.push('details', 'delete')
  return list
}

const ACTION_LABELS = {
  play: () => t('Play'),
  retry: () => t('Try again'),
  details: () => t('Details'),
  delete: () => t('Delete'),
}

const ACTION_ICONS = {
  play: <PlayIcon size={28} />,
  retry: <Icon name="replay" size={28} />,
  details: <Icon name="info" size={28} />,
  delete: <TrashIcon size={28} />,
}

function Stat({ label, value, tone }) {
  if (value === null || value === undefined || value === '') return null
  return (
    <div className={`fact compact ${tone || ''}`}>
      <div className="fact-label">{label}</div>
      <div className="fact-value">{value}</div>
    </div>
  )
}

function Bar({ percent, big }) {
  return (
    <div className={`dl-bar ${big ? 'big' : ''}`}>
      <span style={{ width: `${Math.max(1, Math.min(100, percent || 0))}%` }} />
    </div>
  )
}

export default function Downloads({ onClose, onPlay, registerHandler }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [sel, setSel] = useState(0)
  const [pane, setPane] = useState('list') // list | actions
  const [action, setAction] = useState(0)
  const [confirming, setConfirming] = useState(null)
  const [confirmChoice, setConfirmChoice] = useState('cancel')
  const [inspecting, setInspecting] = useState(null)
  const [busy, setBusy] = useState(false)
  const [note, setNote] = useState(null)
  const listRef = useRef(null)
  const rowRefs = useRef({})

  const items = (data && data.items) || []
  const totals = data && data.totals
  const job = items[sel]
  const acts = job ? actionsFor(job) : []

  // The poll and the reload after a removal overlap; only the newest answers.
  const loadSeq = useRef(0)
  const load = useCallback(async () => {
    const seq = ++loadSeq.current
    try {
      const fresh = await api.downloadJobs()
      if (seq !== loadSeq.current) return
      setData(fresh)
      setError(null)
    } catch (e) {
      if (seq === loadSeq.current) setError(errorText(e))
    }
  }, [])

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
    setSel((s) => {
      const next = clamp(s, items.length)
      return next === null ? 0 : next
    })
  }, [items.length])

  useEffect(() => {
    setAction(0)
  }, [sel])

  useEffect(() => {
    setAction((a) => Math.min(a, Math.max(0, acts.length - 1)))
  }, [acts.length])

  useEffect(() => {
    const list = listRef.current
    const el = rowRefs.current[sel]
    if (!list || !el) return
    if (el.offsetTop < list.scrollTop + 12) list.scrollTop = Math.max(0, el.offsetTop - 12)
    else if (el.offsetTop + el.offsetHeight > list.scrollTop + list.clientHeight - 12) {
      list.scrollTop = el.offsetTop + el.offsetHeight - list.clientHeight + 12
    }
  }, [sel, items.length])

  useEffect(() => {
    if (!note) return undefined
    const timer = setTimeout(() => setNote(null), 4000)
    return () => clearTimeout(timer)
  }, [note])

  const remove = useCallback(async (target) => {
    setBusy(true)
    try {
      await api.deleteJob(target.job_id)
      setNote(target.kind === 'episode' && target.label
        ? t('Removed {label} of {title}', { label: target.label, title: target.title })
        : t('Removed {title}', { title: target.title }))
      setConfirming(null)
      setPane('list')
      await load()
    } catch (e) {
      setNote(t('Could not remove it: {error}', { error: errorText(e) }))
    } finally {
      setBusy(false)
    }
  }, [load])

  // The server finds an existing job for the same request and restarts it.
  const retry = useCallback(async (target) => {
    setBusy(true)
    try {
      const options = target.kind === 'episode' && target.episode ? { episode: target.episode.id } : {}
      await api.startDownload(target.torrent_id, options)
      setNote(t('Preparing {title} again', { title: target.title }))
      await load()
    } catch (e) {
      setNote(t('Could not retry: {error}', { error: errorText(e) }))
    } finally {
      setBusy(false)
    }
  }, [load])

  const run = useCallback((target, name) => {
    if (!target) return
    if (name === 'play') onPlay(target)
    else if (name === 'retry') {
      if (!busy) retry(target)
    } else if (name === 'details') setInspecting(target.job_id)
    else if (name === 'delete') {
      setConfirming(target)
      setConfirmChoice('cancel')
    }
  }, [onPlay, retry, busy])

  // The inspector owns the remote while open; `inspecting` changing re-registers this handler.
  useEffect(() => {
    if (inspecting !== null) return
    registerHandler({
      onDirection: (dir) => {
        if (confirming) {
          if (dir === 'left' || dir === 'right') setConfirmChoice((c) => (c === 'cancel' ? 'delete' : 'cancel'))
          return
        }
        if (pane === 'actions') {
          if (dir === 'up') setAction((a) => Math.max(0, a - 1))
          if (dir === 'down') setAction((a) => Math.min(acts.length - 1, a + 1))
          if (dir === 'left') setPane('list')
          return
        }
        if (dir === 'up') setSel((s) => Math.max(0, s - 1))
        if (dir === 'down') setSel((s) => Math.min(items.length - 1, s + 1))
        if (dir === 'right' && job) setPane('actions')
      },
      onEnter: () => {
        if (confirming) {
          if (confirmChoice === 'delete' && !busy) remove(confirming)
          else setConfirming(null)
          return
        }
        if (pane === 'list') {
          if (job) setPane('actions')
          return
        }
        run(job, acts[action])
      },
      onBack: () => {
        if (confirming) setConfirming(null)
        else if (pane === 'actions') setPane('list')
        else onClose()
        return true
      },
    })
  }, [registerHandler, items, job, acts, pane, action, confirming, confirmChoice, busy, inspecting,
    onClose, remove, run])

  const status = job ? jobStatus(job) : null
  const owed = job && job.seeding && !job.seeding.met

  return (
    <div className="downloads">
      <div className="dl-side">
        <h1>
          <Icon name="download" size={36} />
          {t('Downloads')}
        </h1>
        {totals && (
          <div className="dl-totals">
            {formatBytes(totals.size_bytes)} {t('on disk')}
            {totals.free_bytes ? ` · ${formatBytes(totals.free_bytes)} ${t('free')}` : ''}
            {totals.dl_speed > 0 ? ` · ${t('down')} ${formatSpeed(totals.dl_speed)}` : ''}
            {totals.up_speed > 0 ? ` · ${t('up')} ${formatSpeed(totals.up_speed)}` : ''}
          </div>
        )}
        {totals && (totals.torrent_bytes !== undefined) && (
          <div className="dl-totals dim">
            {t('Torrent files')} {formatBytes(totals.torrent_bytes)} · {t('Playback files')} {formatBytes(totals.playback_bytes)}
          </div>
        )}
        {data && !data.live && (
          <div className="dl-warn">{t('qBittorrent is not answering, so speeds and peers are the last known values.')}</div>
        )}
        <div className="dl-list" ref={listRef}>
          {error && !data && <div className="empty-note">{error}</div>}
          {data && items.length === 0 && (
            <div className="empty-note">{t('Nothing downloaded yet. Pick a title and choose Download.')}</div>
          )}
          {items.map((entry, index) => {
            const art = jobArt(entry)
            const state = jobStatus(entry)
            return (
              <div
                key={entry.job_id}
                ref={(el) => { rowRefs.current[index] = el }}
                className={[
                  'dl-entry',
                  index === sel ? 'current' : '',
                  index === sel && pane === 'list' ? 'focused' : '',
                ].join(' ')}
                onMouseEnter={() => {
                  setSel(index)
                  setPane('list')
                }}
                onClick={() => setPane('actions')}
              >
                <div className="dl-entry-art">
                  <div className={`dl-entry-poster ${art.wide ? 'wide' : ''}`}>
                    {art.src ? <img src={art.src} alt="" /> : null}
                  </div>
                </div>
                <div className="dl-entry-body">
                  <div className="dl-entry-title">{entry.title}</div>
                  {jobSubtitle(entry) && <div className="dl-entry-sub">{jobSubtitle(entry)}</div>}
                  <div className={`dl-entry-state ${state.tone}`}>
                    {state.failed && <span className="fail-badge small">!</span>}
                    {state.text}
                  </div>
                  {state.bar !== null && <Bar percent={state.bar} />}
                </div>
              </div>
            )
          })}
          <div className="list-spacer small" />
        </div>
      </div>

      <div className="dl-detail">
        {job && (
          <>
            <h2 className="dl-detail-title">
              {job.title}
              {job.year && <span className="dl-year">{job.year}</span>}
            </h2>
            {job.kind !== 'title' && jobSubtitle(job) && <div className="dl-detail-sub">{jobSubtitle(job)}</div>}
            {job.release && <div className="dl-release">{job.release}</div>}
            <div className={`dl-detail-state ${status.tone}`}>
              {status.failed && <span className="fail-badge small">!</span>}
              {status.text}
            </div>
            {status.bar !== null && <Bar percent={status.bar} big />}
            <div className="dl-stats">
              <Stat label={t('size')} value={job.size_bytes ? formatBytes(job.size_bytes) : null} />
              {job.state === 'downloading' && <Stat label={t('done')} value={`${Math.round(job.percent || 0)}%`} />}
              {job.dl_speed > 0 && <Stat label={t('down')} value={formatSpeed(job.dl_speed)} />}
              {job.state === 'downloading' && job.eta_seconds ? <Stat label={t('left')} value={formatEta(job.eta_seconds)} /> : null}
              {job.seeding && <Stat label={t('ratio')} value={Number(job.seeding.ratio || 0).toFixed(2)} />}
              {job.seeding && <Stat label={t('seeded')} value={`${Number(job.seeding.hours || 0).toFixed(1)}h`} />}
              <Stat label={t('requested')} value={when(job.requested_at)} />
            </div>
            {owed && (
              <div className="dl-obligation">
                {t('Tracker: seed {hours}h or reach ratio {ratio}', {
                  hours: job.seeding.min_hours, ratio: Number(job.seeding.min_ratio).toFixed(1),
                })}
              </div>
            )}
            <div className="action-list">
              {acts.map((name, i) => (
                <div
                  key={name}
                  className={['action', name === 'delete' ? 'danger' : '', pane === 'actions' && action === i ? 'focused' : ''].join(' ')}
                  onMouseEnter={() => {
                    setPane('actions')
                    setAction(i)
                  }}
                  onClick={() => run(job, name)}
                >
                  {ACTION_ICONS[name]}
                  <span className="action-label">{ACTION_LABELS[name]()}</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {inspecting !== null && (
        <JobInspector
          jobId={inspecting}
          registerHandler={registerHandler}
          onNote={setNote}
          onClose={() => {
            setInspecting(null)
            load()
          }}
        />
      )}

      {confirming && (
        <div className="scrim">
          <div className="dialog">
            <h2>{deleteQuestion(confirming)}</h2>
            <p>{deleteExplanation(confirming)}</p>
            {hitAndRun(confirming) && <p className="dialog-warn">{hitAndRun(confirming)}</p>}
            <div className="dialog-actions">
              <div className={`pill-btn ${confirmChoice === 'cancel' ? 'focused' : ''}`}
                onMouseEnter={() => setConfirmChoice('cancel')} onClick={() => setConfirming(null)}>
                {t('Keep it')}
              </div>
              <div className={`pill-btn danger ${confirmChoice === 'delete' ? 'focused' : ''}`}
                onMouseEnter={() => setConfirmChoice('delete')} onClick={() => remove(confirming)}>
                {busy ? t('Deleting...') : t('Delete')}
              </div>
            </div>
          </div>
        </div>
      )}

      {note && <div className="toast" onClick={() => setNote(null)}>{note}</div>}
    </div>
  )
}
