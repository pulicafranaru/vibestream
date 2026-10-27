import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { Icon } from '../shared/icons'
import { admin } from './api'

// Settings are edited as a draft. Saving sends only changed keys; the server
// applies all or none and reports refusals per field.

const ToastContext = createContext(() => {})

export function ToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  const say = useCallback((message, bad = false) => {
    setToast({ message, bad, at: Date.now() })
  }, [])
  useEffect(() => {
    if (!toast) return undefined
    const timer = setTimeout(() => setToast(null), 3600)
    return () => clearTimeout(timer)
  }, [toast])
  return (
    <ToastContext.Provider value={say}>
      {children}
      {toast && (
        <div className={`toast ${toast.bad ? 'bad' : ''}`} role="status">
          <Icon name={toast.bad ? 'info' : 'check'} size={18} />
          {toast.message}
        </div>
      )}
    </ToastContext.Provider>
  )
}

export const useToast = () => useContext(ToastContext)

const ConfigContext = createContext(null)

export function ConfigProvider({ children }) {
  const [config, setConfig] = useState(null)
  const [draft, setDraft] = useState({})
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const say = useToast()

  const load = useCallback(() => admin.config().then(setConfig).catch(() => {}), [])
  useEffect(() => { load() }, [load])

  const value = useMemo(() => {
    const fields = config ? config.fields : {}
    const get = (key) => (key in draft ? draft[key] : fields[key] && fields[key].value)
    const set = (key, next) => {
      setErrors((e) => ({ ...e, [key]: undefined }))
      setDraft((d) => {
        const copy = { ...d }
        const saved = fields[key] && fields[key].value
        if (JSON.stringify(saved) === JSON.stringify(next)) delete copy[key]
        else copy[key] = next
        return copy
      })
    }
    const save = async () => {
      setSaving(true)
      try {
        const fresh = await admin.saveConfig(draft)
        setConfig(fresh)
        setDraft({})
        setErrors({})
        say('Saved. It applies straight away.')
      } catch (e) {
        if (e.detail && e.detail.fields) setErrors(e.detail.fields)
        say(e.status === 422 ? 'Some values need another look.' : e.message, true)
      } finally {
        setSaving(false)
      }
    }
    const reset = async (key) => {
      try {
        setConfig(await admin.resetConfig(key))
        setDraft((d) => {
          const copy = { ...d }
          delete copy[key]
          return copy
        })
        say('Back to the value from .env.')
      } catch (e) {
        say(e.message, true)
      }
    }
    return {
      config, fields, get, set, save, reset, saving, errors,
      dirty: Object.keys(draft).length,
      discard: () => { setDraft({}); setErrors({}) },
    }
  }, [config, draft, errors, saving, say])

  return <ConfigContext.Provider value={value}>{children}</ConfigContext.Provider>
}

export const useConfig = () => useContext(ConfigContext)

export function SaveBar() {
  const c = useConfig()
  if (!c || !c.dirty) return null
  return (
    <div className="savebar">
      <span>{c.dirty === 1 ? '1 unsaved change' : `${c.dirty} unsaved changes`}</span>
      <button className="btn quiet" onClick={c.discard} disabled={c.saving}>Discard</button>
      <button className="btn primary" onClick={c.save} disabled={c.saving}>
        {c.saving ? <span className="spinner" /> : <Icon name="check" size={16} />}
        Save changes
      </button>
    </div>
  )
}

function Origin({ name }) {
  const c = useConfig()
  const field = c.fields[name]
  if (!field) return null
  if (!field.changed_at) return null
  return (
    <span className="badge ember" title={`Changed here ${new Date(field.changed_at).toLocaleString()}`}>
      Set here
      <button className="link" onClick={() => c.reset(name)}>use .env</button>
    </span>
  )
}

export function Row({ title, text, name, children, end, layout = '' }) {
  const c = useConfig()
  const error = name && c && c.errors[name]
  return (
    <div className={`row ${layout}`}>
      <div className="row-text">
        <b>{title}{name && <Origin name={name} />}</b>
        {text && <p>{text}</p>}
      </div>
      <div className={`row-control ${end ? 'end' : ''}`}>
        {children}
        {error && <span className="row-error">{error}</span>}
      </div>
    </div>
  )
}

export function Switch({ name, on, onChange, label }) {
  const c = useConfig()
  const value = name ? !!c.get(name) : on
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      aria-label={label}
      className={`switch ${value ? 'on' : ''}`}
      onClick={() => (name ? c.set(name, !value) : onChange(!value))}
    />
  )
}

