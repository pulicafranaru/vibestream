import { formatBytes, formatEta, formatSpeed } from '../api'
import { getLanguage, t } from '../shared/i18n'
import { tilePoster } from './images'

// How a download job is described, shared by the list and the inspector.

export function jobArt(job) {
  if (job.kind === 'episode') {
    const still = (job.episode && job.episode.still) || job.backdrop
    if (still) return { src: still, wide: true }
  }
  return { src: job.poster ? tilePoster(job.poster) : null, wide: false }
}

// The server words season labels in English.
function seasonLabel(label) {
  let match = /^Season (\d+)$/.exec(label)
  if (match) return t('Season {n}', { n: match[1] })
  match = /^Seasons (\d+) to (\d+)$/.exec(label)
  if (match) return t('Seasons {from} to {to}', { from: match[1], to: match[2] })
  return label
}

export function jobSubtitle(job) {
  if (job.kind === 'episode') {
    return [job.label, job.episode && job.episode.name].filter(Boolean).join(' · ')
  }
  if (job.label) return seasonLabel(job.label)
  return job.year ? String(job.year) : ''
}

export function jobStatus(job) {
  const percent = job.percent || 0
  if (job.state === 'downloading') {
    if (percent < 1) return { text: t('Downloading'), tone: 'working', bar: 0 }
    const parts = [t('Downloading {n}%', { n: Math.round(percent) })]
    if (job.dl_speed > 0) parts.push(formatSpeed(job.dl_speed))
    if (job.eta_seconds > 0) parts.push(t('{time} left', { time: formatEta(job.eta_seconds) }))
    return { text: parts.join(' · '), tone: 'working', bar: percent }
  }
  if (job.state === 'preparing') {
    const prepared = job.prepare_percent || 0
    return {
      text: prepared >= 1 ? t('Preparing {n}%', { n: Math.round(prepared) }) : t('Preparing'),
      tone: 'working',
      bar: prepared,
    }
  }
  if (job.state === 'ready') return { text: t('Ready'), tone: 'ready', bar: null }
  if (job.state === 'failed') return { text: job.error_message || t('Failed'), tone: 'error', bar: null, failed: true }
  if (job.state === 'paused') return { text: t('Paused'), tone: '', bar: null }
  return { text: t('Queued'), tone: '', bar: null }
}

export function seedingOwed(seeding) {
  return t('It has seeded {hours}h of {min}h and reached ratio {ratio} of {target}.', {
    hours: Number(seeding.hours || 0).toFixed(1),
    min: seeding.min_hours,
    ratio: Number(seeding.ratio || 0).toFixed(2),
    target: Number(seeding.min_ratio || 0).toFixed(1),
  })
}

export function deleteQuestion(job) {
  return job.kind === 'episode' && job.label
    ? t('Delete {label} of {title}?', { label: job.label, title: job.title })
    : t('Delete {title}?', { title: job.title })
}

export function deleteExplanation(job) {
  const size = formatBytes(job.size_bytes)
  if (job.kind === 'episode') {
    return job.shares_torrent
      ? t('This removes the episode from the server and from your library. The rest of the season stays.')
      : t('This removes the episode and its torrent from the server, and takes it out of your library. {size} comes back.', { size })
  }
  const text = t('This removes the torrent and its files from the server, and takes it out of your library. {size} comes back.', { size })
  return job.shares_torrent ? `${text} ${t('Other downloads from the same torrent go with it.')}` : text
}

// The tracker counts a hit and run only when the torrent itself is removed.
export function hitAndRun(job) {
  if (!job.seeding || job.seeding.met || job.shares_torrent) return null
  return `${seedingOwed(job.seeding)} ${t('Deleting now counts as a hit and run on filelist.')}`
}

export function torrentState(raw) {
  const names = {
    downloading: t('Downloading'), forcedDL: t('Downloading'), stalledDL: t('Stalled'),
    metaDL: t('Fetching metadata'), forcedMetaDL: t('Fetching metadata'),
    queuedDL: t('Queued'), queuedUP: t('Queued'), pausedDL: t('Paused'), stoppedDL: t('Paused'),
    uploading: t('Seeding'), forcedUP: t('Seeding'), stalledUP: t('Seeding'),
    pausedUP: t('Finished'), stoppedUP: t('Finished'),
    checkingDL: t('Checking'), checkingUP: t('Checking'), checkingResumeData: t('Checking'),
    allocating: t('Allocating'), moving: t('Moving'), missingFiles: t('Files missing'), error: t('Error'),
  }
  return names[raw] || raw
}

export function trackerStatus(raw) {
  const names = {
    working: t('Working'), 'not contacted': t('Not contacted'), disabled: t('Disabled'),
    updating: t('Updating'), 'not working': t('Not working'),
  }
  return names[raw] || raw
}

export function when(value) {
  if (!value) return null
  const date = new Date(value)
  if (isNaN(date.getTime())) return null
  const locale = { en: 'en-GB', de: 'de-DE', ro: 'ro-RO' }[getLanguage()]
  try {
    return date.toLocaleString(locale, {
      day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return date.toString()
  }
}
