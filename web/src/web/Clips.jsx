import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { Icon, PauseIcon, PlayIcon } from '../shared/icons'
import { confirmDialog } from './Confirm'

const length = (seconds) => {
  const total = Math.max(0, Math.round(seconds))
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`
}

export function ClipsRow({ shell }) {
  const [clips, setClips] = useState(null)
  const [playing, setPlaying] = useState(null)

  useEffect(() => {
    let alive = true
    api.clips().then((data) => alive && setClips(data.items || [])).catch(() => alive && setClips([]))
    return () => {
      alive = false
    }
  }, [shell.profile])

  if (!clips?.length) return null

  const remove = async (clip) => {
    if (!await confirmDialog({ title: 'Delete Clip?', message: `This clip from ${clip.title} goes for good.`, action: 'Delete' })) return
    await api.deleteClip(clip.id).catch(() => {})
    setClips((all) => all.filter((c) => c.id !== clip.id))
  }

  return (
    <section className="row clips-row">
      <div className="row-head"><h2>Clips you&rsquo;ve saved</h2></div>
      <div className="row-strip">
        {clips.map((clip) => (
          <div key={clip.id} className="clip-tile">
            <button type="button" className="clip-tile-art" onClick={() => setPlaying(clip)}
              aria-label={`Play clip from ${clip.title}`}>
              <img src={clip.thumb} alt="" loading="lazy" />
              <span className="clip-tile-play"><PlayIcon size={18} /></span>
              <span className="clip-tile-length">{length(clip.duration)}</span>
            </button>
            <button type="button" className="clip-tile-delete" onClick={() => remove(clip)}
              aria-label="Delete clip" title="Delete clip">
              <Icon name="close" size={14} />
            </button>
            <div className="clip-tile-title">{clip.title}</div>
            {clip.subtitle && <div className="clip-tile-sub">{clip.subtitle}</div>}
          </div>
        ))}
      </div>
      {playing && (
        <ClipPlayer
          clip={playing}
          onClose={() => setPlaying(null)}
          onOpenTitle={clip => {
            setPlaying(null)
            if (clip.media_id) shell.openTitle({ media_id: clip.media_id })
          }}
        />
      )}
    </section>
  )
}

export function ClipPlayer({ clip, onClose, onOpenTitle }) {
  const video = useRef(null)
  const bar = useRef(null)
  const timer = useRef(null)
  const [time, setTime] = useState(0)
  const [length_, setLength] = useState(clip.duration)
  const [playing, setPlaying] = useState(false)
  const [chrome, setChrome] = useState(true)

  const wake = useCallback(() => {
    setChrome(true)
    clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      if (video.current && !video.current.paused) setChrome(false)
    }, 3000)
  }, [])

  const toggle = useCallback(() => {
    const v = video.current
    if (!v) return
    if (v.paused) {
      if (v.currentTime >= (v.duration || length_) - 0.3) v.currentTime = 0
      v.play().catch(() => {})
    } else v.pause()
    wake()
  }, [length_, wake])

  const skip = useCallback((by) => {
    const v = video.current
    if (!v) return
    v.currentTime = Math.min(Math.max(0, v.currentTime + by), v.duration || length_)
    wake()
  }, [length_, wake])

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === 'Escape') onClose()
      else if (event.key === ' ' || event.key === 'k') toggle()
      else if (event.key === 'ArrowLeft') skip(-10)
      else if (event.key === 'ArrowRight') skip(10)
      else return
      event.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      clearTimeout(timer.current)
    }
  }, [onClose, toggle, skip])

  useEffect(wake, [wake])

  const seekTo = (event) => {
    const box = bar.current.getBoundingClientRect()
    const ratio = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width))
    if (video.current) video.current.currentTime = ratio * length_
    wake()
  }

  const pct = Math.min(100, (time / Math.max(length_, 0.1)) * 100)

  return (
    <div className={`clip-player ${chrome ? '' : 'calm'}`} onPointerMove={wake}>
      <video
        ref={video}
        src={clip.video}
        autoPlay
        playsInline
        onClick={toggle}
        onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
        onLoadedMetadata={(e) => Number.isFinite(e.currentTarget.duration) && setLength(e.currentTarget.duration)}
        onPlay={() => { setPlaying(true); wake() }}
        onPause={() => { setPlaying(false); setChrome(true) }}
      />
      <div className="clip-player-chrome">
        <div className="clip-player-top">
          <button type="button" className="clip-player-source" onClick={() => onOpenTitle(clip)}
            disabled={!clip.media_id}>
            <strong>Starts at {length(clip.start)}</strong>
            <span>{clip.subtitle || clip.title} ›</span>
          </button>
          <button type="button" className="clip-player-close" onClick={onClose} aria-label="Close">
            <Icon name="close" size={26} />
          </button>
        </div>
        <div className="clip-player-centre">
          <button type="button" onClick={() => skip(-10)} aria-label="Back 10 seconds">
            <Icon name="back-10" size={46} />
          </button>
          <button type="button" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
            {playing ? <PauseIcon size={62} /> : <PlayIcon size={62} />}
          </button>
          <button type="button" onClick={() => skip(10)} aria-label="Forward 10 seconds">
            <Icon name="forward-10" size={46} />
          </button>
        </div>
        <div className="clip-player-bottom">
          <div className="clip-player-bar" ref={bar} onPointerDown={seekTo}
            role="slider" aria-label="Seek" aria-valuenow={Math.round(time)}>
            <div className="clip-player-fill" style={{ width: `${pct}%` }} />
            <div className="clip-player-knob" style={{ left: `${pct}%` }} />
          </div>
          <span>{length(Math.max(0, length_ - time))}</span>
        </div>
      </div>
    </div>
  )
}
