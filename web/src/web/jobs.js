import { formatBytes, formatEta, formatSpeed } from '../api'

export function jobArt(job) {
  if (job.kind === 'episode') {
    const still = job.episode?.still || job.backdrop
    if (still) return { src: still, wide: true }
  }
  return { src: job.poster, wide: false }
}

/** "S1:E3 · Pilot", "Season 1", or the year of a film. */
export function jobSubtitle(job) {
  if (job.kind === 'episode') return [job.label, job.episode?.name].filter(Boolean).join(' · ')
  if (job.label) return job.label
  return job.year ? String(job.year) : ''
}

/** The state in words, its tone, and its bar fill (null when there is no bar). */
export function jobStatus(job) {
  const percent = job.percent || 0
  if (job.state === 'downloading') {
    if (percent < 1) return { text: 'Downloading', tone: 'working', bar: 0 }
    const parts = [`Downloading ${Math.round(percent)}%`]
    if (job.dl_speed > 0) parts.push(formatSpeed(job.dl_speed))
    if (job.eta_seconds > 0) parts.push(`${formatEta(job.eta_seconds)} left`)
    return { text: parts.join(' · '), tone: 'working', bar: percent }
  }
  if (job.state === 'preparing') {
    const prepared = job.prepare_percent || 0
    return { text: prepared >= 1 ? `Preparing ${Math.round(prepared)}%` : 'Preparing', tone: 'working', bar: prepared }
  }
  if (job.state === 'ready') return { text: 'Ready', tone: 'ready', bar: null }
  if (job.state === 'failed') return { text: job.error_message || 'Failed', tone: 'error', bar: null, failed: true }
  if (job.state === 'paused') return { text: 'Paused', tone: 'faint', bar: null }
  return { text: 'Queued', tone: 'faint', bar: null }
}

export function seedingOwed(seeding) {
  return `It has seeded ${Number(seeding.hours || 0).toFixed(1)}h of ${seeding.min_hours}h and reached ratio `
    + `${Number(seeding.ratio || 0).toFixed(2)} of ${Number(seeding.min_ratio || 0).toFixed(1)}.`
}

/* Deleting the last job on a torrent removes the torrent; a film or season always does, with any job sharing it. */
export function deleteExplanation(job) {
  const size = formatBytes(job.size_bytes)
  if (job.kind === 'episode') {
    return job.shares_torrent
      ? 'Removes the episode from the server and from your library. The rest of the season stays.'
      : `Removes the episode and its torrent from the server, and takes it out of your library. ${size} comes back.`
  }
  const text = `Removes the torrent and its files from the server, and takes it out of your library. ${size} comes back.`
  return job.shares_torrent ? `${text} Other downloads from the same torrent go with it.` : text
}

/* Shared torrents survive the delete, so the tracker does not count it. */
export function hitAndRun(job) {
  if (!job.seeding || job.seeding.met || job.shares_torrent) return null
  return `${seedingOwed(job.seeding)} Deleting now counts as a hit and run on filelist.`
}

const TORRENT_STATES = {
  downloading: 'Downloading', forcedDL: 'Downloading', stalledDL: 'Stalled',
  metaDL: 'Fetching metadata', forcedMetaDL: 'Fetching metadata',
  queuedDL: 'Queued', queuedUP: 'Queued', pausedDL: 'Paused', stoppedDL: 'Paused',
  uploading: 'Seeding', forcedUP: 'Seeding', stalledUP: 'Seeding',
  pausedUP: 'Finished', stoppedUP: 'Finished',
  checkingDL: 'Checking', checkingUP: 'Checking', checkingResumeData: 'Checking',
  allocating: 'Allocating', moving: 'Moving', missingFiles: 'Files missing', error: 'Error',
}

export const torrentState = (raw) => TORRENT_STATES[raw] || raw

export function when(value) {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  return date.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}
