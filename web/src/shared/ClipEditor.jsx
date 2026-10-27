import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { api } from '../api'
import { thumbStyle } from './trickplay'

// Clip a Moment. The preview is the player's own video, shrunk by .player.clipping
// in player.css, so looping between the handles is just a seek. A clip at the
// maximum length keeps its length when a handle is pushed: the other end follows.
const LONGEST = 120
const SHORTEST = 2
const SPAN = 130
const MARGIN = 4
const HANDLE = 26
const CELLS = 16
const EDGE = 40
const ROLL_SPEED = 10 // seconds of film per second while a handle is held at an edge

export default function ClipEditor({ videoRef, duration, playId, trick, fmtTime, onClose }) {
  const total = Math.max(duration || 0, SHORTEST)
  const span = Math.min(SPAN, total)
  const [range, setRange] = useState(() => {
    const now = videoRef.current?.currentTime || 0
    const end = Math.min(total, Math.max(now, Math.min(total, 30)))
    const start = Math.max(0, end - 30)
    const win = Math.max(0, Math.min(start - MARGIN, total - span))
    return { start, end, win }
  })
  const [playhead, setPlayhead] = useState(range.start)
  const [previewing, setPreviewing] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [failure, setFailure] = useState(null)
  const [width, setWidth] = useState(800)
  const strip = useRef(null)
  const drag = useRef(null)
  const latest = useRef(range)
  latest.current = range

  useLayoutEffect(() => {
    const el = strip.current
    if (!el) return undefined
    const measure = () => setWidth(el.clientWidth)
    measure()
    const observer = new ResizeObserver(measure)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const inner = Math.max(1, width - HANDLE * 2)
  const x = (t) => HANDLE + ((t - range.win) / span) * inner
  const seconds = (dx) => (dx / inner) * span

  const hold = useCallback((t) => {
    const video = videoRef.current
    if (!video) return
    if (!video.paused) video.pause()
    setPreviewing(false)
    // Seeks pile up during a drag; only the newest matters.
    drag.current && (drag.current.seekTo = t)
    if (!video.seeking) video.currentTime = t
  }, [videoRef])

  const replay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    video.currentTime = latest.current.start
    video.play().catch(() => {})
    setPreviewing(true)
  }, [videoRef])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return undefined
    video.currentTime = range.start
    video.play().catch(() => {})
    let frame
    const tick = () => {
      const { start, end } = latest.current
      const t = video.currentTime
      setPlayhead(t)
      if (drag.current?.seekTo != null && !video.seeking) {
        video.currentTime = drag.current.seekTo
        drag.current.seekTo = null
      }
      if (!drag.current && !video.paused && (t >= end || t < start - 1)) video.currentTime = start
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  const follow = (start, end, win) => {
    let from = win
    if (end > win + span - MARGIN) from = end + MARGIN - span
    if (start < from + MARGIN) from = start - MARGIN
    return Math.max(0, Math.min(from, total - span))
  }

  const moveStart = (wanted) => {
    const { end, win } = latest.current
    const start = Math.min(Math.max(0, wanted), end - SHORTEST, total - SHORTEST)
    const newEnd = end - start > LONGEST ? start + LONGEST : end
    const next = { start, end: newEnd, win: follow(start, newEnd, win) }
    latest.current = next
    setRange(next)
    hold(start)
  }

  const moveEnd = (wanted) => {
    const { start, win } = latest.current
    const end = Math.max(Math.min(total, wanted), start + SHORTEST, SHORTEST)
    const newStart = end - start > LONGEST ? end - LONGEST : start
    const next = { start: newStart, end, win: follow(newStart, end, win) }
    latest.current = next
    setRange(next)
    hold(Math.max(newStart, end - 1))
  }

  const rollFilm = (delta) => {
    const from = drag.current?.from
    if (!from) return
    const length = from.end - from.start
    const start = Math.min(Math.max(0, from.start + delta), total - length)
    const moved = start - from.start
    const win = Math.max(0, Math.min(from.win + moved, total - span))
    const next = { start, end: start + length, win }
    latest.current = next
    setRange(next)
    hold(start)
    return start
  }

  const apply = () => {
    const d = drag.current
    if (!d) return
    if (d.grip === 'start') moveStart(d.from.start + d.travelled + d.rolled)
    else if (d.grip === 'end') moveEnd(d.from.end + d.travelled + d.rolled)
  }

  useEffect(() => {
    let frame
    let last = performance.now()
    const tick = (now) => {
      const dt = Math.min(0.05, (now - last) / 1000)
      last = now
      const d = drag.current
      if (d && d.rolling && d.grip !== 'film') {
        d.rolled += d.rolling * ROLL_SPEED * dt
        apply()
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [span, total, inner])

  const begin = (grip, event) => {
    event.preventDefault()
    event.stopPropagation()
    cancelAnimationFrame(drag.current?.coast)
    event.currentTarget.setPointerCapture(event.pointerId)
    drag.current = {
      grip,
      from: { ...latest.current },
      x: event.clientX,
      travelled: 0,
      rolled: 0,
      rolling: 0,
      seekTo: null,
      track: [{ x: event.clientX, t: performance.now() }],
    }
  }

  const move = (event) => {
    const d = drag.current
    if (!d || d.coasting) return
    const dx = event.clientX - d.x
    d.track.push({ x: event.clientX, t: performance.now() })
    if (d.track.length > 6) d.track.shift()
    if (d.grip === 'film') {
      d.travelled = -seconds(dx)
      rollFilm(d.travelled)
      return
    }
    d.travelled = seconds(dx)
    const box = strip.current.getBoundingClientRect()
    const at = event.clientX - box.left
    d.rolling = at < EDGE ? -1 : at > box.width - EDGE ? 1 : 0
    apply()
  }

  const finish = () => {
    drag.current = null
    replay()
  }

  /** A fling coasts with decaying velocity, then the preview plays. */
  const end = () => {
    const d = drag.current
    if (!d) return
    if (d.grip !== 'film' || d.track.length < 2) {
      finish()
      return
    }
    const first = d.track[0]
    const lastPoint = d.track[d.track.length - 1]
    const ms = Math.max(1, lastPoint.t - first.t)
    let speed = -seconds(((lastPoint.x - first.x) / ms) * 1000)
    if (performance.now() - lastPoint.t > 80 || Math.abs(speed) < 4) {
      finish()
      return
    }
    d.coasting = true
    let delta = d.travelled
    let previous = performance.now()
    const step = (now) => {
      const dt = Math.min(0.05, (now - previous) / 1000)
      previous = now
      delta += speed * dt
      const before = latest.current.start
      const start = rollFilm(delta)
      speed *= Math.pow(0.94, dt * 60)
      if (Math.abs(speed) < 1 || start === before) {
        finish()
        return
      }
      d.coast = requestAnimationFrame(step)
    }
    d.coast = requestAnimationFrame(step)
  }

  const save = async () => {
    setSaving(true)
    setFailure(null)
    try {
      await api.saveClip(playId, latest.current.start, latest.current.end)
      setSaving(false)
      setSaved(true)
      setTimeout(leave, 1200)
    } catch {
      setSaving(false)
      setFailure("Couldn't save the clip. Try again.")
    }
  }

  const leave = () => {
    cancelAnimationFrame(drag.current?.coast)
    drag.current = null
    videoRef.current?.pause()
    onClose()
  }

  const togglePreview = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) replay()
    else {
      video.pause()
      setPreviewing(false)
    }
  }

  // The player's own keys are off while this is open.
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') leave()
      else if (event.key === ' ') togglePreview()
      else return
      event.preventDefault()
      event.stopPropagation()
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  })

  // Each frame is pinned to its own moment so the strip slides them, not swaps them.
  const step = span / CELLS
  const cell = (step / span) * inner
  const firstCell = Math.floor(range.win / step)
  const lastCell = Math.ceil((range.win + span) / step)
  const cells = []
  for (let index = firstCell; index < lastCell; index += 1) {
    const at = (index + 0.5) * step
    if (at > total) break
    cells.push(
      <div
        key={index}
        className="clip-cell"
        style={{ left: `${((index * step - range.win) / span) * inner}px`, width: `${cell + 1}px` }}
      >
        {trick && <div className="clip-cell-img" style={thumbStyle(trick, at, Math.ceil(cell + 1))} />}
      </div>,
    )
  }

  const shownHead = Math.min(Math.max(playhead, range.start), range.end)

  return (
    <div className="clip-editor" onPointerMove={move} onPointerUp={end} onPointerCancel={end}>
      <div className="clip-head">
        <button type="button" className="clip-back" onClick={leave} aria-label="Back">‹</button>
        <h2>Clip a Moment</h2>
        <button type="button" className="clip-save" onClick={save} disabled={saving || saved}>
          {saving ? 'Saving…' : 'Save'}
        </button>
      </div>
      {failure && <p className="clip-failure">{failure}</p>}

      <div className="clip-middle">
        <div className="clip-bound start">
          <span>Start</span>
          <strong>{fmtTime(range.start)}</strong>
        </div>
        <div className="clip-frame">
          <div className="clip-frame-controls">
            <button type="button" onClick={togglePreview} aria-label={previewing ? 'Pause' : 'Play'}>
              {previewing ? '❚❚' : '▶'}
            </button>
            <button type="button" onClick={replay} aria-label="Play from the start">↺</button>
          </div>
        </div>
        <div className="clip-bound end">
          <span>End</span>
          <strong>{fmtTime(range.end)}</strong>
        </div>
      </div>

      <div className="clip-strip" ref={strip}>
        <div className="clip-head-time" style={{ left: `${x(shownHead)}px` }}>{fmtTime(shownHead)}</div>
        <div
          className="clip-film"
          style={{ left: `${HANDLE}px`, width: `${inner}px` }}
          onPointerDown={(e) => begin('film', e)}
        >
          {cells}
        </div>
        <div
          className="clip-selection"
          style={{ left: `${x(range.start) - HANDLE}px`, width: `${x(range.end) - x(range.start) + HANDLE * 2}px` }}
        />
        <div className="clip-playhead" style={{ left: `${x(shownHead)}px` }} />
        <div
          className="clip-handle start"
          style={{ left: `${x(range.start) - HANDLE}px`, width: `${HANDLE}px` }}
          onPointerDown={(e) => begin('start', e)}
          role="slider"
          aria-label="Start"
          aria-valuenow={Math.round(range.start)}
        >‹›</div>
        <div
          className="clip-handle end"
          style={{ left: `${x(range.end)}px`, width: `${HANDLE}px` }}
          onPointerDown={(e) => begin('end', e)}
          role="slider"
          aria-label="End"
          aria-valuenow={Math.round(range.end)}
        >‹›</div>
      </div>

      {saved && <div className="clip-toast">✓ Saved to Library</div>}
    </div>
  )
}
