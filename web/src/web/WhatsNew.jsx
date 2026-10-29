import { useEffect } from 'react'
import { createPortal } from 'react-dom'

/*
 * What is new since this browser last said, once after an update: a few
 * lines for whoever is watching, from the server's own release notes.
 */
export default function WhatsNew({ news, onDone }) {
  useEffect(() => {
    const escape = (event) => { if (event.key === 'Escape') onDone() }
    window.addEventListener('keydown', escape)
    return () => window.removeEventListener('keydown', escape)
  }, [onDone])

  const items = news.releases.flatMap((r) => r.items)
  return createPortal(
    <div className="chooser-backdrop confirm-backdrop" onClick={onDone}>
      <div className="chooser confirm whats-new" role="dialog" aria-label="What is new" onClick={(e) => e.stopPropagation()}>
        <h2>New in {news.version}</h2>
        <ul>
          {items.map((item, i) => (
            <li key={i}><strong>{item.title}</strong>{item.text}</li>
          ))}
        </ul>
        <div className="confirm-buttons">
          <button className="btn primary" onClick={onDone} autoFocus>Got it</button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
