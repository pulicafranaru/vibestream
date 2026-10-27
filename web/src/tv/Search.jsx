import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import TopNav, { NAV_ITEMS, navIndexOf } from './TopNav'
import { BackspaceIcon, Icon } from './icons'
import { genreName, t } from '../shared/i18n'
import { scrollPageTo } from './navigation'
import { tilePoster } from './images'

const KEYS = 'abcdefghijklmnopqrstuvwxyz1234567890'.split('')
const SPACE = { id: 'space', wide: true }
const DELETE = { id: 'delete', wide: true }
const GRID = [SPACE, DELETE, ...KEYS.map((k) => ({ id: k, label: k }))]
const COLS = 6
const WIDE_SPAN = COLS / 2

function cellOf(index) {
  if (index < 2) return { row: 0, col: index * WIDE_SPAN, span: WIDE_SPAN }
  const offset = index - 2
  return { row: Math.floor(offset / COLS) + 1, col: offset % COLS, span: 1 }
}

function indexAt(row, col) {
  if (row <= 0) return col < WIDE_SPAN ? 0 : 1
  return Math.min(2 + (row - 1) * COLS + col, GRID.length - 1)
}

const LAST_ROW = cellOf(GRID.length - 1).row
const PER_ROW = 4
const LIST_LENGTH = 8

const memory = { query: '', results: [], fetchedFor: '', pane: 'keyboard', keyIndex: 2, resultIndex: 0, listIndex: 0 }

