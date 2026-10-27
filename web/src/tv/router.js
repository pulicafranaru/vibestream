// A tiny History API router: react-router is too heavy for the webOS browser.

export const SECTION_PATHS = {
  home: '/',
  movies: '/movies',
  shows: '/shows',
  library: '/library',
}

// Mount point (/tv or /legacy/tv); every path the router reads or writes is relative to it.
let base = ''

export function setBase(value) {
  base = (value || '').replace(/\/+$/, '')
}

export function parseLocation(pathname = window.location.pathname) {
  let path = pathname
  if (base && (path === base || path.indexOf(`${base}/`) === 0)) {
    path = path.slice(base.length) || '/'
  }
  const parts = path.replace(/\/+$/, '').split('/').filter(Boolean)

  if (!parts.length) return { screen: 'home', section: 'home' }

  const [head, arg] = parts

  if (head === 'search') return { screen: 'search', section: 'home' }
  if (head === 'downloads') return { screen: 'downloads', section: 'library' }
  if (head === 'debug') return { screen: 'debug', section: 'home' }
  // Old address for the library page.
  if (head === 'mine') return { screen: 'home', section: 'library' }
  if (head === 'category' && arg) {
    return { screen: 'category', section: 'home', genre: decodeURIComponent(arg) }
  }
  if (head === 'title' && arg) {
    return { screen: 'detail', section: 'home', mediaId: Number(arg) }
  }
  if (head === 'watch' && arg) {
    return { screen: 'player', section: 'home', playId: arg }
  }
  for (const [section, path] of Object.entries(SECTION_PATHS)) {
    if (path === `/${head}`) return { screen: 'home', section }
  }
  return { screen: 'home', section: 'home' }
}

export function buildPath(state) {
  return `${base}${_path(state)}` || '/'
}

function _path(state) {
  if (state.screen === 'search') return '/search'
  if (state.screen === 'downloads') return '/downloads'
  if (state.screen === 'debug') return '/debug'
  if (state.screen === 'category' && state.genre) {
    return `/category/${encodeURIComponent(state.genre)}`
  }
  if (state.screen === 'detail' && state.mediaId) return `/title/${state.mediaId}`
  if (state.screen === 'player' && state.playId) return `/watch/${state.playId}`
  return SECTION_PATHS[state.section] || '/'
}

// Skips no-op pushes, which would stack duplicate entries and make Back appear to do nothing.
export function navigate(state, { replace = false } = {}) {
  const path = buildPath(state)
  if (path === window.location.pathname) return
  if (replace) window.history.replaceState(state, '', path)
  else window.history.pushState(state, '', path)
}

export function onRouteChange(handler) {
  const listener = () => handler(parseLocation())
  window.addEventListener('popstate', listener)
  return () => window.removeEventListener('popstate', listener)
}
