/** Subtitle appearance: size and style. */

export const SUBTITLE_SIZES = [
  { id: 'small', label: 'Small', scale: 0.75 },
  { id: 'medium', label: 'Medium', scale: 1 },
  { id: 'large', label: 'Large', scale: 1.4 },
]

export const SUBTITLE_STYLES = [
  { id: 'shadow', label: 'Drop Shadow' },
  { id: 'outline', label: 'Outline' },
  { id: 'yellow', label: 'Yellow' },
  { id: 'boxed', label: 'Boxed' },
]

const STORAGE_KEY = 'vibestream.subtitle.appearance'
export const DEFAULT_APPEARANCE = { size: 'medium', style: 'shadow' }

export function loadAppearance() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) return { ...DEFAULT_APPEARANCE, ...JSON.parse(raw) }
  } catch {
    /* storage can be unavailable on a TV; fall through to defaults */
  }
  return { ...DEFAULT_APPEARANCE }
}

export function saveAppearance(appearance) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance))
  } catch {
    /* not fatal, the choice just will not persist */
  }
}

// Fraction of picture height above its bottom edge. WebVTT's default sits at the
// bottom of the element, inside the letterbox bar.
export const SUBTITLE_BOTTOM_RATIO = 0.08

/** Rendered cue size in pixels, sized for a 1080p TV. */
export function cueFontSize(size) {
  const scale = (SUBTITLE_SIZES.find((s) => s.id === size) || SUBTITLE_SIZES[1]).scale
  return Math.round(34 * scale)
}

export function previewStyle({ size, style }, base = 30) {
  const scale = (SUBTITLE_SIZES.find((s) => s.id === size) || SUBTITLE_SIZES[1]).scale
  const shared = { fontSize: Math.round(base * scale), fontWeight: 700 }
  switch (style) {
    case 'outline':
      return {
        ...shared,
        color: '#fff',
        textShadow:
          '-2px -2px 0 #000, 2px -2px 0 #000, -2px 2px 0 #000, 2px 2px 0 #000',
      }
    case 'yellow':
      return {
        ...shared,
        color: '#f5d020',
        textShadow: '0 2px 4px rgba(0,0,0,.9)',
      }
    case 'boxed':
      return {
        ...shared,
        color: '#fff',
        background: 'rgba(0,0,0,.75)',
        padding: '2px 10px',
        borderRadius: 4,
      }
    default:
      return {
        ...shared,
        color: '#fff',
        textShadow: '0 2px 4px rgba(0,0,0,.9), 0 0 8px rgba(0,0,0,.7)',
      }
  }
}
