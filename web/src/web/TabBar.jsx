import Avatar from '../shared/Avatar'
import { Icon, SearchIcon } from '../shared/icons'

/* Bottom tabs at phone widths; hidden wider (web.css). */
const TABS = [
  { id: 'home', label: 'Home', icon: 'home' },
  { id: 'search', label: 'Search' },
  { id: 'library', label: 'Library' },
]

export default function TabBar({ section, profile, onNavigate, onSearch }) {
  return (
    <nav className="tab-bar" aria-label="Sections">
      {TABS.map((tab) => {
        const chosen = section === tab.id
        const icon = tab.id === 'search'
          ? <SearchIcon size={20} />
          : tab.id === 'library'
            ? <Avatar id={profile?.avatar} size={22} />
            : <Icon name={tab.icon} size={20} />
        return (
          <button
            key={tab.id}
            type="button"
            className={chosen ? 'chosen' : ''}
            aria-current={chosen ? 'page' : undefined}
            onClick={() => (tab.id === 'search' ? onSearch() : onNavigate(tab.id))}
          >
            {icon}
            <span>{tab.label}</span>
          </button>
        )
      })}
    </nav>
  )
}
