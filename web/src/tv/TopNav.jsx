import { useEffect, useRef } from 'react'
import Avatar from './Avatar'
import { Icon, SearchIcon } from './icons'
import { BellIcon, DownloadIcon } from '../shared/icons'
import { t } from '../shared/i18n'
import { VMark } from '../shared/brand'
import { ago, useNotes } from './notes'

// Presentational only: the screen that shows the bar owns its focus (row -1), since only it knows what Down lands on.
export const NAV_ITEMS = [
  { id: 'home', label: 'Home' },
  { id: 'shows', label: 'Shows' },
  { id: 'movies', label: 'Movies' },
  { id: 'library', label: 'Library' },
  { id: 'search' },
  { id: 'downloads' },
  { id: 'bell' },
  { id: 'profile' },
]

export function navIndexOf(id) {
  const at = NAV_ITEMS.findIndex((item) => item.id === id)
  return at >= 0 ? at : 0
}

export default function TopNav({ active, focused = null, profile, onHover, onActivate, hidden }) {
  const { unread } = useNotes()
  const button = (item, index) => {
    const props = {
      type: 'button',
      key: item.id,
      onMouseEnter: () => onHover(index),
      onClick: () => onActivate(index),
    }
    if (item.id === 'profile') {
      return (
        <button {...props} className={`nav-profile ${focused === index ? 'focused' : ''}`}>
          {profile && <Avatar id={profile.avatar} size={44} />}
          <Icon name="chevron-down" size={18} className="nav-caret" />
        </button>
      )
    }
    if (item.id === 'downloads') {
      return (
        <button {...props} className={`nav-search ${focused === index ? 'focused' : ''}`}
          aria-label={t('Downloads')}>
          <DownloadIcon size={30} />
        </button>
      )
    }
    if (item.id === 'bell') {
      return (
        <button {...props} className={`nav-search nav-bell ${focused === index ? 'focused' : ''}`}
          aria-label={t('Notifications')}>
          <BellIcon size={30} />
          {unread && <span className="nav-bell-dot" />}
        </button>
      )
    }
    return (
      <button
        {...props}
        className={[
          item.id === 'search' ? 'nav-search' : 'nav-item',
          active === item.id ? 'active' : '',
          focused === index ? 'focused' : '',
        ].join(' ')}
        aria-label={item.id === 'search' ? t('Search') : undefined}
      >
        {item.id === 'search' ? <SearchIcon size={30} /> : t(item.label)}
      </button>
    )
  }

  return (
    <div className={`topnav ${hidden ? 'hidden' : ''}`}>
      <div className="nav-mark" aria-hidden="true"><VMark size={40} /></div>
      <div className="nav-sections">
        {NAV_ITEMS.map((item, index) => (item.label ? button(item, index) : null))}
      </div>
      <div className="nav-end">
        {NAV_ITEMS.map((item, index) => (item.label ? null : button(item, index)))}
      </div>
    </div>
  )
}

export const MENU_ITEMS = ['profile', 'debug', 'exit']

export function ProfileMenu({ profile, index, onHover, onChoose }) {
  return (
    <div className="profile-menu">
      {MENU_ITEMS.map((id, i) => (
        <button
          type="button"
          key={id}
          className={`pm-item ${id === 'profile' ? 'pm-who' : ''} ${index === i ? 'focused' : ''}`}
          onMouseEnter={() => onHover(i)}
          onClick={() => onChoose(id)}
        >
          {id === 'profile' && profile && (
            <>
              <Avatar id={profile.avatar} size={44} />
              <span>{profile.name}</span>
            </>
          )}
          {id === 'debug' && (
            <>
              <Icon name="bug" size={26} />
              <span>{t('Debug')}</span>
            </>
          )}
          {id === 'exit' && (
            <>
              <Icon name="exit" size={26} />
              <span>{t('Exit VibeStream')}</span>
            </>
          )}
        </button>
      ))}
    </div>
  )
}

export function NotificationsPanel({ index, onHover, onChoose }) {
  const { items } = useNotes()
  const listRef = useRef(null)

  useEffect(() => {
    const list = listRef.current
    const row = list && list.children[index]
    if (!row) return
    if (row.offsetTop < list.scrollTop) list.scrollTop = row.offsetTop
    else if (row.offsetTop + row.offsetHeight > list.scrollTop + list.clientHeight) {
      list.scrollTop = row.offsetTop + row.offsetHeight - list.clientHeight
    }
  }, [index])

  return (
    <div className="notes-panel">
      <div className="notes-title">{t('Notifications')}</div>
      {items.length === 0 ? (
        <div className="notes-empty">{t('Nothing new yet')}</div>
      ) : (
        <div className="notes-list" ref={listRef}>
          {items.map((item, i) => (
            <button
              type="button"
              key={item.id}
              className={`note ${index === i ? 'focused' : ''}`}
              onMouseEnter={() => onHover(i)}
              onClick={() => onChoose(item)}
            >
              <span className="note-art">{item.image && <img src={item.image} alt="" />}</span>
              <span className="note-text">
                <span className={`note-heading ${item.kind === 'failed' ? 'failed' : ''}`}>{item.heading}</span>
                <span className="note-body">{item.text}</span>
                <span className="note-when">{ago(item.at)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
