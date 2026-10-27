import { activeProfile } from '../api'

// Audio and subtitle choice per profile per title, as languages: files number
// their tracks differently. audio: code or null (file default); subs: code,
// 'off' or null.

const key = (mediaId) => `vs.tracks.${activeProfile() || 0}.${mediaId}`

export function loadTrackPrefs(mediaId) {
  if (!mediaId) return null
  try {
    const raw = localStorage.getItem(key(mediaId))
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function saveTrackPrefs(mediaId, prefs) {
  if (!mediaId) return
  try {
    localStorage.setItem(key(mediaId), JSON.stringify(prefs))
  } catch {
    /* a full or blocked store only costs the memory */
  }
}

// ISO 639-2 has two codes for some languages ("ger"/"deu", "rum"/"ron");
// external subtitles use two letters.
const ALIASES = {
  en: 'en', eng: 'en',
  de: 'de', ger: 'de', deu: 'de',
  ro: 'ro', rum: 'ro', ron: 'ro', mol: 'ro',
  fr: 'fr', fre: 'fr', fra: 'fr',
  es: 'es', spa: 'es',
  it: 'it', ita: 'it',
  hu: 'hu', hun: 'hu',
}

export function sameLanguage(a, b) {
  if (!a || !b) return false
  const x = String(a).toLowerCase().split(/[-_]/)[0]
  const y = String(b).toLowerCase().split(/[-_]/)[0]
  return (ALIASES[x] || x) === (ALIASES[y] || y)
}

export function languageCode(value) {
  if (!value) return null
  const x = String(value).toLowerCase().split(/[-_]/)[0]
  return ALIASES[x] || x
}

export function applyTrackPrefs(prefs, info) {
  const out = { audioIndex: null, subtitleId: undefined }
  if (!prefs || !info) return out
  if (prefs.audio) {
    const match = (info.audio || []).find((a) => sameLanguage(a.language, prefs.audio))
    if (match && !match.default) out.audioIndex = match.index
  }
  if (prefs.subs === 'off') out.subtitleId = null
  else if (prefs.subs) {
    const list = (info.subtitles || []).filter((s) => sameLanguage(s.language, prefs.subs))
    // Prefer a full track over a forced one, which only covers foreign dialogue.
    const match = list.find((s) => !s.forced) || list[0]
    if (match) out.subtitleId = match.id
  }
  return out
}
