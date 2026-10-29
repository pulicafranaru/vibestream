// The active profile travels as a header so it stays out of the HLS playlist
// and segment URLs, which ffmpeg generates and the server rewrites.
let activeProfileId = null

export function setActiveProfile(id) {
  activeProfileId = id || null
}

export function activeProfile() {
  return activeProfileId
}

const withProfile = (init = {}) => {
  if (!activeProfileId) return init
  return {
    ...init,
    headers: { ...(init.headers || {}), 'X-VibeStream-Profile': String(activeProfileId) },
  }
}

const json = async (res) => {
  if (!res.ok) {
    let detail = res.statusText
    let body = null
    try {
      body = await res.json()
      detail = body.detail || detail
    } catch {
      /* keep statusText */
    }
    // status and body stay on the error: a 507 from Download says what removing
    // finished sources would free.
    const error = new Error(`${res.status}: ${detail}`)
    error.status = res.status
    error.body = body
    error.detail = typeof detail === 'string' ? detail : null
    throw error
  }
  return res.json()
}

/** The server's message without the status code that `message` carries. */
export function errorText(error) {
  if (!error) return ''
  return error.detail || error.message || ''
}

const pinHeader = (pin) => (pin ? { 'X-Profile-Pin': pin } : {})

const qs = (params) => {
  const search = new URLSearchParams()
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      search.set(key, value)
    }
  })
  const str = search.toString()
  return str ? `?${str}` : ''
}

