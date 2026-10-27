/** The dash offset is transitioned, not animated from JS, which stutters on webOS. */
export default function ProgressRing({
  percent = 0,
  size = 56,
  stroke = 4,
  label = null,
  tone = 'accent',
  indeterminate = false,
}) {
  const clamped = Math.max(0, Math.min(100, percent || 0))
  const radius = (size - stroke) / 2
  const circumference = 2 * Math.PI * radius
  const offset = circumference * (1 - clamped / 100)

  // No label while indeterminate.
  const showLabel = label !== null && label !== undefined && !indeterminate

  return (
    <div
      className={`ring ring-${tone} ${indeterminate ? 'ring-spin' : ''}`}
      style={{ width: size, height: size }}
    >
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        <circle
          className="ring-track"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          fill="none"
        />
        <circle
          className="ring-fill"
          cx={size / 2}
          cy={size / 2}
          r={radius}
          strokeWidth={stroke}
          fill="none"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={indeterminate ? circumference * 0.75 : offset}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      {showLabel && <span className="ring-label">{label}</span>}
    </div>
  )
}
