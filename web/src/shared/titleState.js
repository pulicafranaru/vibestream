/*
 * What a title's one button says and does, shared so every screen agrees.
 * 
 *   download    nothing here yet
 *   waiting     the server has it, no bytes have arrived
 *   downloading percent is null below one percent, which would read as a stall
 *   preparing   on disk, being made playable
 *   play        ready (Resume when part watched)
 *   failed      preparation gave up; pressing retries
 */

const WORKING = ['downloading', 'adding', 'requested']

export function titleState(live, card = {}) {
  const resumePlayId = card.resume_play_id
  const resumePercent = card.resume_percent || 0

  if (!live || live.state === 'removed') {
    return { id: 'download', label: 'Download', icon: 'download', busy: false }
  }

  if (live.playable) {
    const playId = resumePlayId || String(live.id)
    const resuming = resumePercent > 1 && resumePercent < 95
    return {
      id: 'play',
      label: resuming ? 'Resume' : 'Play',
      icon: 'play',
      busy: false,
      playId,
    }
  }

  if (live.prepare_error) {
    return { id: 'failed', label: 'Try again', icon: 'replay', busy: false }
  }

  if (live.preparing) {
    const percent = live.prepare_percent || 0
    return {
      id: 'preparing',
      label: percent ? `Preparing ${Math.round(percent)}%` : 'Preparing',
      busy: true,
      percent,
      spin: !percent,
    }
  }

  if (live.state === 'downloading') {
    const percent = live.percent || 0
    return {
      id: 'downloading',
      label: percent >= 1 ? `Downloading ${Math.round(percent)}%` : 'Downloading',
      busy: true,
      percent,
      spin: percent < 1,
    }
  }

  if (WORKING.includes(live.state)) {
    return { id: 'waiting', label: 'Waiting for download', busy: true, percent: 0, spin: true }
  }

  if (live.state === 'error') {
    return { id: 'failed', label: 'Try again', icon: 'replay', busy: false }
  }

  return { id: 'download', label: 'Download', icon: 'download', busy: false }
}

// The live row for a card. Every release is checked: the copy on disk is often not the catalog's pick.
export function liveFor(card, downloads) {
  if (!card) return null
  const ids = (card.releases || []).map((r) => r.id)
  if (card.primary_release_id) ids.push(card.primary_release_id)

  const known = []
  for (const id of ids) {
    const row = downloads[id]
    if (row && row.state !== 'removed') known.push(row)
  }
  const playable = known.find((d) => d.playable)
  if (playable) return playable
  const busy = known.find(
    (d) => WORKING.includes(d.state) || d.preparing,
  )
  if (busy) return busy
  if (known.length) return known[0]
  // Before the first poll the card's own copy is best; after it, misleading.
  return Object.keys(downloads).length ? null : card.download || null
}
