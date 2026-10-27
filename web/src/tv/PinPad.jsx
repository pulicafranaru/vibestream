import { useCallback, useEffect, useRef, useState } from 'react'
import Avatar from './Avatar'
import { BackspaceIcon } from './icons'
import { t } from '../shared/i18n'

// `onEntered(pin)` answers true, or 'wrong', 'mismatch', 'wait' (too many tries) or 'error'.

const MESSAGES = {
  wrong: 'Wrong PIN. Try again.',
  mismatch: 'That does not match. Try again.',
  wait: 'Too many tries. Wait 30 seconds.',
  error: 'Could not check it. Try again.',
}

const KEYS = [
  ['1', '2', '3'],
  ['4', '5', '6'],
  ['7', '8', '9'],
  [null, '0', 'delete'],
]

export function usePinPad({ session, profile, title, subtitle, onEntered, onCancel }) {
  const [digits, setDigitsState] = useState('')
  const digitsRef = useRef('')
  const setDigits = (value) => {
    digitsRef.current = value
    setDigitsState(value)
  }
  const [at, setAt] = useState({ row: 1, col: 1, cancel: false })
  const [shake, setShake] = useState(0)
  const [message, setMessage] = useState(null)
  const busy = useRef(false)

  useEffect(() => {
    setDigits('')
    setAt({ row: 1, col: 1, cancel: false })
    setMessage(null)
  }, [session])

  const type = useCallback((digit) => {
    if (busy.current || digitsRef.current.length >= 4) return
    setMessage(null)
    const next = digitsRef.current + digit
    setDigits(next)
    if (next.length < 4) return
    busy.current = true
    Promise.resolve(onEntered(next)).catch(() => 'error').then((answer) => {
      busy.current = false
      if (answer === true) return
      setDigits('')
      setShake((n) => n + 1)
      setMessage(t(MESSAGES[answer] || MESSAGES.error))
    })
  }, [onEntered])

  const erase = useCallback(() => {
    if (busy.current) return
    setDigits(digitsRef.current.slice(0, -1))
  }, [])

  const press = useCallback((key) => {
    if (key === 'delete') erase()
    else if (key) type(key)
  }, [erase, type])

  const handler = {
    onDigit: (n) => type(String(n)),
    onDirection: (dir) => {
      setAt((a) => {
        if (a.cancel) return dir === 'up' ? { row: 3, col: 1, cancel: false } : a
        let { row, col } = a
        if (dir === 'down' && row === 3) return { ...a, cancel: true }
        if (dir === 'up') row = Math.max(0, row - 1)
        if (dir === 'down') row += 1
        if (dir === 'left') col = Math.max(0, col - 1)
        if (dir === 'right') col = Math.min(2, col + 1)
        if (!KEYS[row][col]) return dir === 'down' ? { row, col: 1, cancel: false } : a
        return { row, col, cancel: false }
      })
    },
    onEnter: () => {
      if (at.cancel) onCancel()
      else press(KEYS[at.row][at.col])
    },
    onBack: () => {
      if (digits) erase()
      else onCancel()
      return true
    },
  }

  const view = (
    <div className="pin-screen">
      {profile && <Avatar id={profile.avatar} size={120} />}
      {profile && <div className="pin-name">{profile.name}</div>}
      <h1>{title}</h1>
      {subtitle && <p className="pe-sub">{subtitle}</p>}
      <div className={`pin-dots ${shake % 2 ? 'shake-a' : shake ? 'shake-b' : ''}`}>
        {[0, 1, 2, 3].map((i) => <span key={i} className={i < digits.length ? 'on' : ''} />)}
      </div>
      <div className="pin-message">{message || ' '}</div>
      <div className="pin-keys">
        {KEYS.map((row, ri) => (
          <div className="pin-row" key={ri}>
            {row.map((key, ci) => (
              key ? (
                <div
                  key={key}
                  className={`pin-key ${!at.cancel && at.row === ri && at.col === ci ? 'focused' : ''}`}
                  onMouseEnter={() => setAt({ row: ri, col: ci, cancel: false })}
                  onClick={() => press(key)}
                >
                  {key === 'delete' ? <BackspaceIcon size={30} /> : key}
                </div>
              ) : <div key="blank" className="pin-key blank" />
            ))}
          </div>
        ))}
      </div>
      <div
        className={`pill-btn small pin-cancel ${at.cancel ? 'focused' : ''}`}
        onMouseEnter={() => setAt((a) => ({ ...a, cancel: true }))}
        onClick={onCancel}
      >
        {t('Cancel')}
      </div>
    </div>
  )

  return { handler, view }
}
