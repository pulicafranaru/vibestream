import './iconfont/icons.css'
import { GLYPHS } from './iconfont/glyphs'

/** Icons from the icon font. `size` is the side of the icon's square in pixels. */
// A triangle looks off centre in its box, so the play glyph is nudged here once,
// not per screen.
const OPTICAL = { play: 'translateX(0.09em)' }

export function Icon({ name, size = 24, className = '' }) {
  return (
    <i
      className={`vi ${className}`}
      style={{ fontSize: size, width: size, height: size, transform: OPTICAL[name] }}
      aria-hidden="true"
    >
      {GLYPHS[name]}
    </i>
  )
}

export const PlayIcon = (props) => <Icon name="play" {...props} />
export const PauseIcon = (props) => <Icon name="pause" {...props} />
export const BackIcon = (props) => <Icon name="back" {...props} />
export const ReplayIcon = (props) => <Icon name="replay" {...props} />
export const GearIcon = (props) => <Icon name="gear" {...props} />
export const SearchIcon = (props) => <Icon name="search" {...props} />
export const LikeIcon = (props) => <Icon name="like" {...props} />
export const DislikeIcon = (props) => <Icon name="dislike" {...props} />
export const DownloadIcon = (props) => <Icon name="download" {...props} />
export const SeasonDownloadIcon = (props) => <Icon name="download-season" {...props} />
export const BellIcon = (props) => <Icon name="bell" {...props} />
export const PlusIcon = (props) => <Icon name="plus" {...props} />
export const CheckIcon = (props) => <Icon name="check" {...props} />

export function MyListIcon({ saved = false, ...props }) {
  return <Icon name={saved ? 'check' : 'plus'} {...props} />
}

export const TrashIcon = (props) => <Icon name="trash" {...props} />

export const BackspaceIcon = (props) => <Icon name="backspace" {...props} />
