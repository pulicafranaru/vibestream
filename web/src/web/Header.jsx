import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import Avatar from '../shared/Avatar'
import { BellIcon, DownloadIcon, Icon, SearchIcon } from '../shared/icons'
import { SECTIONS } from './router'
import { ago } from './notifications'
import { VMark, Wordmark } from '../shared/brand'
import { JobState } from './Downloads'
import { jobStatus, jobSubtitle } from './jobs'

export default function Header({
  section,
  query,
  profile,
  onNavigate,
  onSearch,
  onDownloads,
  onDownload,
  downloading,
  onManageProfile,
  onSwitchProfile,
  notes,
  onNotification,
  onAllNotifications,
}) {
  const [text, setText] = useState(query || '')
  const [menuOpen, setMenuOpen] = useState(false)
  const [searchOpen, setSearchOpen] = useState(Boolean(query))
  const inputRef = useRef(null)
  const menuRef = useRef(null)

  const openSearch = useCallback(() => {
    setSearchOpen(true)
    // Focus once the field exists and has started to widen.
    requestAnimationFrame(() => {
      inputRef.current?.focus()
      inputRef.current?.select()
    })
  }, [])

  // The URL is the source of truth: /search?q= from a link or Back fills the box.
  useEffect(() => {
    setText(query || '')
    if (query) setSearchOpen(true)
  }, [query])

  useEffect(() => {
    const onKey = (event) => {
      const typing = /^(INPUT|TEXTAREA)$/.test(document.activeElement?.tagName || '')
      const shortcut = (event.key === 'k' && (event.metaKey || event.ctrlKey))
        || (event.key === '/' && !typing)
      if (!shortcut) return
      event.preventDefault()
      openSearch()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [openSearch])

  useEffect(() => {
    if (!menuOpen) return undefined
    const away = (event) => {
      if (!menuRef.current?.contains(event.target)) setMenuOpen(false)
    }
    window.addEventListener('mousedown', away)
    return () => window.removeEventListener('mousedown', away)
  }, [menuOpen])

  /* Debounced longer than a UI-only debounce: a live search can cost a tracker request. */
  // Emptied: clear the results page; elsewhere, navigating to /search would be wrong.
  const clearSearch = () => {
    if (query) onSearch('')
  }

  useEffect(() => {
    if (text === (query || '')) return undefined
    const timer = setTimeout(() => onSearch(text), 350)
    return () => clearTimeout(timer)
  }, [text, query, onSearch])

  return (
    <header className="header">
      <a
        className="brand"
        href="/"
        onClick={(e) => {
          e.preventDefault()
          onNavigate('home')
        }}
      >
        <Wordmark size={16} className="brand-full" />
        <VMark size={22} className="brand-mark" />
      </a>

      <nav className="nav">
        {SECTIONS.filter((item) => !item.parent).map((item) => (
          <a
            key={item.id}
            href={item.path}
            className={section === item.id ? 'active' : ''}
            onClick={(e) => {
              e.preventDefault()
              onNavigate(item.id)
            }}
          >
            {item.label}
          </a>
        ))}
      </nav>

      <form
        className={`searchbox ${searchOpen ? 'open' : ''}`}
        onSubmit={(e) => {
          e.preventDefault()
          onSearch(text)
        }}
      >
        <button
          type="button"
          className="search-toggle"
          onClick={() => (searchOpen ? inputRef.current?.focus() : openSearch())}
          aria-label="Search"
          title="Search"
        >
          <SearchIcon size={19} />
        </button>
        <input
          ref={inputRef}
          value={text}
          placeholder="Titles, people, genres"
          onChange={(e) => setText(e.target.value)}
          onBlur={() => { if (!text) setSearchOpen(false) }}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              setText('')
              clearSearch()
              setSearchOpen(false)
              e.currentTarget.blur()
            }
          }}
          tabIndex={searchOpen ? 0 : -1}
          aria-label="Search"
        />
        {searchOpen && text && (
          <button type="button" className="clear" onClick={() => { setText(''); clearSearch(); inputRef.current?.focus() }}>
            <Icon name="close" size={16} />
          </button>
        )}
      </form>

      <Notifications notes={notes} onChoose={onNotification} onAll={onAllNotifications} />

      <DownloadsMenu busy={downloading} onChoose={onDownload} onAll={onDownloads} />

      <div className="who" ref={menuRef}>
        <button className="avatar-btn" onClick={() => setMenuOpen((v) => !v)}>
          <Avatar id={profile.avatar} size={34} />
        </button>
        {menuOpen && (
          <div className="menu">
            <div className="menu-name">{profile.name}</div>
            <button onClick={() => { setMenuOpen(false); onManageProfile() }}>
              Manage profile
            </button>
            <button onClick={() => { setMenuOpen(false); onSwitchProfile() }}>
              Switch profile
            </button>
          </div>
        )}
      </div>
    </header>
  )
}

