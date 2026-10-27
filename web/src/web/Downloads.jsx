import { useCallback, useEffect, useState } from 'react'
import { api, errorText, formatBytes, formatSpeed } from '../api'
import ProgressRing from '../shared/ProgressRing'
import { Icon, PlayIcon, TrashIcon } from '../shared/icons'
import { DownloadsSkeleton } from './Skeleton'
import JobInspector from './JobInspector'
import { deleteExplanation, hitAndRun, jobArt, jobStatus, jobSubtitle } from './jobs'

export default function Downloads({ shell, onPlay }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(null)
  const [inspecting, setInspecting] = useState(null)

  const load = useCallback(async () => {
    try {
      setData(await api.downloadJobs())
      setError(null)
    } catch (e) {
      setError(errorText(e))
    }
  }, [])

  useEffect(() => {
    let alive = true
    let timer = null
    const tick = async () => {
      if (!alive) return
      await load()
      if (alive) timer = setTimeout(tick, 3000)
    }
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [load])

  const remove = async (job) => {
    setPending(null)
    if (inspecting === job.job_id) setInspecting(null)
    // A toast, not the page's note: the reload below would clear that unseen.
    await api.deleteJob(job.job_id).catch((e) => shell.showError(errorText(e)))
    await load()
    await shell.refreshDownloads()
  }

  // The server restarts an existing job for the same request rather than adding another.
  const retry = async (job) => {
    const options = job.kind === 'episode' && job.episode ? { episode: job.episode.id } : {}
    await shell.startDownload(job.torrent_id, options)
    await load()
  }

  const [freeing, setFreeing] = useState(false)
  const removeFinished = async () => {
    setFreeing(true)
    await api.removeFinishedSources().catch((e) => shell.showError(errorText(e)))
    await load()
    setFreeing(false)
  }

  const totals = data?.totals
  const space = data?.space
  const items = data?.items || []
  const seeded = space?.removable_seeded

  return (
    <div className="page">
      <h1 className="page-title">My Downloads</h1>

      {totals && (
        <div className="totals">
          <Stat label="downloads" value={items.length} />
          {totals.torrent_bytes != null ? (
            <>
              <Stat label="torrent files" value={formatBytes(totals.torrent_bytes)} />
              <Stat label="playback files" value={formatBytes(totals.playback_bytes)} />
            </>
          ) : (
            <Stat label="on disk" value={formatBytes(totals.size_bytes)} />
          )}
          <Stat label="shared" value={formatBytes(totals.uploaded_bytes)} />
          <Stat label="free" value={formatBytes(totals.free_bytes)} />
          {totals.dl_speed > 0 && <Stat label="downloading" value={formatSpeed(totals.dl_speed)} />}
          {totals.up_speed > 0 && <Stat label="uploading" value={formatSpeed(totals.up_speed)} />}
        </div>
      )}

      {space && (space.low || seeded?.count > 0) && (
        <div className={`space-bar ${space.low ? 'low' : ''}`}>
          <span>
            {space.low && (
              <>Running out of space: <strong>{formatBytes(space.free_bytes)}</strong> free</>
            )}
            {space.low && seeded?.count > 0 && '  ·  '}
            {seeded?.count > 0 && (
              <>
                <strong>{formatBytes(seeded.bytes)}</strong> more from {seeded.count} finished
                source{seeded.count === 1 ? '' : 's'}
              </>
            )}
          </span>
          {seeded?.count > 0 && (
            <button className="btn small" onClick={removeFinished} disabled={freeing}
              title="Removes the downloaded copies that have finished seeding. The titles keep playing.">
              {freeing ? <ProgressRing size={14} stroke={2} indeterminate /> : null}
              Free {formatBytes(seeded.bytes)}
            </button>
          )}
        </div>
      )}

      {data && !data.live && (
        <p className="note">qBittorrent is not answering, so speeds are the last known values.</p>
      )}
      {error && <p className="note error">{error}</p>}
      {!data && !error && <DownloadsSkeleton />}

      {data && !items.length && <p className="note">Nothing downloaded yet.</p>}

      {items.length > 0 && (
        <table className="dl-table jobs">
          <thead>
            <tr>
              <th className="art" />
              <th>Title</th>
              <th className="num">Size</th>
              <th className="actions" />
            </tr>
          </thead>
          <tbody>
            {items.map((job) => {
              const art = jobArt(job)
              const status = jobStatus(job)
              const subtitle = jobSubtitle(job)
              const warning = hitAndRun(job)
              return (
                <tr key={job.job_id} className="dl-job" onClick={() => setInspecting(job.job_id)}>
                  <td className="art">
                    <div className={`dl-art ${art.wide ? 'wide' : ''}`}>
                      {art.src && <img src={art.src} alt="" loading="lazy" />}
                    </div>
                  </td>
                  <td className="dl-main">
                    <div className="dl-title">
                      {job.title}
                      {subtitle && <span className="dl-sub">{subtitle}</span>}
                    </div>
                    <JobState status={status} />
                    {status.bar !== null && (
                      <div className="dl-progress"><span style={{ width: `${Math.max(1, Math.min(100, status.bar))}%` }} /></div>
                    )}
                  </td>
                  <td className="num">{job.size_bytes ? formatBytes(job.size_bytes) : ''}</td>
                  <td className="actions" onClick={(e) => e.stopPropagation()}>
                    <div className="row-actions">
                      {pending === job.job_id ? (
                        <>
                          {warning && (
                            <span className="row-warn" title={warning}>Still seeding. Hit and run?</span>
                          )}
                          {!warning && job.kind !== 'episode' && job.shares_torrent && (
                            <span className="row-warn">Its torrent&apos;s other downloads go too.</span>
                          )}
                          <button className="btn small danger" onClick={() => remove(job)}
                            title={deleteExplanation(job)}>
                            Delete
                          </button>
                          <button className="btn small" onClick={() => setPending(null)}>
                            Keep
                          </button>
                        </>
                      ) : (
                        <>
                          {job.play_id && (
                            <button
                              className="row-icon"
                              onClick={() => onPlay(job.play_id)}
                              title="Play"
                              aria-label={`Play ${job.title}`}
                            >
                              <PlayIcon size={16} />
                            </button>
                          )}
                          {job.state === 'failed' && (
                            <button
                              className="row-icon"
                              onClick={() => retry(job)}
                              title="Try again"
                              aria-label={`Try ${job.title} again`}
                            >
                              <Icon name="replay" size={16} />
                            </button>
                          )}
                          <button
                            className="row-icon"
                            onClick={() => setInspecting(job.job_id)}
                            title="Details"
                            aria-label={`Details of ${job.title}`}
                          >
                            <Icon name="info" size={16} />
                          </button>
                          <button
                            className="row-icon"
                            onClick={() => setPending(job.job_id)}
                            title="Delete"
                            aria-label={`Delete ${job.title}`}
                          >
                            <TrashIcon size={16} />
                          </button>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}

      {items.some((i) => i.seeding) && (
        <p className="note">
          Seeding obligations come from the tracker: a torrent stays until it has
          seeded long enough or reached ratio 1.0. Deleting early is a hit and run.
        </p>
      )}

      {inspecting !== null && (
        <JobInspector
          jobId={inspecting}
          onClose={() => setInspecting(null)}
          onChanged={load}
          onPlay={onPlay}
        />
      )}
    </div>
  )
}

export function JobState({ status }) {
  return (
    <div className={`dl-state job ${status.tone}`}>
      {status.failed ? <span className="fail-badge">!</span> : <i className="dot" />}
      <span>{status.text}</span>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <strong>{value}</strong>
      <span>{label}</span>
    </div>
  )
}
