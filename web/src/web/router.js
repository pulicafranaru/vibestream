export const SECTIONS = [
  { id: 'home', path: '/', label: 'Home', mediaType: null },
  { id: 'shows', path: '/shows', label: 'Shows', mediaType: 'tv' },
  { id: 'movies', path: '/movies', label: 'Movies', mediaType: 'movie' },
  { id: 'library', path: '/library', label: 'Library', mediaType: null },
  { id: 'mylist', path: '/my-list', label: 'Watchlist', mediaType: null, parent: 'library' },
]

export function parseLocation(loc = window.location) {
  const parts = loc.pathname.replace(/\/+$/, '').split('/').filter(Boolean)
  const params = new URLSearchParams(loc.search)
  const [head, arg] = parts

  if (!head) return { screen: 'home', section: 'home' }
  if (head === 'search') {
    return { screen: 'search', section: 'home', query: params.get('q') || '' }
  }
  if (head === 'downloads') return { screen: 'downloads', section: 'library' }
  if (head === 'notifications') return { screen: 'notifications', section: 'home' }
  if (head === 'title' && arg) {
    // The page the title was opened over, kept in the history entry so Back
    // and Forward restore it behind the title. A cold link has none: Home.
    const background = window.history.state?.background || null
    // Titles deep: 1 over the page, +1 per title opened from another.
    const depth = window.history.state?.depth || 1
    // ?play=: playing inside the title's own picture.
    return {
      screen: 'detail', section: 'home', mediaId: Number(arg), background, depth,
      play: params.get('play') || null,
    }
  }
  if (head === 'browse' && arg === 'genre' && parts[2]) {
    return { screen: 'genre', section: 'home', slug: parts[2] }
  }
  if (head === 'browse' && arg === 'person' && parts[2]) {
    return { screen: 'person', section: 'home', personId: Number(parts[2]) }
  }
  if (head === 'watch' && arg) {
    return { screen: 'player', section: 'home', playId: arg }
  }
  const section = SECTIONS.find((s) => s.path === `/${head}`)
  if (section) return { screen: 'home', section: section.id }
  return { screen: 'home', section: 'home' }
}

export function buildPath(state) {
  if (state.screen === 'search') {
    return state.query ? `/search?q=${encodeURIComponent(state.query)}` : '/search'
  }
  if (state.screen === 'downloads') return '/downloads'
  if (state.screen === 'notifications') return '/notifications'
  if (state.screen === 'detail' && state.mediaId) {
    return `/title/${state.mediaId}${state.play ? `?play=${encodeURIComponent(state.play)}` : ''}`
  }
  if (state.screen === 'player' && state.playId) return `/watch/${state.playId}`
  if (state.screen === 'genre' && state.slug) return `/browse/genre/${state.slug}`
  if (state.screen === 'person' && state.personId) return `/browse/person/${state.personId}`
  const section = SECTIONS.find((s) => s.id === state.section)
  return section ? section.path : '/'
}

export function navigate(state, { replace = false } = {}) {
  const path = buildPath(state)
  const current = `${window.location.pathname}${window.location.search}`
  if (path === current) return
  if (replace) window.history.replaceState(state, '', path)
  else window.history.pushState(state, '', path)
}

export function onRouteChange(handler) {
  const listener = () => handler(parseLocation())
  window.addEventListener('popstate', listener)
  return () => window.removeEventListener('popstate', listener)
}

export function sectionFor(id) {
  return SECTIONS.find((s) => s.id === id) || SECTIONS[0]
}
