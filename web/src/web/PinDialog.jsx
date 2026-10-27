import { useEffect, useRef, useState } from 'react'
import Avatar from '../shared/Avatar'
import { Icon } from '../shared/icons'

/* `onEntered(pin)` returns true, or 'wrong', 'mismatch', 'wait' or 'error'. A new `title` restarts entry. */

const MESSAGES = {
  wrong: 'Wrong PIN. Try again.',
  mismatch: 'That does not match. Try again.',
  wait: 'Too many tries. Wait 30 seconds.',
  error: 'Could not check it. Try again.',
}

export default function PinDialog({ profile, title, subtitle, onEntered, onClose }) {
  const [digits, setDigits] = useState('')
  const [shake, setShake] = useState(0)
  const [message, setMessage] = useState(null)
  const [busy, setBusy] = useState(false)
  const field = useRef(null)

  useEffect(() => {
    setDigits('')
    setMessage(null)
    if (field.current) field.current.focus()
  }, [title])

  const change = async (target) => {
    const next = target.value.replace(/\D/g, '').slice(0, 4)
    // Typing always adds to the end, wherever the caret was left.
    requestAnimationFrame(() => target.setSelectionRange(next.length, next.length))
    setDigits(next)
    setMessage(null)
    if (next.length < 4 || busy) return
    setBusy(true)
    const answer = await Promise.resolve(onEntered(next)).catch(() => 'error')
    setBusy(false)
    if (answer === true) return
    setDigits('')
    setShake((n) => n + 1)
    setMessage(MESSAGES[answer] || MESSAGES.error)
    if (field.current) field.current.focus()
  }

  return (
    // Over the profile editor too, so a click outside closes this alone.
    <div className="sheet-backdrop" onClick={(e) => { e.stopPropagation(); onClose() }}>
      <div className="sheet narrow pin-sheet" onClick={(e) => { e.stopPropagation(); field.current?.focus() }}>
        <button className="sheet-close" onClick={onClose} aria-label="Close"><Icon name="close" size={22} /></button>
        <div className="sheet-body">
          {profile && <Avatar id={profile.avatar} size={72} />}
          {profile && <div className="pin-name">{profile.name}</div>}
          <h2>{title}</h2>
          {subtitle && <p className="note">{subtitle}</p>}
          <div className={`pin-dots ${shake % 2 ? 'shake-a' : shake ? 'shake-b' : ''}`}>
            {[0, 1, 2, 3].map((i) => <span key={i} className={i < digits.length ? 'on' : ''} />)}
          </div>
          <input
            ref={field}
            className="pin-field"
            value={digits}
            onChange={(e) => change(e.target)}
            inputMode="numeric"
            autoComplete="off"
            maxLength={4}
            autoFocus
            aria-label={title}
          />
          <p className="note error pin-message">{message || ' '}</p>
        </div>
      </div>
    </div>
  )
}
