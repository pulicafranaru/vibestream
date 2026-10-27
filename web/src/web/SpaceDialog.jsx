import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { formatBytes } from '../api'
import ProgressRing from '../shared/ProgressRing'
import { Icon } from '../shared/icons'

/* Shown when a download would leave the disk below its spare space. */
export default function SpaceDialog({ space, onAnswer }) {
  const [busy, setBusy] = useState(false)
  const seeded = space.removable_seeded || { count: 0, bytes: 0 }
  const seeding = space.removable_seeding || { count: 0, bytes: 0 }

  useEffect(() => {
    const escape = (event) => {
      if (event.key === 'Escape') {
        event.stopPropagation()
        onAnswer('cancel')
      }
    }
    window.addEventListener('keydown', escape, true)
    return () => window.removeEventListener('keydown', escape, true)
  }, [onAnswer])

  const free = async () => {
    setBusy(true)
    onAnswer('free')
  }

  return createPortal(
    <div className="chooser-backdrop" onClick={(e) => { e.stopPropagation(); onAnswer('cancel') }}>
      <div className="chooser space-dialog" role="alertdialog" aria-label="Running out of space"
        onClick={(e) => e.stopPropagation()}>
        <button className="chooser-close" onClick={() => onAnswer('cancel')} aria-label="Close">
          <Icon name="close" size={18} />
        </button>
        <h2>Running Out of Space</h2>
        <p className="space-text">
          {formatBytes(space.free_bytes)} free, and this needs about {formatBytes(space.needed_bytes)}.
          {' '}{formatBytes(space.floor_bytes)} is kept spare so the disk never fills up.
        </p>

        {seeded.count > 0 && (
          <button className="chooser-option" onClick={free} disabled={busy}>
            <span className="chooser-icon">
              {busy ? <ProgressRing size={22} stroke={3} indeterminate /> : <Icon name="download" size={24} />}
            </span>
            <span className="chooser-text">
              <strong>Free {formatBytes(seeded.bytes)} and Download</strong>
              <span>
                Removes the downloaded source of {seeded.count} title{seeded.count === 1 ? '' : 's'} that
                finished seeding. They keep playing.
              </span>
            </span>
          </button>
        )}

        {space.fits && (
          <button className="chooser-option" onClick={() => onAnswer('anyway')} disabled={busy}>
            <span className="chooser-icon"><Icon name="download" size={24} /></span>
            <span className="chooser-text">
              <strong>Download Anyway</strong>
              <span>Leaves {formatBytes(Math.max(0, space.free_bytes - space.needed_bytes))} free.</span>
            </span>
          </button>
        )}

        {!space.fits && seeded.count === 0 && (
          <p className="note error">There isn't room for this download.</p>
        )}

        {seeding.count > 0 && (
          <p className="space-foot">
            {seeding.count} more source{seeding.count === 1 ? ' is' : 's are'} still seeding
            ({formatBytes(seeding.bytes)}). You can remove them in My Downloads, but leaving
            early counts as a hit and run.
          </p>
        )}
      </div>
    </div>,
    document.body,
  )
}
