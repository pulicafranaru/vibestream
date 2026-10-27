import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { GridSkeleton } from './Skeleton'
import Tile from './Tile'

const SORTS = [
  { id: 'added', label: 'Recently Added' },
  { id: 'title', label: 'A to Z' },
  { id: 'year', label: 'Release Year' },
]

export default function MyList({ shell }) {
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)
  const [kind, setKind] = useState(null)
  const [started, setStarted] = useState(null)
  const [sort, setSort] = useState('added')

  const size = shell.myList.size
  useEffect(() => {
    let alive = true
    api
      .myListPage()
      .then((data) => alive && setItems(data.items || []))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
    // Refetched on add; a removal only needs filtering, below.
  }, [size, shell.profile])

  const shown = useMemo(() => {
    const list = (items || []).filter(
      (card) =>
        shell.myList.has(card.media_id) &&
        (!kind || card.media_type === kind) &&
        (started === null || Boolean(card.started) === started),
    )
    if (sort === 'title') return [...list].sort((a, b) => a.title.localeCompare(b.title))
    if (sort === 'year') return [...list].sort((a, b) => (b.year || 0) - (a.year || 0))
    return list
  }, [items, shell.myList, kind, started, sort])

  const chip = (label, on, onClick) => (
    <button className={`filter-chip${on ? ' on' : ''}`} onClick={onClick}>
      {label}
    </button>
  )

  return (
    <div className="page my-list">
      <a
        href="/library"
        className="crumb"
        onClick={(e) => {
          e.preventDefault()
          shell.go({ screen: 'home', section: 'library' })
        }}
      >
        ‹ Library
      </a>
      <h1 className="page-title">Watchlist</h1>

      <div className="my-list-controls">
        <div className="filter-chips">
          {chip('TV Shows', kind === 'tv', () => setKind(kind === 'tv' ? null : 'tv'))}
          {chip('Movies', kind === 'movie', () => setKind(kind === 'movie' ? null : 'movie'))}
          {chip("Haven't Started", started === false, () => setStarted(started === false ? null : false))}
          {chip('Started', started === true, () => setStarted(started === true ? null : true))}
        </div>
        <label className="sort-by">
          <span>Sort By</span>
          <select value={sort} onChange={(e) => setSort(e.target.value)}>
            {SORTS.map((s) => (
              <option key={s.id} value={s.id}>{s.label}</option>
            ))}
          </select>
        </label>
      </div>

      {error && <p className="note error">{error}</p>}
      {!items && !error && <GridSkeleton />}
      {items && !shown.length && (
        <p className="note">
          {items.length
            ? 'Nothing on your list matches these filters.'
            : 'Your list is empty. Press the + on any title to save it here for later.'}
        </p>
      )}

      <div className="grid my-list-grid">
        {shown.map((card) => (
          <Tile
            key={card.media_id}
            card={card}
            shell={shell}
          />
        ))}
      </div>
    </div>
  )
}
