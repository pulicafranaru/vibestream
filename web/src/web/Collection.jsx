import { useEffect, useState } from 'react'
import { api } from '../api'
import { GridSkeleton } from './Skeleton'
import Tile from './Tile'

export const genreSlug = (name) =>
  name.toLowerCase().replace(/&/g, 'and').replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')

export function GenrePage({ slug, shell }) {
  const [name, setName] = useState(null)
  const [items, setItems] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setItems(null)
    setError(null)
    // The address carries the slug; the catalog filters by the genre's name.
    api
      .genres()
      .then((genres) => {
        const found = genres.find((g) => genreSlug(g.name) === slug)
        if (!found) throw new Error('There is no such genre in the catalog.')
        if (!alive) return null
        setName(found.name)
        return api.browse({ genre: found.name, sort: 'popular', limit: 120 })
      })
      .then((page) => alive && page && setItems(page.items || []))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [slug])

  return (
    <Collection heading={name} items={items} error={error} shell={shell}
      empty={`Nothing in ${name} yet.`} />
  )
}

export function PersonPage({ personId, shell }) {
  const [person, setPerson] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    setPerson(null)
    setError(null)
    api
      .person(personId)
      .then((data) => alive && setPerson(data))
      .catch((e) => alive && setError(e.message))
    return () => {
      alive = false
    }
  }, [personId])

  return (
    <Collection
      heading={person?.name}
      items={person?.items || null}
      error={error}
      shell={shell}
      empty={`Nothing with ${person?.name} in the catalog yet.`}
    />
  )
}

function Collection({ heading, items, error, shell, empty }) {
  return (
    <div className="page collection">
      <h1 className="page-title collection-title">{heading || ' '}</h1>
      {error && <p className="note error">{error}</p>}
      {!items && !error && <GridSkeleton />}
      {items && !items.length && <p className="note">{empty}</p>}
      {items && items.length > 0 && (
        <div className="grid">
          {items.map((card) => (
            <Tile key={card.media_id ?? card.id} card={card} shell={shell} />
          ))}
        </div>
      )}
    </div>
  )
}
