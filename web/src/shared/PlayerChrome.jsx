import { Icon, PauseIcon, PlayIcon } from './icons'
import { ScrubPreview } from './trickplay'
import { t } from './i18n'

// The player's controls. On the TV a focus moves over them with the remote and
// the focused one shows its name; the browser uses the pointer.
export const SPEEDS = [0.5, 0.75, 1, 1.25, 1.5, 2]

export function speedLabel(rate) {
  return rate === 1 ? '1x' : `${rate}x`
}

export default function PlayerChrome({
  browser,
  visible,
  focus,
  onFocus,
  title,
  episodeLine,
  playing,
  ready = true,
  onTogglePlay,
  onSkip,
  onExit,
  topRight = [],
  leftItems = [],
  rightItems = [],
  volume = null,
  scrub,
  filmstrip = null,
  tray = null,
  rate = 1,
  onRate,
  trayIndex = 0,
  // Pixels per TV pixel: 1 on the TV, the window's share in a browser.
  unit = 1,
  // Inline in the title page: no close or title, smaller middle controls.
  compact = false,
}) {
  const px = (n) => Math.round(n * Math.max(unit, 0.6))
  const focused = (zone, index) => Boolean(focus && focus.zone === zone && focus.index === index)
  const hover = (zone, index) => (browser || !onFocus ? undefined : () => onFocus(zone, index))
  const seeking = scrub.seeking
  const rowItems = leftItems.concat(rightItems)

  const button = (zone, index, item, size = 34) => (
    <button
      key={item.id}
      type="button"
      className={['pc-icon', item.on ? 'on' : '', focused(zone, index) ? 'focused' : ''].join(' ')}
      onClick={item.onPress}
      onMouseEnter={hover(zone, index)}
      aria-label={item.label}
      title={browser ? item.label : undefined}
    >
      <Icon name={item.icon} size={px(size)} />
      {!browser && zone !== 'row' && focused(zone, index) && <span className="pc-name">{item.label}</span>}
    </button>
  )

  return (
    <div className={`pc ${visible ? '' : 'hidden'} ${seeking ? 'seeking' : ''}`}>
      <div className="pc-shade" />

      <div className="pc-top">
        {!compact && button('top', 0, { id: 'close', icon: 'close', label: t('Close'), onPress: onExit }, 40)}
        <div className="pc-heading">
          {!compact && <strong>{title}</strong>}
          {!compact && episodeLine && <span>{episodeLine}</span>}
        </div>
        <div className="pc-top-right">
          {topRight.map((item, i) => button('top', i + 1, item, 38))}
        </div>
      </div>

      {/* Hidden until playable, so they do not cover "Starting playback". */}
      {!seeking && ready && (
        <div className="pc-centre">
          {button('centre', 0, { id: 'back10', icon: 'back-10', label: t('Back 10 seconds'), onPress: () => onSkip(-10) }, compact ? 56 : 76)}
          <button
            type="button"
            className={`pc-icon pc-play ${focused('centre', 1) ? 'focused' : ''}`}
            onClick={onTogglePlay}
            onMouseEnter={hover('centre', 1)}
            aria-label={playing ? t('Pause') : t('Play')}
          >
            {playing ? <PauseIcon size={px(compact ? 76 : 100)} /> : <PlayIcon size={px(compact ? 76 : 100)} />}
          </button>
          {button('centre', 2, { id: 'fwd10', icon: 'forward-10', label: t('Forward 10 seconds'), onPress: () => onSkip(10) }, compact ? 56 : 76)}
        </div>
      )}

      <div className="pc-bottom">
        {filmstrip}

        {tray === 'speed' && (
          <SpeedTray browser={browser} rate={rate} onRate={onRate} focusIndex={focus && focus.zone === 'tray' ? trayIndex : -1} />
        )}

        <div className="pc-line">
          <Scrubber {...scrub} focused={Boolean(focus && focus.zone === 'scrub')} onHover={hover('scrub', 0)} browser={browser} />
        </div>

        {/* Kept in a browser while seeking so the scrubber never resizes under the pointer. */}
        {(!seeking || browser) && (
          <div className="pc-row">
            <div className="pc-group">
              {leftItems.map((item, i) => button('row', i, item, 44))}
              {volume && <Volume {...volume} size={px(44)} />}
              {browser && scrub.duration > 0 && (
                <span className="pc-clock">
                  {scrub.fmtTime(scrub.shown)} / {scrub.fmtTime(scrub.duration)}
                </span>
              )}
            </div>
            {!browser && focus && focus.zone === 'row' && rowItems[focus.index] && (
              <span className="pc-row-name">{rowItems[focus.index].label}</span>
            )}
            <div className="pc-group right">
              {rightItems.map((item, i) => button('row', leftItems.length + i, item, 44))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// On the TV the remaining time shows at the scrubber's end; in a browser the time
// is in the row below.
function Scrubber({
  scrubRef, shown, current, duration, pct, bufPct, seeking, dragging, hover,
  trick, fmtTime, previewWidth, handlers = {}, focused, onHover, browser,
}) {
  return (
    <div className={`pc-progress ${focused ? 'focused' : ''}`}>
      {!browser && (seeking || dragging) && <span className="pc-time">{fmtTime(shown)}</span>}
      <div
        ref={scrubRef}
        className={`pc-scrub ${dragging ? 'dragging' : ''}`}
        onMouseOver={onHover}
        {...handlers}
        role="slider"
        aria-label={t('Seek')}
        aria-valuemin={0}
        aria-valuemax={Math.round(duration)}
        aria-valuenow={Math.round(shown)}
      >
        <div className="pc-rail">
          <div className="pc-buffer" style={{ width: `${bufPct}%` }} />
          <div className="pc-fill" style={{ width: `${pct}%` }} />
        </div>
        {seeking && duration > 0 && shown !== current && (
          <div className="pc-origin" style={{ left: `${(current / duration) * 100}%` }} />
        )}
        <div className="pc-knob" style={{ left: `${pct}%` }} />
        {hover && (
          <ScrubPreview
            manifest={trick}
            time={hover.time}
            left={hover.left}
            label={fmtTime(hover.time)}
            width={browser ? previewWidth : undefined}
          />
        )}
      </div>
      {!browser && <span className="pc-time">{fmtTime(Math.max(0, duration - shown))}</span>}
    </div>
  )
}

function SpeedTray({ browser, rate, onRate, focusIndex }) {
  return (
    <div className="pc-tray">
      <div className="pc-tray-title">{t('Playback Speed')}</div>
      <div className="pc-speeds">
        <div className="pc-speed-line" />
        {SPEEDS.map((value, i) => (
          <button
            type="button"
            key={value}
            className={[
              'pc-speed',
              value === rate ? 'chosen' : '',
              focusIndex === i ? 'focused' : '',
            ].join(' ')}
            onClick={() => onRate(value)}
            aria-label={speedLabel(value)}
          >
            <i />
            <span>{browser || value === rate || focusIndex === i ? speedLabel(value) : ''}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function Volume({ level, muted, setLevel, toggleMute, size }) {
  const icon = muted || level === 0 ? 'volume-mute' : level < 0.5 ? 'volume-low' : 'volume'
  return (
    <div className="pc-volume">
      <button type="button" className="pc-icon" onClick={toggleMute} aria-label={muted ? t('Unmute') : t('Mute')}>
        <Icon name={icon} size={size} />
      </button>
      <input
        type="range"
        min="0"
        max="1"
        step="0.05"
        value={muted ? 0 : level}
        onChange={(e) => setLevel(Number(e.target.value))}
        aria-label={t('Volume')}
        style={{ '--level': `${(muted ? 0 : level) * 100}%` }}
      />
    </div>
  )
}

