// TMDB serves every size from the same path, so artwork is fetched at the size the TV tile draws.
const TMDB_SIZE = /(\/t\/p\/)(w\d+|original)\//

function sized(url, size) {
  return url && TMDB_SIZE.test(url) ? url.replace(TMDB_SIZE, `$1${size}/`) : url
}

export const tilePoster = (url) => sized(url, 'w342')

export const tileLogo = (url) => sized(url, 'w300')
