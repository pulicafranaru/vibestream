// Keys and input mode. Mode is tracked per event, not detected once: an LG Magic
// Remote is both a pointer and a D-pad.

import { useEffect, useState } from 'react'

export const KEY = {
  LEFT: 37,
  UP: 38,
  RIGHT: 39,
  DOWN: 40,
  ENTER: 13,
  // webOS remote Back.
  BACK: 461,
  BACKSPACE: 8,
  ESCAPE: 27,
  SPACE: 32,
  PLAY: 415,
  PAUSE: 19,
  STOP: 413,
  REWIND: 412,
  FORWARD: 417,
}

let inputMode_ = 'pointer'
const inputListeners = new Set()

export function setInputMode(next) {
  if (next === inputMode_) return
  inputMode_ = next
  inputListeners.forEach((fn) => fn(next))
}

export function inputMode() {
  return inputMode_
}

export function useInputMode() {
  const [mode, setMode] = useState(inputMode_)
  useEffect(() => {
    inputListeners.add(setMode)
    setMode(inputMode_)
    return () => inputListeners.delete(setMode)
  }, [])
  return mode
}

export function keyName(event) {
  const code = event.keyCode || event.which
  switch (code) {
    case KEY.LEFT:
      return 'left'
    case KEY.UP:
      return 'up'
    case KEY.RIGHT:
      return 'right'
    case KEY.DOWN:
      return 'down'
    case KEY.ENTER:
      return 'enter'
    case KEY.BACK:
    case KEY.BACKSPACE:
    case KEY.ESCAPE:
      return 'back'
    case KEY.PLAY:
      return 'play'
    case KEY.PAUSE:
      return 'pause'
    case KEY.STOP:
      return 'stop'
    case KEY.REWIND:
      return 'rewind'
    case KEY.FORWARD:
      return 'forward'
    default:
      if (code >= 48 && code <= 57) return `digit${code - 48}`
      if (code >= 96 && code <= 105) return `digit${code - 96}`
      return null
  }
}

// Drops key repeats faster than the UI can answer: a minimum gap, and nothing
// new until the last press has been drawn.
export function createKeyGate(intervalMs = 90) {
  let last = 0
  // Otherwise a slow TV queues presses and keeps moving after the key is released.
  let drawing = false
  let fallback = 0
  const drawn = () => {
    drawing = false
    clearTimeout(fallback)
  }
  return function allow() {
    const now = Date.now()
    if (drawing || now - last < intervalMs) return false
    last = now
    drawing = true
    requestAnimationFrame(() => requestAnimationFrame(drawn))
    // rAF stops while the page is hidden; a press must never stay blocked.
    fallback = setTimeout(drawn, 300)
    return true
  }
}
