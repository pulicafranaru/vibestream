import { useEffect, useRef, useState } from 'react'
// Imported so the build gives it a content-hashed name; a fixed name stayed cached on TVs.
import SRC from './intro.mp4'

// The intro is a video, not drawn live: the TVs drop most frames of a 1080p canvas but decode H.264 in hardware.

const PRELOAD_LIMIT_MS = 6000
const FADE_MS = 700

let preloaded = null

export function preloadIntro() {
  if (preloaded) return preloaded
  preloaded = new Promise((resolve) => {
    const video = document.createElement('video')
    let settled = false
    const finish = (ok) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(ok ? video : null)
    }
    const timer = setTimeout(() => finish(video.readyState >= 3), PRELOAD_LIMIT_MS)
    video.muted = true
    video.playsInline = true
    video.preload = 'auto'
    video.addEventListener('canplaythrough', () => finish(true))
    video.addEventListener('error', () => finish(false))
    video.src = SRC
    video.load()
  })
  return preloaded
}

export function lastIntroPlayback() {
  try {
    return localStorage.getItem('vs.introFrames') || null
  } catch {
    return null
  }
}

function recordPlayback(video) {
  let decoded = null
  let dropped = null
  if (video.getVideoPlaybackQuality) {
    const q = video.getVideoPlaybackQuality()
    decoded = q.totalVideoFrames
    dropped = q.droppedVideoFrames
  } else if (typeof video.webkitDecodedFrameCount === 'number') {
    decoded = video.webkitDecodedFrameCount
    dropped = video.webkitDroppedFrameCount
  }
  if (decoded === null) return
  try {
    localStorage.setItem('vs.introFrames',
      `${decoded} frames, ${dropped} dropped, sound ${video.muted ? 'off' : 'on'}`)
  } catch {
    /* only the Debug screen misses it */
  }
}

export default function Intro({ video, onReveal, onDone }) {
  const holder = useRef(null)
  const [fading, setFading] = useState(!video)
  const reveal = useRef(onReveal)
  const done = useRef(onDone)
  reveal.current = onReveal
  done.current = onDone

  useEffect(() => {
    let finished = false
    let timer = 0
    const finish = () => {
      if (finished) return
      finished = true
      if (video) {
        recordPlayback(video)
        video.pause()
        if (video.parentNode) video.parentNode.removeChild(video)
      }
      if (reveal.current) reveal.current()
      setFading(true)
      timer = setTimeout(() => done.current && done.current(), FADE_MS)
    }
    if (!video) {
      finish()
      return () => clearTimeout(timer)
    }
    video.className = 'intro-video'
    holder.current.appendChild(video)
    video.addEventListener('ended', finish)
    video.addEventListener('error', finish)
    // Loaded muted (a muted video may always preload), then played with sound, or silent if the engine refuses.
    video.muted = false
    const started = video.play()
    if (started && started.catch) {
      started.catch((error) => {
        if (!error || error.name !== 'NotAllowedError' || finished) return finish()
        video.muted = true
        const silent = video.play()
        if (silent && silent.catch) silent.catch(finish)
      })
    }
    return () => {
      clearTimeout(timer)
      if (!finished) video.pause()
      video.removeEventListener('ended', finish)
      video.removeEventListener('error', finish)
    }
  }, [video])

  return <div className={`intro ${fading ? 'fading' : ''}`} ref={holder} />
}