export function TextInput({ name, placeholder, mono }) {
  const c = useConfig()
  const value = c.get(name) ?? ''
  return (
    <input
      className={`input ${mono ? 'mono' : ''} ${c.errors[name] ? 'bad' : ''}`}
      value={value}
      placeholder={placeholder}
      spellCheck={false}
      onChange={(e) => c.set(name, e.target.value)}
    />
  )
}

export function NumberInput({ name, unit, step = 1 }) {
  const c = useConfig()
  const field = c.fields[name] || {}
  const value = c.get(name)
  const [text, setText] = useState(value === undefined ? '' : String(value))
  useEffect(() => { setText(value === undefined ? '' : String(value)) }, [value])
  return (
    <div className="number">
      <input
        className={`input ${c.errors[name] ? 'bad' : ''}`}
        inputMode="decimal"
        value={text}
        onChange={(e) => {
          setText(e.target.value)
          const n = Number(e.target.value)
          if (e.target.value.trim() !== '' && Number.isFinite(n)) c.set(name, field.kind === 'int' ? Math.round(n) : n)
        }}
        step={step}
        min={field.min ?? undefined}
        max={field.max ?? undefined}
      />
      {unit && <span className="unit">{unit}</span>}
    </div>
  )
}

export function SecretInput({ name, placeholder = 'Paste a new one' }) {
  const c = useConfig()
  const saved = (c.fields[name] || {}).value || {}
  const typed = typeof c.get(name) === 'string' ? c.get(name) : ''
  return (
    <>
      <input
        className={`input mono ${c.errors[name] ? 'bad' : ''}`}
        type="password"
        autoComplete="off"
        value={typed}
        placeholder={saved.set ? `Set${saved.ends ? `, ends in ${saved.ends}` : ''}. Paste to replace` : placeholder}
        onChange={(e) => c.set(name, e.target.value === '' ? saved : e.target.value)}
      />
      <span className="faint" style={{ fontSize: 12 }}>
        {saved.set ? <><span className="dot good" /> Set</> : <><span className="dot bad" /> Not set</>}
      </span>
    </>
  )
}

export function Select({ name, options }) {
  const c = useConfig()
  return (
    <select className="input" value={c.get(name) ?? ''} onChange={(e) => c.set(name, e.target.value)}>
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

export function Panel({ title, sub, icon, action, children, className = '' }) {
  return (
    <section className={`panel ${className}`}>
      {(title || action) && (
        <div className="panel-head" style={sub ? { marginBottom: 4 } : undefined}>
          {icon && <Icon name={icon} size={18} />}
          {title && <h2>{title}</h2>}
          {action}
        </div>
      )}
      {sub && <p className="sub">{sub}</p>}
      {children}
    </section>
  )
}

export function PageHead({ title, text, actions }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {text && <p>{text}</p>}
      </div>
      {actions && <div className="actions">{actions}</div>}
    </header>
  )
}

export function Ring({ used, total, size = 92 }) {
  const share = total ? used / total : 0
  const r = size / 2 - 7
  const around = 2 * Math.PI * r
  const id = `ring-${size}-${Math.round(share * 1000)}`
  return (
    <svg className="disk-ring" width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb000" />
          <stop offset="0.5" stopColor="#ff6a00" />
          <stop offset="1" stopColor="#ff2e63" />
        </linearGradient>
      </defs>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="#2a2019" strokeWidth="9" />
      <circle
        cx={size / 2} cy={size / 2} r={r} fill="none" stroke={`url(#${id})`} strokeWidth="9"
        strokeLinecap="round" strokeDasharray={`${around * share} ${around}`}
        transform={`rotate(-90 ${size / 2} ${size / 2})`}
      />
      <text x="50%" y="48%" textAnchor="middle" dominantBaseline="middle">{Math.round(share * 100)}%</text>
      <text className="sub" x="50%" y="66%" textAnchor="middle">USED</text>
    </svg>
  )
}

export function bytes(n) {
  if (n === null || n === undefined) return ''
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let i = 0
  let v = n
  while (v >= 1000 && i < units.length - 1) {
    v /= 1000
    i += 1
  }
  return `${v >= 100 || i === 0 ? Math.round(v) : v.toFixed(1)} ${units[i]}`
}

export function ago(iso) {
  if (!iso) return ''
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000
  if (seconds < 60) return 'just now'
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`
  const days = Math.floor(seconds / 86400)
  return days === 1 ? 'yesterday' : `${days} days ago`
}

export function duration(seconds) {
  const s = Math.max(0, Math.round(seconds || 0))
  const d = Math.floor(s / 86400)
  const h = Math.floor((s % 86400) / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (d) return `${d}d ${h}h`
  if (h) return `${h}h ${m}m`
  return `${m}m`
}

export function Busy({ on, children }) {
  return on ? <span className="spinner" /> : children
}
