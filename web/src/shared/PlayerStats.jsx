import { useEffect, useRef, useState } from 'react'

/* Playback stats, sampled once a second from the element and hls.js while shown. */
const WINDOW = 60

export default function PlayerStats({ videoRef, hlsRef, info, playId, stageRef }) {
  const [, setTick] = useState(0)
  const samples = useRef([])
  const bytes = useRef(0)
  const last = useRef({})

  useEffect(() => {
    const hls = hlsRef.current
    if (!hls || !hls.on) return undefined
    const onFrag = (_event, data) => {
      const stats = (data && (data.frag && data.frag.stats)) || (data && data.stats) || {}
      bytes.current += stats.total || stats.loaded || 0
    }
    hls.on('hlsFragLoaded', onFrag)
    return () => hls.off && hls.off('hlsFragLoaded', onFrag)
  }, [hlsRef])

  useEffect(() => {
    const sample = () => {
      const video = videoRef.current
      if (!video) return
      const hls = hlsRef.current
      const at = video.currentTime
      let buffer = 0
      for (let i = 0; i < video.buffered.length; i += 1) {
        if (video.buffered.start(i) <= at + 0.5 && at <= video.buffered.end(i)) {
          buffer = Math.max(0, video.buffered.end(i) - at)
        }
      }
      const kbps = hls && hls.bandwidthEstimate ? hls.bandwidthEstimate / 1000 : 0
      const kb = bytes.current / 1024
      bytes.current = 0
      const quality = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null
      last.current = {
        kbps, kb, buffer,
        dropped: quality ? quality.droppedVideoFrames : null,
        frames: quality ? quality.totalVideoFrames : null,
        width: video.videoWidth,
        height: video.videoHeight,
        volume: video.volume,
        muted: video.muted,
        level: hls && hls.levels && hls.currentLevel >= 0 ? hls.levels[hls.currentLevel] : null,
      }
      samples.current = samples.current.concat([{ kbps, kb, buffer }]).slice(-WINDOW)
      setTick((n) => n + 1)
    }
    sample()
    const timer = setInterval(sample, 1000)
    return () => clearInterval(timer)
  }, [videoRef, hlsRef])

  const s = last.current
  const media = (info && info.media) || {}
  const video = media.video || {}
  const playback = (info && info.playback) || {}
  const file = info && info.file
  const stage = stageRef.current
  const ratio = window.devicePixelRatio || 1

  const engine = `${playId} / ${playback.engine === 'live' ? 'live remux' : 'prepared rendition'}${playback.mode ? `, ${playback.mode}` : ''}`
  const fileLine = file ? `${file.name}${file.size_bytes ? ` (${(file.size_bytes / 1e9).toFixed(2)} GB)` : ''}` : '?'
  // As drawn: smaller than the element while Settings is open.
  const drawn = stage ? stage.getBoundingClientRect() : { width: 0, height: 0 }
  const viewport = `${Math.round(drawn.width)}x${Math.round(drawn.height)}*${ratio.toFixed(2)}`
    + (s.frames !== null && s.frames !== undefined ? ` / ${s.dropped} dropped of ${s.frames}` : '')
  const source = video.width && video.height
    ? ` / ${video.width}x${video.height}${video.frame_rate ? `@${Math.round(video.frame_rate * 100) / 100}` : ''}`
    : ''
  const current = s.width ? `${s.width}x${s.height}` : '?'
  const audioTrack = (media.audio || [])[0] || {}
  const codecs = `${[video.codec, video.profile].filter(Boolean).join(' ') || '?'}${video.bit_depth ? ` ${video.bit_depth}-bit` : ''}`
    + ` / ${[audioTrack.codec, audioTrack.channels ? `${audioTrack.channels}ch` : null].filter(Boolean).join(' ') || '?'}`
    + (playback.audio_transcoded ? ' > aac' : '')
  const color = video.dolby_vision ? `Dolby Vision${video.hdr ? ' / HDR10 base' : ''}`
    : video.hdr ? `HDR (${video.bit_depth || 10}-bit)` : 'SDR'
  const variant = s.level && s.level.bitrate ? `${Math.round(s.level.bitrate / 1000)} Kbps variant` : 'native HLS'
  const stream = `${variant}${media.container ? `, ${media.container}` : ''}, ${window.location.host}`

  const rows = [
    ['Play ID / Engine', engine],
    ['File', fileLine],
    ['Viewport / Frames', viewport],
    ['Current / Source Res', current + source],
    ['Volume', `${Math.round((s.volume || 0) * 100)}%${s.muted ? ', muted' : ''}`],
    ['Codecs', codecs],
    ['Color', color],
  ]

  return (
    <div className="pstats">
      <table>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}><th>{label}</th><td>{value}</td></tr>
          ))}
          <tr>
            <th>Connection Speed</th>
            <td><Spark values={samples.current.map((x) => x.kbps)} tint="#2980c7" />
              {s.kbps ? `${Math.round(s.kbps)} Kbps` : 'n/a'}</td>
          </tr>
          <tr>
            <th>Network Activity</th>
            <td><Spark values={samples.current.map((x) => x.kb)} tint="#5cbf9e" />{`${Math.round(s.kb || 0)} KB`}</td>
          </tr>
          <tr>
            <th>Buffer Health</th>
            <td><Spark values={samples.current.map((x) => x.buffer)} tint="#dbf08f" />{`${(s.buffer || 0).toFixed(2)} s`}</td>
          </tr>
          <tr><th>Stream</th><td>{stream}</td></tr>
          <tr><th>Date</th><td>{new Date().toString().replace(/ \(.*\)$/, '')}</td></tr>
        </tbody>
      </table>
    </div>
  )
}

function Spark({ values, tint }) {
  const top = Math.max(0.0001, ...values)
  return (
    <span className="pstats-spark">
      {values.map((value, i) => (
        <i
          key={WINDOW - values.length + i}
          style={{
            left: `${((WINDOW - values.length + i) / WINDOW) * 100}%`,
            height: `${Math.max(4, (value / top) * 100)}%`,
            background: tint,
          }}
        />
      ))}
    </span>
  )
}
