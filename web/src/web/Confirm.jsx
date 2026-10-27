import { useEffect, useRef } from 'react'
import { createRoot } from 'react-dom/client'

/* In-app confirm: `await confirmDialog({ title, message, action })` resolves true only for the action. */
export function confirmDialog({ title, message = null, action = 'OK', cancel = 'Cancel', danger = true }) {
  return new Promise((resolve) => {
    const host = document.createElement('div')
    document.body.appendChild(host)
    const root = createRoot(host)
    const answer = (yes) => {
      root.unmount()
      host.remove()
      resolve(yes)
    }
    root.render(
      <ConfirmDialog title={title} message={message} action={action} cancel={cancel} danger={danger} onAnswer={answer} />,
    )
  })
}

function ConfirmDialog({ title, message, action, cancel, danger, onAnswer }) {
  const keep = useRef(null)

  useEffect(() => {
    // Focus the harmless button, so Enter does the harmless thing.
    keep.current?.focus()
    const escape = (event) => {
      if (event.key !== 'Escape') return
      // Before the title's dialog, which would close on the same key.
      event.stopPropagation()
      event.preventDefault()
      onAnswer(false)
    }
    window.addEventListener('keydown', escape, true)
    return () => window.removeEventListener('keydown', escape, true)
  }, [onAnswer])

  return (
    <div className="chooser-backdrop confirm-backdrop" onClick={() => onAnswer(false)}>
      <div className="chooser confirm" role="alertdialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <h2>{title}</h2>
        {message && <p className="confirm-text">{message}</p>}
        <div className="confirm-buttons">
          <button ref={keep} className="btn" onClick={() => onAnswer(false)}>{cancel}</button>
          <button className={`btn ${danger ? 'danger solid' : 'primary'}`} onClick={() => onAnswer(true)}>
            {action}
          </button>
        </div>
      </div>
    </div>
  )
}