const IN_THE_BELL = 6

function useDropdown() {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const away = (event) => {
      if (!ref.current?.contains(event.target)) setOpen(false)
    }
    const escape = (event) => { if (event.key === 'Escape') setOpen(false) }
    window.addEventListener('mousedown', away)
    window.addEventListener('keydown', escape)
    return () => {
      window.removeEventListener('mousedown', away)
      window.removeEventListener('keydown', escape)
    }
  }, [open])

  return [open, setOpen, ref]
}

function Notifications({ notes, onChoose, onAll }) {
  const [open, setOpen, ref] = useDropdown()

  const toggle = () => {
    if (open) {
      setOpen(false)
      return
    }
    notes.load()
    setOpen(true)
    notes.markSeen()
  }

  const { items, unread } = notes
  return (
    <div className="bell" ref={ref}>
      <button
        className="icon-btn"
        onClick={toggle}
        title="Notifications"
        aria-label={unread ? `Notifications, ${unread} new` : 'Notifications'}
      >
        <BellIcon size={21} />
        {unread > 0 && <span className="bell-badge" />}
      </button>
      {open && (
        <div className="notifications">
          {items.length === 0 && <div className="notifications-empty">Nothing new yet</div>}
          {items.slice(0, IN_THE_BELL).map((item) => (
            <NotificationRow key={item.id} item={item} onClick={() => { setOpen(false); onChoose(item) }} />
          ))}
          <button type="button" className="notifications-all" onClick={() => { setOpen(false); onAll() }}>
            View all Notifications
          </button>
        </div>
      )}
    </div>
  )
}

const IN_THE_LIST = 6

function DownloadsMenu({ busy, onChoose, onAll }) {
  const [open, setOpen, ref] = useDropdown()
  const [jobs, setJobs] = useState(null)

  useEffect(() => {
    if (!open) return undefined
    let alive = true
    let timer = null
    const tick = async () => {
      const data = await api.downloadJobs().catch(() => null)
      if (!alive) return
      if (data) setJobs(data.items || [])
      timer = setTimeout(tick, 3000)
    }
    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [open])

  return (
    <div className="bell" ref={ref}>
      <button
        className="icon-btn"
        onClick={() => setOpen((v) => !v)}
        title="Downloads"
        aria-label={busy ? 'Downloads, in progress' : 'Downloads'}
      >
        <DownloadIcon size={20} />
        {busy && <span className="bell-badge" />}
      </button>
      {open && (
        <div className="notifications">
          {jobs && jobs.length === 0 && <div className="notifications-empty">Nothing downloaded yet</div>}
          {!jobs && <div className="notifications-empty">Loading</div>}
          {(jobs || []).slice(0, IN_THE_LIST).map((job) => (
            <DownloadRow key={job.job_id} job={job} onClick={() => { setOpen(false); onChoose(job) }} />
          ))}
          <button type="button" className="notifications-all" onClick={() => { setOpen(false); onAll() }}>
            View all Downloads
          </button>
        </div>
      )}
    </div>
  )
}

function DownloadRow({ job, onClick }) {
  const status = jobStatus({ ...job, dl_speed: 0 })
  const subtitle = jobSubtitle(job)
  // A wide picture for every row: a poster cropped to this box would be a strip of its middle.
  const art = (job.kind === 'episode' && job.episode?.still) || job.backdrop || job.poster
  return (
    <button className="notification download" onClick={onClick}>
      <div className="notification-art">
        {art && <img src={art} alt="" loading="lazy" />}
      </div>
      <div className="notification-body">
        <div className="notification-heading">{job.title}</div>
        {subtitle && <div className="notification-text">{subtitle}</div>}
        <JobState status={status} />
        {status.bar !== null && (
          <div className="dl-progress"><span style={{ width: `${Math.max(1, Math.min(100, status.bar))}%` }} /></div>
        )}
      </div>
    </button>
  )
}

export function NotificationRow({ item, fresh = false, onClick }) {
  return (
    <button className={`notification ${item.kind} ${fresh ? 'fresh' : ''}`} onClick={onClick}>
      <div className="notification-art">
        {item.image && <img src={item.image} alt="" loading="lazy" />}
      </div>
      <div className="notification-body">
        <div className="notification-heading">{item.heading}</div>
        <div className="notification-text">{item.text}</div>
        <div className="notification-when">{ago(item.at)}</div>
      </div>
    </button>
  )
}
