import { useEffect, useState } from 'react'
import { api } from '../api'
import Tile from './Tile'

export default function Search({ query, onQuery, shell }) {
  const [results, setResults] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)
  const [suggested, setSuggested] = useState([])

  useEffect(() => {
    let alive = true
    api.home()
      .then((feed) => {
        if (!alive) return
        const seen = new Set()
        const cards = (feed.rows || [])
          .filter((row) => row.kind !== 'continue')
          .flatMap((row) => row.items || [])
          .filter((card) => {
            const id = card.media_id ?? card.id
            if (seen.has(id)) return false
            seen.add(id)
            return true
          })
        setSuggested(cards.slice(0, 30))
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [])

  useEffect(() => {
    const term = (query || '').trim()
    if (!term) {
      setResults([])
      setLoading(false)
      return undefined
    }
    let alive = true
    // Clear the last answer as soon as the query changes: a tracker search takes
    // seconds, and the old results read as the answer to the new query.
    setResults([])
    setLoading(true)
    setError(null)
    api
      .browse({ q: term, limit: 60 })
      .then((data) => {
        if (!alive) return
        setResults(data.items || [])
      })
      .catch((e) => alive && setError(e.message))
      .finally(() => alive && setLoading(false))
    return () => {
      alive = false
    }
  }, [query])

  const term = (query || '').trim()

  return (
    <div className="page">
      <h1 className="page-title">
        {term ? `Results for “${term}”` : 'Recommended TV Shows & Movies'}
        {loading && <span className="spinner inline" />}
      </h1>

      {error && <p className="note error">{error}</p>}

      {term && !loading && !results.length && !error && (
        <p className="note">
          Nothing for “{term}”, here or on the tracker.{' '}
          <button className="link" onClick={() => onQuery('')}>Clear</button>
        </p>
      )}

      <div className="grid">
        {(term ? results : suggested).map((card) => (
          <Tile
            key={card.media_id ?? card.id}
            card={card}
            shell={shell}
          />
        ))}
      </div>
    </div>
  )
}