export default function Search({ profile, onNav, onOpen, onGenre, onClose, registerHandler, suggestions = [], genres = [] }) {
  const [query, setQuery] = useState(memory.query)
  const [results, setResults] = useState(memory.results)
  const [loading, setLoading] = useState(false)
  const [pane, setPane] = useState(memory.pane) // nav | keyboard | list | results
  const [navCol, setNavCol] = useState(navIndexOf('search'))
  const [keyIndex, setKeyIndex] = useState(memory.keyIndex)
  const [listIndex, setListIndex] = useState(memory.listIndex)
  const [resultIndex, setResultIndex] = useState(memory.resultIndex)
  const timer = useRef(null)
  const resultsRef = useRef(null)
  const resultRefs = useRef({})

  useEffect(() => {
    clearTimeout(timer.current)
    if (!query.trim()) {
      setResults([])
      setLoading(false)
      memory.fetchedFor = ''
      return undefined
    }
    if (query === memory.fetchedFor) {
      setLoading(false)
      return undefined
    }
    // Clear the last answer at once, and drop answers that arrive after the query changed.
    let alive = true
    setResults([])
    memory.fetchedFor = ''
    setLoading(true)
    timer.current = setTimeout(() => {
      api
        .browse({ q: query, limit: 40 })
        .then((data) => {
          if (!alive) return
          setResults(data.items || [])
          setResultIndex(0)
          setListIndex(0)
          memory.fetchedFor = query
        })
        .catch(() => alive && setResults([]))
        .finally(() => alive && setLoading(false))
    }, 350)
    return () => {
      alive = false
      clearTimeout(timer.current)
    }
  }, [query])

  useEffect(() => {
    Object.assign(memory, { query, results, pane: pane === 'nav' ? 'keyboard' : pane, keyIndex, resultIndex, listIndex })
  }, [query, results, pane, keyIndex, resultIndex, listIndex])

  const typed = Boolean(query.trim())
  const showing = typed ? results : suggestions
  const list = typed
    ? results.slice(0, LIST_LENGTH).map((card) => ({ id: `t${card.media_id}`, label: card.title, card }))
    : genres.slice(0, LIST_LENGTH).map((g) => ({ id: `g${g.name}`, label: genreName(g.name), genre: g.name }))

  useEffect(() => {
    if (pane !== 'results') return
    scrollPageTo(resultsRef.current, resultRefs.current[resultIndex], { offset: 24 })
  }, [pane, resultIndex, showing])

  const press = useCallback((item) => {
    if (item.id === 'space') setQuery((q) => `${q} `)
    else if (item.id === 'delete') setQuery((q) => q.slice(0, -1))
    else setQuery((q) => q + item.id)
  }, [])

  const pick = useCallback((entry) => {
    if (!entry) return
    if (entry.card) onOpen(entry.card)
    else if (entry.genre) onGenre(entry.genre)
  }, [onOpen, onGenre])

  useEffect(() => {
    registerHandler({
      onDirection: (dir) => {
        if (pane === 'nav') {
          if (dir === 'left') setNavCol((c) => Math.max(0, c - 1))
          if (dir === 'right') setNavCol((c) => Math.min(NAV_ITEMS.length - 1, c + 1))
          if (dir === 'down') setPane('keyboard')
          return
        }
        if (pane === 'keyboard') {
          const cell = cellOf(keyIndex)
          if (dir === 'right') {
            if (cell.col + cell.span > COLS - 1) {
              if (showing.length) setPane('results')
              return
            }
            setKeyIndex(indexAt(cell.row, cell.col + cell.span))
          } else if (dir === 'left') {
            if (cell.col > 0) setKeyIndex(indexAt(cell.row, cell.col - 1))
          } else if (dir === 'down') {
            if (cell.row < LAST_ROW) setKeyIndex(indexAt(cell.row + 1, cell.col))
            else if (list.length) {
              setPane('list')
              setListIndex(0)
            }
          } else if (dir === 'up') {
            if (cell.row > 0) setKeyIndex(indexAt(cell.row - 1, cell.col))
            else {
              setPane('nav')
              setNavCol(navIndexOf('search'))
            }
          }
          return
        }
        if (pane === 'list') {
          if (dir === 'down') setListIndex((i) => Math.min(list.length - 1, i + 1))
          if (dir === 'up') {
            if (listIndex === 0) setPane('keyboard')
            else setListIndex((i) => i - 1)
          }
          if (dir === 'right' && showing.length) setPane('results')
          return
        }
        if (dir === 'left') {
          if (resultIndex % PER_ROW === 0) setPane('keyboard')
          else setResultIndex((i) => i - 1)
          return
        }
        if (dir === 'right') setResultIndex((i) => Math.min(showing.length - 1, i + 1))
        if (dir === 'down') setResultIndex((i) => Math.min(showing.length - 1, i + PER_ROW))
        if (dir === 'up') {
          if (resultIndex >= PER_ROW) setResultIndex((i) => i - PER_ROW)
          else {
            setPane('nav')
            setNavCol(navIndexOf('search'))
          }
        }
      },
      onEnter: () => {
        if (pane === 'nav') {
          const id = NAV_ITEMS[navCol].id
          if (id === 'search') setPane('keyboard')
          else onNav(id)
          return
        }
        if (pane === 'keyboard') {
          press(GRID[keyIndex])
          return
        }
        if (pane === 'list') {
          pick(list[listIndex])
          return
        }
        const card = showing[resultIndex]
        if (card) onOpen(card)
      },
      onBack: () => {
        if (pane === 'results' || pane === 'list') {
          setPane('keyboard')
          return true
        }
        if (pane === 'nav') {
          setPane('keyboard')
          return true
        }
        if (query) {
          setQuery((q) => q.slice(0, -1))
          return true
        }
        onClose()
        return true
      },
    })
  }, [registerHandler, pane, navCol, keyIndex, listIndex, resultIndex, showing, list, query, press,
    pick, onOpen, onNav, onClose])

  return (
    <>
      <TopNav
        active="search"
        focused={pane === 'nav' ? navCol : null}
        profile={profile}
        onHover={(i) => {
          setPane('nav')
          setNavCol(i)
        }}
        onActivate={(i) => onNav(NAV_ITEMS[i].id)}
      />
      <div className="search">
        <div className="search-side">
          <div className="kb-grid">
            {GRID.map((item, i) => (
              <div
                key={item.id}
                aria-label={item.id === 'space' ? t('Space') : item.id === 'delete' ? t('Delete') : undefined}
                className={['kb-key', item.wide ? 'wide' : '', pane === 'keyboard' && keyIndex === i ? 'focused' : ''].join(' ')}
                onMouseEnter={() => {
                  setPane('keyboard')
                  setKeyIndex(i)
                }}
                onClick={() => press(item)}
              >
                {item.id === 'space' ? <span className="kb-space" /> : item.id === 'delete' ? <BackspaceIcon size={26} /> : item.label}
              </div>
            ))}
          </div>
          <div className="search-list">
            {list.map((entry, i) => (
              <div
                key={entry.id}
                className={`search-list-item ${pane === 'list' && listIndex === i ? 'focused' : ''}`}
                onMouseEnter={() => {
                  setPane('list')
                  setListIndex(i)
                }}
                onClick={() => pick(entry)}
              >
                {entry.label}
              </div>
            ))}
          </div>
        </div>

        <div className="search-results" ref={resultsRef}>
          <h2 className="search-heading">
            {typed ? (
              <>
                <Icon name="search" size={28} />
                <span>{query}</span>
              </>
            ) : (
              t('Your Search Recommendations')
            )}
          </h2>
          {typed && !loading && results.length === 0 && (
            <div className="empty-note">{t('Nothing found for “{q}”', { q: query.trim() })}</div>
          )}
          {typed && loading && results.length === 0 && <div className="empty-note">{t('Searching...')}</div>}
          <div className="result-grid">
            {showing.map((card, i) => (
              <div
                key={card.media_id || card.primary_release_id}
                ref={(el) => { resultRefs.current[i] = el }}
                className={`tile result ${pane === 'results' && resultIndex === i ? 'focused' : ''}`}
                onMouseEnter={() => {
                  setPane('results')
                  setResultIndex(i)
                }}
                onClick={() => onOpen(card)}
              >
                {card.poster ? <img src={tilePoster(card.poster)} alt="" /> : <div className="tile-fallback">{card.title}</div>}
              </div>
            ))}
          </div>
          <div className="list-spacer" />
        </div>
      </div>
    </>
  )
}
