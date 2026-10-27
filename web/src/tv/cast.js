// The TV side of casting: register with a hello, then long-poll the inbox for commands.

const ID_KEY = 'vs.castId'
const TOKEN_KEY = 'vs.castToken'
const WAIT = 25

function stored(key) {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function store(key, value) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    // Not saved: kept for this launch only.
  }
}

function newId() {
  const id = `tv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`
  store(ID_KEY, id)
  return id
}

function deviceName() {
  const raw = (window.webOSSystem && window.webOSSystem.deviceInfo) ||
    (window.PalmSystem && window.PalmSystem.deviceInfo)
  const info = (() => {
    try {
      return typeof raw === 'string' ? JSON.parse(raw) : raw || {}
    } catch {
      return {}
    }
  })()
  const model = info.modelName || info.modelNameAscii
  return model ? `LG ${model}` : 'TV'
}

let ID = stored(ID_KEY) || newId()
let token = stored(TOKEN_KEY)

function forgetDevice() {
  ID = newId()
  token = null
  store(TOKEN_KEY, null)
}

const castHeaders = (extra) => {
  const headers = {}
  if (token) headers['X-Cast-Token'] = token
  return Object.assign(headers, extra)
}

const post = (path, body, extra) =>
  fetch(`/api/cast/${path}`, {
    method: 'POST',
    headers: castHeaders(Object.assign({ 'Content-Type': 'application/json' }, extra)),
    body: JSON.stringify(body),
  })

const controls = new Set()

export function onCastControl(fn) {
  controls.add(fn)
  return () => controls.delete(fn)
}

let lastState = ''
export function reportCastState(playing) {
  const body = JSON.stringify(playing)
  if (body === lastState) return
  lastState = body
  post('state', { id: ID, playing }).catch(() => {})
}

// One inbox poll for the app's lifetime: the inbox is per device, so a second poll would steal and drop commands.
let wanted = null // { profileId, onPlay } while listening
let greeted = null // the `wanted` the server last heard a hello for
let looping = false

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

// A PIN just entered for a profile, sent once with the next hello; the server remembers the device after that.
let pin = null // { profileId, value }

export function castPin(profileId, value) {
  pin = { profileId, value }
  if (looping && wanted && wanted.profileId === profileId) greet(wanted).catch(() => {})
}

async function hello(as, retried) {
  const sent = pin && pin.profileId === as.profileId ? pin : null
  const r = await post(
    'hello',
    { id: ID, name: deviceName(), kind: 'tv', profile_id: as.profileId },
    sent ? { 'X-Profile-Pin': sent.value } : null,
  )
  if (sent && pin === sent && r.status !== 200) {
    pin = null
    if (!retried) return hello(as, true)
  } else if (r.status === 403 && !retried) {
    forgetDevice()
    return hello(as, true)
  }
  if (!r.ok) throw new Error('hello refused')
  const data = await r.json()
  if (data.token && data.token !== token) {
    token = data.token
    store(TOKEN_KEY, token)
  }
  if (sent && pin === sent) pin = null
}

function greet(as) {
  greeted = as
  return hello(as, false).catch((e) => {
    if (greeted === as) greeted = null
    throw e
  })
}

async function listen() {
  looping = true
  while (wanted) {
    const as = wanted
    try {
      if (greeted !== as) await greet(as)
      const res = await fetch(`/api/cast/inbox?id=${encodeURIComponent(ID)}&wait=${WAIT}`, {
        headers: castHeaders(),
      })
      if (res.status === 404 || res.status === 403) {
        greeted = null
        continue
      }
      if (!res.ok) throw new Error(`inbox ${res.status}`)
      const { commands = [] } = await res.json()
      const to = wanted || as
      commands.forEach((command) => {
        if (command.type === 'play') to.onPlay(command)
        else controls.forEach((fn) => fn(command))
      })
    } catch {
      await sleep(5000)
    }
  }
  looping = false
}

export function startCast(profileId, onPlay) {
  wanted = { profileId, onPlay }
  if (looping) greet(wanted).catch(() => {})
  else listen()
}

export function stopCast() {
  wanted = null
}
