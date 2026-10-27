/** Profile avatars: an id like "emerald-wink" names a gradient and a face. */

import art from './avatar-art.js'

export const AVATAR_COLOURS = art.colours

export const AVATAR_FACES = Object.keys(art.faces)

export default function Avatar({ id = 'crimson-smile', size = 120 }) {
  const [colour, face] = String(id).split('-')
  const pair = AVATAR_COLOURS[colour] || AVATAR_COLOURS.crimson
  const paths = art.faces[face] || art.faces[AVATAR_FACES[0]]
  const gradientId = `av-${colour}-${face}`

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 100 100"
      aria-hidden="true"
      focusable="false"
      style={{ display: 'block', borderRadius: '50%' }}
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={pair[0]} />
          <stop offset="100%" stopColor={pair[1]} />
        </linearGradient>
      </defs>
      <circle cx="50" cy="50" r="50" fill={`url(#${gradientId})`} />
      {paths.map((p, i) => (
        <path
          key={i}
          d={p.d}
          fill={p.fill || 'none'}
          stroke={p.stroke}
          strokeWidth={p['stroke-width']}
          strokeLinecap={p['stroke-linecap']}
        />
      ))}
    </svg>
  )
}

export function allAvatars() {
  const out = []
  for (const colour of Object.keys(AVATAR_COLOURS)) {
    for (const face of AVATAR_FACES) out.push(`${colour}-${face}`)
  }
  return out
}
