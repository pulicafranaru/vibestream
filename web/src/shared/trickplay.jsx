import { useEffect, useState } from 'react'
import { api } from '../api'

// Scrubber thumbnails from sprite sheets of 64. Frame times are listed, not derived,
// because frames are taken on keyframes and are unevenly spaced.

const POLL_MS = 15000

/** Polls until the manifest exists; generation can take minutes. Null means "no previews". */
export function useTrickplay(downloadId, enabled = true) {
  const [manifest, setManifest] = useState(null)

  useEffect(() => {
    if (!enabled || !downloadId) return undefined
    let alive = true
    let timer = null

    const poll = () => {
      api
        .thumbs(downloadId)
        .then((data) => {
          if (!alive) return
          if (data?.ready && data.count > 0) {
            setManifest(data)
            return
          }
          timer = setTimeout(poll, POLL_MS)
        })
        .catch(() => {
          if (alive) timer = setTimeout(poll, POLL_MS)
        })
    }

    setManifest(null)
    poll()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [downloadId, enabled])

  return manifest
}

export function tileHeightFor(manifest, width) {
  if (!manifest) return Math.round((width * 9) / 16)
  return Math.round((manifest.tile_height / manifest.tile_width) * width)
}

/** The last frame at or before `seconds`, matching where a keyframe seek lands. */
export function frameAt(manifest, seconds) {
  const times = manifest.times
  let low = 0
  let high = times.length - 1
  let found = 0
  while (low <= high) {
    const mid = (low + high) >> 1
    if (times[mid] <= seconds) {
      found = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }
  return found
}

export function thumbStyle(manifest, seconds, width) {
  const index = frameAt(manifest, seconds)
  const sheet = Math.floor(index / manifest.per_sheet)
  const cell = index % manifest.per_sheet
  const col = cell % manifest.columns
  const row = Math.floor(cell / manifest.columns)
  const height = tileHeightFor(manifest, width)

  return {
    width: `${width}px`,
    height: `${height}px`,
    backgroundImage: `url(${manifest.url}/${sheet}.jpg)`,
    backgroundSize: `${manifest.columns * width}px ${manifest.rows * height}px`,
    backgroundPosition: `-${col * width}px -${row * height}px`,
  }
}

// Neighbours are one thumbnail apart, not one stride, so the strip means the same
// however fast the key repeats.
export function Filmstrip({ manifest, time, width = 264, span = 2 }) {
  const height = tileHeightFor(manifest, width)
  const centre = frameAt(manifest, time)
  const cells = []

  for (let offset = -span; offset <= span; offset += 1) {
    // Step by thumbnail, not seconds: uneven spacing would repeat frames.
    const index = centre + offset
    const inRange = index >= 0 && index < manifest.count
    cells.push(
      <div
        key={offset}
        className={`filmstrip-cell ${offset === 0 ? 'focused' : ''}`}
        style={{ width: `${width}px`, height: `${height}px` }}
      >
        {inRange ? (
          <div
            className="filmstrip-thumb"
            style={thumbStyle(manifest, manifest.times[index], width)}
          />
        ) : (
          <div className="filmstrip-thumb empty" />
        )}
      </div>,
    )
  }

  return <div className="filmstrip">{cells}</div>
}

export function ScrubPreview({ manifest, time, left, label, width = 184 }) {
  return (
    <div className="scrub-preview" style={{ left: `${left}px` }}>
      {manifest ? (
        <div className="scrub-preview-img" style={thumbStyle(manifest, time, width)} />
      ) : null}
      <div className="scrub-preview-time">{label}</div>
    </div>
  )
}
