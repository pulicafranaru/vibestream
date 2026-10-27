// Recent remote input events for the Debug screen, kept in localStorage. Nothing is sent anywhere.

const KEY = 'vs.inputLog'
const MAX = 200
let entries = []

try {
  entries = JSON.parse(localStorage.getItem(KEY) || '[]')
} catch {
  entries = []
}

export function logInput(what) {
  entries.push({ at: Date.now(), what })
  if (entries.length > MAX) entries = entries.slice(-MAX)
  try {
    localStorage.setItem(KEY, JSON.stringify(entries))
  } catch {
    /* kept in memory only */
  }
}

export function inputLog() {
  return entries.slice()
}

let started = false

export function startInputLog() {
  if (started) return
  started = true
  window.addEventListener('keydown', (e) => logInput(`keydown ${e.keyCode || e.which}${e.repeat ? ' repeat' : ''}`), true)
  window.addEventListener('keyup', (e) => logInput(`keyup ${e.keyCode || e.which}`), true)
  window.addEventListener('popstate', () => logInput('popstate'), true)
  // webOS: the Magic Remote's pointer appearing and going.
  document.addEventListener('cursorStateChange', (e) => {
    const visible = e && e.detail && e.detail.visibility
    logInput(`pointer ${visible ? 'shown' : 'hidden'}`)
  })
  // Some sets never send cursorStateChange, but a visible pointer always moves the mouse.
  let lastMove = 0
  window.addEventListener('mousemove', () => {
    if (Date.now() - lastMove < 1000) return
    lastMove = Date.now()
    logInput('pointer moving')
  }, true)
  window.addEventListener('mousedown', (e) => logInput(`mousedown ${e.button}`), true)
  window.addEventListener('blur', () => logInput('window lost focus'))
  window.addEventListener('focus', () => logInput('window got focus'))
  // A frame more than 250 ms after the last while visible means the page stalled.
  let lastFrame = 0
  const frame = (now) => {
    if (lastFrame && !document.hidden && now - lastFrame > 250) {
      logInput(`page stuck ${Math.round(now - lastFrame)} ms`)
    }
    lastFrame = now
    requestAnimationFrame(frame)
  }
  requestAnimationFrame(frame)
  document.addEventListener('visibilitychange', () => logInput(`page ${document.hidden ? 'hidden' : 'shown'}`))
}