export const api = {
  profiles: () => fetch('/api/profiles').then(json),
  createProfile: (name, avatar, language, isKids) =>
    fetch(`/api/profiles${qs({ name, avatar, language, is_kids: isKids })}`, { method: 'POST' }).then(json),
  // Changing or deleting a locked profile requires its PIN.
  updateProfile: (id, fields, pin) =>
    fetch(`/api/profiles/${id}${qs(fields)}`, { method: 'PATCH', headers: pinHeader(pin) }).then(json),
  deleteProfile: (id, pin) =>
    fetch(`/api/profiles/${id}`, { method: 'DELETE', headers: pinHeader(pin) }).then(json),
  // checkPin: 403 wrong, 429 too many tries. setPin(id, null, current) removes it.
  checkPin: (id, pin) =>
    fetch(`/api/profiles/${id}/pin/check`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }),
    }).then(json),
  setPin: (id, pin, current) =>
    fetch(`/api/profiles/${id}/pin`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json', ...pinHeader(current) }, body: JSON.stringify({ pin, current }),
    }).then(json),
  useProfile: (id) => fetch(`/api/profiles/${id}/use`, { method: 'POST' }).then(json),

  myList: (profileId) => fetch(`/api/profiles/${profileId}/my-list`).then(json),
  setInMyList: (profileId, mediaId, inList) =>
    fetch(`/api/profiles/${profileId}/my-list/${mediaId}`, {
      method: inList ? 'PUT' : 'DELETE',
    }).then(json),
  myListPage: () => fetch('/api/catalog/my-list', withProfile()).then(json),
  hideContinue: (profileId, mediaId) =>
    fetch(`/api/profiles/${profileId}/continue/${mediaId}`, { method: 'DELETE' }).then(json),
  mine: () => fetch('/api/catalog/mine', withProfile()).then(json),

  ratings: (profileId) => fetch(`/api/profiles/${profileId}/ratings`).then(json),
  rate: (profileId, mediaId, value) =>
    fetch(`/api/profiles/${profileId}/ratings/${mediaId}${qs({ value })}`, {
      method: 'PUT',
    }).then(json),

  home: (mediaType) =>
    fetch(`/api/catalog/home${qs({ media_type: mediaType })}`, withProfile()).then(json),
  /* A play id, not a download id: "12" is a film, "e34" one episode of a season pack. */
  playInfo: (playId) =>
    fetch(`/api/play/${playId}/info`, withProfile()).then(json),
  prepare: (playId, audio) =>
    fetch(`/api/play/${playId}/prepare${qs({ audio })}`).then(json),
  reportProgress: (playId, position, duration) =>
    fetch(
      `/api/play/${playId}/progress${qs({ position, duration })}`,
      withProfile({
        method: 'POST',
        // keepalive lets the final report survive page teardown.
        keepalive: true,
      }),
    ).then(json),
  thumbs: (playId) => fetch(`/api/play/${playId}/thumbs.json`).then(json),
  clips: () => fetch('/api/clips', withProfile()).then(json),
  saveClip: (playId, start, end) =>
    fetch('/api/clips', withProfile({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ play_id: playId, start, end }),
    })).then(json),
  deleteClip: (id) => fetch(`/api/clips/${id}`, withProfile({ method: 'DELETE' })).then(json),
  searchSubtitles: (playId, language) =>
    fetch(`/api/play/${playId}/subs/search${qs({ language })}`).then(json),

  browse: (params) => fetch(`/api/catalog${qs(params)}`, withProfile()).then(json),
  stats: () => fetch('/api/catalog/stats').then(json),
  genres: (mediaType, order) =>
    fetch(`/api/catalog/genres${qs({ media_type: mediaType, order })}`).then(json),
  media: (id) => fetch(`/api/catalog/media/${id}`, withProfile()).then(json),
  // More Like This: the same kind of title with the most in common.
  person: (id) => fetch(`/api/catalog/person/${id}`, withProfile()).then(json),
  similar: (id) => fetch(`/api/catalog/media/${id}/similar`, withProfile()).then(json),
  // One season's episodes:
  season: (mediaId, number) =>
    fetch(`/api/catalog/media/${mediaId}/seasons/${number}`, withProfile()).then(json),

  downloads: (activeOnly = false) =>
    fetch(`/api/downloads${qs({ active_only: activeOnly })}`, withProfile()).then(json),
  // The manager view: the same downloads with live qBittorrent numbers and the
  // artwork they belong to, which the plain list deliberately does not carry.
  downloadManager: () => fetch('/api/downloads/manager', withProfile()).then(json),
  // Downloads as what was asked for: a job per film, episode or season, each with its own progress,
  // newest first. The torrent under a job is in its inspector; deleting a job deletes what it
  // brought (one episode of a pack leaves the others).
  downloadJobs: () => fetch('/api/downloads/jobs', withProfile()).then(json),
  inspectJob: (jobId) => fetch(`/api/downloads/jobs/${jobId}/inspect`, withProfile()).then(json),
  deleteJob: (jobId) => fetch(`/api/downloads/jobs/${jobId}`, { method: 'DELETE' }).then(json),
  notifications: (limit = 20) => fetch(`/api/notifications?limit=${limit}`, withProfile()).then(json),
  // Start a download. `episode` fetches one episode out of a season pack (and adds it to the pack's
  // torrent if that is already under way); `scope: 'all'` asks for the whole of a pack being
  // fetched an episode at a time.
  startDownload: (torrentId, { episode, scope, ignoreSpace } = {}) =>
    fetch(`/api/downloads/${torrentId}${qs({ episode, scope, ignore_space: ignoreSpace || undefined })}`, withProfile({
      method: 'POST',
    })).then(json),

  /* `force` removes a source still seeding, which the tracker counts as a hit and run. */
  space: () => fetch('/api/downloads/space').then(json),
  removeSource: (downloadId, force = false) =>
    fetch(`/api/downloads/${downloadId}/remove-source${qs({ force: force || undefined })}`, {
      method: 'POST',
    }).then(json),
  removeFinishedSources: () =>
    fetch('/api/downloads/sources/remove', { method: 'POST' }).then(json),
  cancelDownload: (downloadId, deleteFiles = true) =>
    fetch(`/api/downloads/${downloadId}${qs({ delete_files: deleteFiles })}`, {
      method: 'DELETE',
    }).then(json),

  removeEpisode: (downloadId, episodeId) =>
    fetch(`/api/downloads/${downloadId}/episodes/${episodeId}`, { method: 'DELETE' }).then(json),

  streamStatus: (downloadId) => fetch(`/api/stream/${downloadId}/status`).then(json),
  streamUrl: (downloadId) => `/api/stream/${downloadId}`,

  health: () => fetch('/api/admin/health').then(json),
  about: () => fetch('/api/admin/about').then(json),
  settings: () => fetch('/api/admin/settings').then(json),
  events: (limit = 60) => fetch(`/api/admin/events${qs({ limit })}`).then(json),
  sweep: () => fetch('/api/admin/sweep', { method: 'POST' }).then(json),
  enrich: () => fetch('/api/admin/enrich', { method: 'POST' }).then(json),
  reap: (dryRun = true) =>
    fetch(`/api/admin/reap${qs({ dry_run: dryRun })}`, { method: 'POST' }).then(json),
}

export const formatBytes = (bytes) => {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`
}

export const formatSpeed = (bytesPerSecond) =>
  bytesPerSecond > 0 ? `${formatBytes(bytesPerSecond)}/s` : ''

export const formatEta = (seconds) => {
  if (seconds === null || seconds === undefined || seconds < 0) return ''
  if (seconds < 60) return `${Math.round(seconds)}s`
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.round((seconds % 3600) / 60)
  return `${hours}h ${minutes}m`
}

export const formatRuntime = (minutes) => {
  if (!minutes) return null
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  if (h && !m) return `${h}h`
  return h ? `${h}h ${m}m` : `${m}m`
}

/* A pack's per-episode share is exact once its file list is known, an estimate before. */
export const episodeCost = (release) => {
  if (!release || !release.episode_size_gb) return ''
  return `${release.episode_size_exact ? '' : 'about '}${release.episode_size_gb} GB`
}
