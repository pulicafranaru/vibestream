// D-pad focus management as rows of horizontal strips, rather than spatial navigation, which is slow on webOS.

import { KEY, inputMode, keyName, setInputMode, useInputMode } from '../shared/input'

export { KEY, inputMode, keyName, setInputMode, useInputMode }
export { createKeyGate } from '../shared/input'

export function clamp(index, length) {
  if (length <= 0) return null
  if (index < 0) return 0
  if (index >= length) return length - 1
  return index
}

// Rects, not offsetTop/offsetLeft, which are relative to the nearest positioned ancestor rather than the scroller.
function offsetWithin(container, element) {
  const box = container.getBoundingClientRect()
  const target = element.getBoundingClientRect()
  return {
    top: target.top - box.top + container.scrollTop,
    left: target.left - box.left + container.scrollLeft,
  }
}

const clampScroll = (value, max) => Math.max(0, Math.min(value, Math.max(0, max)))

export function scrollRowTo(container, element, { offset = 96 } = {}) {
  if (!container || !element) return
  const target = clampScroll(
    offsetWithin(container, element).left - offset,
    container.scrollWidth - container.clientWidth,
  )
  if (Math.abs(container.scrollLeft - target) < 2) return
  container.scrollLeft = target
}

export function scrollPageTo(container, element, { offset, animate = false } = {}) {
  if (!container || !element) return
  const margin = offset ?? Math.max(
    96,
    (container.clientHeight - element.offsetHeight) / 2,
  )
  // Mid-slide the content is drawn displaced; the slide still to run is taken back out.
  const target = clampScroll(
    offsetWithin(container, element).top - slideLeft(container) - margin,
    container.scrollHeight - container.clientHeight,
  )
  setPageScroll(container, target, { animate })
}

const SLIDE_MS = 320

function slideLeft(container) {
  const first = container.firstElementChild
  if (!first || !first.style.transform) return 0
  const matrix = getComputedStyle(first).transform
  const parts = matrix && matrix !== 'none' ? matrix.slice(matrix.indexOf('(') + 1, -1).split(',') : []
  return parts.length === 6 ? parseFloat(parts[5]) || 0 : 0
}

// Jumps at once, then slides the content into place with a transform: smooth scrolling stutters on webOS.
export function setPageScroll(container, target, { animate = false } = {}) {
  if (!container) return
  const from = container.scrollTop
  if (Math.abs(from - target) < 2) return
  container.scrollTop = target
  if (!animate) return
  const moved = container.scrollTop - from
  if (!moved) return
  const start = moved + slideLeft(container)
  const kids = Array.prototype.slice.call(container.children)
  kids.forEach((kid) => {
    kid.style.transition = 'none'
    kid.style.transform = `translateY(${start}px)`
  })
  void container.offsetHeight
  kids.forEach((kid) => {
    kid.style.transition = `transform ${SLIDE_MS}ms cubic-bezier(0.25, 0.8, 0.3, 1)`
    kid.style.transform = 'translateY(0px)'
  })
  clearTimeout(container.slideTimer)
  container.slideTimer = setTimeout(() => {
    kids.forEach((kid) => {
      kid.style.transition = ''
      kid.style.transform = ''
    })
  }, SLIDE_MS + 40)
}
