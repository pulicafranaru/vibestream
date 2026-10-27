import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import Avatar, { AVATAR_COLOURS, AVATAR_FACES } from './Avatar'
import { BackspaceIcon, Icon } from './icons'
import { LANGUAGES, t } from '../shared/i18n'
import { VMark, Wordmark } from '../shared/brand'
import { usePinPad } from './PinPad'
import { castPin } from './cast'

const COLOURS = Object.keys(AVATAR_COLOURS)

// Each key is one column wide unless it says otherwise; Up and Down land on the key covering the same column.
const LETTERS = [
  '1234567890'.split(''),
  'qwertyuiop'.split(''),
  [...'asdfghjkl'.split(''), '-'],
  ['shift', ...'zxcvbnm'.split(''), "'"],
  ['symbols', 'accents', 'space', 'delete'],
]
const SYMBOLS = [
  '1234567890'.split(''),
  '!@#$%&*()+'.split(''),
  '.,?:;"/=_~'.split(''),
  ['shift', ...'<>[]{}|'.split('')],
  ['symbols', 'accents', 'space', 'delete'],
]
const ACCENTS = [
  '1234567890'.split(''),
  'ăâîșțäöüß-'.split(''),
  'éèêëàáçñóú'.split(''),
  ['shift', ...'íìòùãõø'.split(''), "'"],
  ['symbols', 'accents', 'space', 'delete'],
]
const SPAN = { shift: 2, symbols: 2, accents: 2, space: 4, delete: 2 }
const span = (key) => SPAN[key] || 1

function columnsOf(row) {
  const out = []
  let at = 0
  row.forEach((key) => {
    out.push(at)
    at += span(key)
  })
  return out
}

function keyAtColumn(row, column) {
  const starts = columnsOf(row)
  for (let i = row.length - 1; i >= 0; i -= 1) {
    if (column >= starts[i]) return i
  }
  return 0
}

export default function Profiles({
  profiles, active, onPick, onChanged, onActiveDeleted, registerHandler, onClose, variant = 'start', backdrop = null,
}) {
  const [mode, setMode] = useState(variant === 'switch' ? 'switch' : 'pick')
  const [index, setIndex] = useState(() => {
    const at = active ? profiles.findIndex((p) => p.id === active.id) : -1
    return at >= 0 ? at : 0
  })
  const [pencil, setPencil] = useState(false)
  const [editing, setEditing] = useState(null)
  const [draft, setDraft] = useState({ name: '', avatar: 'teal-cool', language: 'en' })
  const [menuIndex, setMenuIndex] = useState(0)
  const [kb, setKb] = useState({ row: 1, col: 0, layer: 'letters', upper: false, onActions: false, action: 1 })
  const [iconRow, setIconRow] = useState(0)
  const [iconCol, setIconCol] = useState(0)
  const [langIndex, setLangIndex] = useState(0)
  const [confirmChoice, setConfirmChoice] = useState(0)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  // { step: 'open' | 'edit' | 'choose' | 'again', profile, back, chosen }; back is the mode Cancel returns to.
  const [pin, setPin] = useState(null)
  const [pinMenuIndex, setPinMenuIndex] = useState(0)
  const unlocked = useRef(null)
  const returnTo = useRef('pick')
  const iconRowRefs = useRef({})
  const iconGridRef = useRef(null)

  const tiles = mode === 'manage'
    ? profiles
    : [...profiles, { id: '__add', name: t('Add Profile') }, ...(mode === 'pick' ? [{ id: '__manage', name: t('Manage') }] : [])]

  const menu = editing ? ['name', 'icon', 'language', 'pin', 'delete', 'done'] : ['name', 'icon', 'language', 'done']

  const askPin = useCallback((step, profile, extra = {}) => {
    setPin({ step, profile, back: mode, ...extra })
    setMode('pin')
  }, [mode])

  const choose = useCallback((profile) => {
    if (profile.has_pin && !(active && active.id === profile.id)) askPin('open', profile)
    else onPick(profile)
  }, [active, askPin, onPick])

  const beginEditor = useCallback((profile, from) => {
    returnTo.current = from
    setEditing(profile)
    setDraft({
      name: profile ? profile.name : '',
      avatar: profile ? profile.avatar || 'teal-cool' : 'teal-cool',
      language: profile ? profile.language || 'en' : (active && active.language) || 'en',
    })
    setMenuIndex(profile ? 0 : 0)
    setError(null)
    setMode(profile ? 'menu' : 'name')
    if (!profile) setKb({ row: 1, col: 0, layer: 'letters', upper: true, onActions: false, action: 1 })
  }, [active])

  const openEditor = useCallback((profile, from) => {
    unlocked.current = null
    if (profile && profile.has_pin) askPin('edit', profile, { from })
    else beginEditor(profile, from)
  }, [askPin, beginEditor])

  const leaveEditor = useCallback(() => {
    setEditing(null)
    unlocked.current = null
    setMode(returnTo.current)
  }, [])

  const verdict = (e) => (e.status === 429 ? 'wait' : e.status === 403 ? 'wrong' : 'error')

  const pinEntered = useCallback(async (value) => {
    if (!pin) return 'error'
    const { step, profile } = pin
    if (step === 'open' || step === 'edit') {
      try {
        await api.checkPin(profile.id, value)
      } catch (e) {
        return verdict(e)
      }
      // The server also needs the PIN once to bind this TV to the profile.
      castPin(profile.id, value)
      setPin(null)
      if (step === 'open') {
        setMode(pin.back)
        onPick(profile)
      } else {
        beginEditor(profile, pin.from)
        unlocked.current = value
      }
      return true
    }
    if (step === 'choose') {
      setPin({ ...pin, step: 'again', chosen: value })
      return true
    }
    if (value !== pin.chosen) return 'mismatch'
    try {
      await api.setPin(profile.id, value, unlocked.current)
    } catch (e) {
      return verdict(e)
    }
    unlocked.current = value
    setEditing((current) => current && { ...current, has_pin: true })
    onChanged()
    setPin(null)
    setMode('menu')
    return true
  }, [pin, onPick, beginEditor, onChanged])

  const removePin = useCallback(async () => {
    if (!editing) return
    setBusy(true)
    setError(null)
    try {
      await api.setPin(editing.id, null, unlocked.current)
      unlocked.current = null
      setEditing((current) => current && { ...current, has_pin: false })
      onChanged()
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
      setMode('menu')
    }
  }, [editing, onChanged])

  const pinTitles = {
    open: t('Enter your PIN'),
    edit: t('Enter the PIN to edit this profile'),
    choose: t('Choose a PIN'),
    again: t('Enter it again'),
  }
  const pinPad = usePinPad({
    session: pin,
    profile: pin && pin.profile,
    title: pin ? pinTitles[pin.step] : '',
    subtitle: pin && pin.step === 'choose' ? t('Four digits, asked for when someone chooses this profile.') : null,
    onEntered: pinEntered,
    onCancel: () => {
      const back = pin ? pin.back : 'pick'
      setPin(null)
      setMode(back)
    },
  })

  const save = useCallback(async () => {
    const clean = draft.name.trim() || t('New Profile')
    setBusy(true)
    setError(null)
    try {
      if (editing) {
        await api.updateProfile(editing.id, { name: clean, avatar: draft.avatar, language: draft.language }, unlocked.current)
        await onChanged()
        leaveEditor()
      } else {
        const created = await api.createProfile(clean, draft.avatar, draft.language)
        await onChanged()
        onPick(created)
      }
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  }, [draft, editing, onChanged, onPick, leaveEditor])

  const remove = useCallback(async () => {
    if (!editing) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteProfile(editing.id, unlocked.current)
      const remaining = await onChanged()
      setEditing(null)
      unlocked.current = null
      setIndex(0)
      setMode(returnTo.current === 'switch' ? 'switch' : 'pick')
      if (active && editing.id === active.id) {
        const next = (remaining || []).find((p) => p.id !== editing.id && !p.has_pin)
        if (next) onPick(next)
        else {
          setMode('pick')
          onActiveDeleted()
        }
      }
    } catch (e) {
      setError(e.message.indexOf('400') >= 0 ? t('This is the only profile.') : e.message)
      setMode('menu')
    } finally {
      setBusy(false)
    }
  }, [editing, active, onChanged, onPick, onActiveDeleted])


  // The old name opens selected: the first letter typed replaces it all.
  const [nameSelected, setNameSelected] = useState(false)
  const layout = kb.layer === 'symbols' ? SYMBOLS : kb.layer === 'accents' ? ACCENTS : LETTERS
  const typeKey = useCallback((key) => {
    const base = nameSelected ? '' : null
    const from = (d) => (base === null ? d.name : base)
    if (key === 'shift') setKb((k) => ({ ...k, upper: !k.upper }))
    else if (key === 'symbols') setKb((k) => ({ ...k, layer: k.layer === 'symbols' ? 'letters' : 'symbols' }))
    else if (key === 'accents') setKb((k) => ({ ...k, layer: k.layer === 'accents' ? 'letters' : 'accents' }))
    else if (key === 'space') setDraft((d) => ({ ...d, name: from(d).length < 40 ? `${from(d)} ` : from(d) }))
    else if (key === 'delete') setDraft((d) => ({ ...d, name: base === null ? d.name.slice(0, -1) : '' }))
    else {
      const ch = kb.upper ? key.toUpperCase() : key
      setDraft((d) => ({ ...d, name: from(d).length < 40 ? from(d) + ch : from(d) }))
      if (kb.upper) setKb((k) => ({ ...k, upper: false }))
    }
    if (!['shift', 'symbols', 'accents'].includes(key)) setNameSelected(false)
  }, [kb.upper, nameSelected])

  const finishName = useCallback((keep) => {
    if (!keep && editing) setDraft((d) => ({ ...d, name: editing.name }))
    if (!keep && !editing) {
      leaveEditor()
      return
    }
    setMode('menu')
    setMenuIndex(0)
  }, [editing, leaveEditor])

  const [draftColour, draftFace] = draft.avatar.split('-')
  const iconRows = useMemo(() => [
    { id: 'face', label: 'Face', ids: AVATAR_FACES.map((f) => `${draftColour}-${f}`) },
    { id: 'colour', label: 'Colour', ids: COLOURS.map((c) => `${c}-${draftFace}`) },
  ], [draftColour, draftFace])

  const openIcons = useCallback(() => {
    setIconRow(0)
    setIconCol(Math.max(0, AVATAR_FACES.indexOf(draftFace)))
    setMode('icon')
  }, [draftFace])

  useEffect(() => {
    if (mode !== 'icon') return
    const grid = iconGridRef.current
    const el = iconRowRefs.current[iconRow]
    if (grid && el) grid.scrollTop = Math.max(0, el.offsetTop - 40)
  }, [mode, iconRow])

  const runMenu = useCallback((id) => {
    if (id === 'name') {
      setKb({ row: 1, col: 0, layer: 'letters', upper: true, onActions: false, action: 1 })
      setNameSelected(!!draft.name)
      setMode('name')
    } else if (id === 'icon') openIcons()
    else if (id === 'language') {
      setLangIndex(Math.max(0, LANGUAGES.findIndex((l) => l.id === draft.language)))
      setMode('language')
    } else if (id === 'pin') {
      if (editing && editing.has_pin) {
        setPinMenuIndex(0)
        setMode('pinmenu')
      } else if (editing) askPin('choose', editing)
    } else if (id === 'delete') {
      setConfirmChoice(0)
      setMode('confirm')
    } else if (id === 'done') save()
  }, [draft, openIcons, save, editing, askPin])

  const pinMenu = [
    { id: 'change', label: t('Change PIN'), run: () => askPin('choose', editing) },
    { id: 'remove', label: t('Remove PIN'), run: removePin },
  ]

  useEffect(() => {
    if (mode === 'pin') {
      registerHandler(pinPad.handler)
      return
    }
    registerHandler({
      onDirection: (dir) => {
        if (mode === 'pinmenu') {
          if (dir === 'up') setPinMenuIndex((i) => Math.max(0, i - 1))
          if (dir === 'down') setPinMenuIndex((i) => Math.min(pinMenu.length, i + 1))
          return
        }
        if (mode === 'confirm') {
          if (dir === 'left' || dir === 'right') setConfirmChoice((c) => 1 - c)
          return
        }
        if (mode === 'language') {
          if (dir === 'up') setLangIndex((i) => Math.max(0, i - 1))
          if (dir === 'down') setLangIndex((i) => Math.min(LANGUAGES.length, i + 1))
          return
        }
        if (mode === 'icon') {
          if (dir === 'left') setIconCol((c) => Math.max(0, c - 1))
          if (dir === 'right') setIconCol((c) => Math.min(iconRows[iconRow].ids.length - 1, c + 1))
          if (dir === 'up' && iconRow > 0) {
            setIconRow(0)
            setIconCol(Math.max(0, AVATAR_FACES.indexOf(draftFace)))
          }
          if (dir === 'down' && iconRow < 1) {
            setIconRow(1)
            setIconCol(Math.max(0, COLOURS.indexOf(draftColour)))
          }
          return
        }
        if (mode === 'name') {
          if (kb.onActions) {
            if (dir === 'left') setKb((k) => ({ ...k, action: 0 }))
            if (dir === 'right') setKb((k) => ({ ...k, action: 1 }))
            if (dir === 'up') setKb((k) => ({ ...k, onActions: false, row: layout.length - 1, col: 0 }))
            return
          }
          const row = layout[kb.row]
          if (dir === 'left') setKb((k) => ({ ...k, col: Math.max(0, k.col - 1) }))
          if (dir === 'right') setKb((k) => ({ ...k, col: Math.min(row.length - 1, k.col + 1) }))
          if (dir === 'up' || dir === 'down') {
            const next = kb.row + (dir === 'down' ? 1 : -1)
            if (next >= layout.length) {
              setKb((k) => ({ ...k, onActions: true, action: 1 }))
              return
            }
            if (next < 0) return
            const column = columnsOf(row)[kb.col]
            setKb((k) => ({ ...k, row: next, col: keyAtColumn(layout[next], column) }))
          }
          return
        }
        if (mode === 'menu') {
          if (dir === 'up') setMenuIndex((i) => Math.max(0, i - 1))
          if (dir === 'down') setMenuIndex((i) => Math.min(menu.length - 1, i + 1))
          return
        }
        if (mode === 'switch') {
          if (dir === 'up') setIndex((i) => Math.max(0, i - 1))
          if (dir === 'down') setIndex((i) => Math.min(tiles.length - 1, i + 1))
          if (dir === 'left' && tiles[index] && tiles[index].id !== '__add') setPencil(true)
          if (dir === 'right') setPencil(false)
          return
        }
        if (dir === 'left') setIndex((i) => Math.max(0, i - 1))
        if (dir === 'right') setIndex((i) => Math.min(tiles.length - 1, i + 1))
      },
      onEnter: () => {
        if (busy) return
        if (mode === 'pinmenu') {
          if (pinMenu[pinMenuIndex]) pinMenu[pinMenuIndex].run()
          else setMode('menu')
          return
        }
        if (mode === 'confirm') {
          if (confirmChoice === 1) remove()
          else setMode('menu')
          return
        }
        if (mode === 'language') {
          const choice = LANGUAGES[langIndex]
          if (choice) setDraft((d) => ({ ...d, language: choice.id }))
          setMode('menu')
          return
        }
        if (mode === 'icon') {
          const chosen = iconRows[iconRow].ids[iconCol]
          setDraft((d) => ({ ...d, avatar: chosen }))
          if (iconRow === 0) {
            setIconRow(1)
            setIconCol(Math.max(0, COLOURS.indexOf(chosen.split('-')[0])))
          } else {
            setMode('menu')
          }
          return
        }
        if (mode === 'name') {
          if (kb.onActions) finishName(kb.action === 1)
          else typeKey(layout[kb.row][kb.col])
          return
        }
        if (mode === 'menu') {
          runMenu(menu[menuIndex])
          return
        }
        const tile = tiles[index]
        if (!tile) return
        if (mode === 'manage') return openEditor(tile, 'manage')
        if (tile.id === '__add') return openEditor(null, mode)
        if (tile.id === '__manage') {
          setIndex(0)
          setMode('manage')
          return undefined
        }
        if (mode === 'switch' && pencil) return openEditor(tile, 'switch')
        choose(tile)
        return undefined
      },
      onBack: () => {
        if (mode === 'confirm' || mode === 'language' || mode === 'icon' || mode === 'pinmenu') {
          setMode('menu')
          return true
        }
        if (mode === 'name') {
          finishName(false)
          return true
        }
        if (mode === 'menu') {
          if (editing) save()
          else leaveEditor()
          return true
        }
        if (mode === 'manage') {
          setIndex(0)
          setMode('pick')
          return true
        }
        // Nothing to close back to at launch: Back is left to the system.
        if (!onClose) return false
        onClose()
        return true
      },
    })
  }, [registerHandler, mode, index, pencil, tiles, menu, menuIndex, kb, layout, iconRow, iconCol, iconRows, draftFace, draftColour,
    langIndex, confirmChoice, busy, editing, onPick, onClose, openEditor, runMenu, typeKey, finishName,
    remove, save, leaveEditor, choose, pinPad.handler, pinMenu, pinMenuIndex])

  const preview = (
    <div className="pe-preview">
      <Avatar id={draft.avatar} size={250} />
      <div className="pe-name">
        {mode === 'name' && nameSelected
          ? <span className="name-selected">{draft.name}</span>
          : <>{draft.name || ' '}{mode === 'name' && <span className="caret">|</span>}</>}
      </div>
      {mode !== 'name' && (
        <div className="pe-language">{(LANGUAGES.find((l) => l.id === draft.language) || LANGUAGES[0]).name}</div>
      )}
    </div>
  )

  if (mode === 'pin') return pinPad.view

  if (mode === 'pinmenu') {
    return (
      <div className="profile-editor">
        <h1>{t('Profile PIN')}</h1>
        <p className="pe-sub">{editing && editing.name}</p>
        <div className="pe-languages">
          {pinMenu.map((item, i) => (
            <div
              key={item.id}
              className={`menu-item ${pinMenuIndex === i ? 'focused' : ''}`}
              onMouseEnter={() => setPinMenuIndex(i)}
              onClick={item.run}
            >
              <span>{item.label}</span>
            </div>
          ))}
          <div
            className={`pill-btn small ${pinMenuIndex === pinMenu.length ? 'focused' : ''}`}
            onMouseEnter={() => setPinMenuIndex(pinMenu.length)}
            onClick={() => setMode('menu')}
          >
            {t('Cancel')}
          </div>
        </div>
      </div>
    )
  }

  if (mode === 'menu' || mode === 'confirm') {
    const icons = { name: 'user', icon: 'grid', language: 'globe', pin: 'lock', delete: 'trash' }
    const labels = {
      name: t('Name'),
      icon: t('Icon'),
      language: t('Language'),
      pin: editing && editing.has_pin ? t('Profile PIN: On') : t('Profile PIN: Off'),
      delete: t('Delete Profile'),
    }
    return (
      <div className="profile-editor">
        <h1>{editing ? t('Edit profile') : t('Add a profile')}</h1>
        <p className="pe-sub">{t('Select what you want to change.')}</p>
        <div className="pe-columns">
          <div className="pe-menu">
            {menu.filter((id) => id !== 'done').map((id, i) => (
              <div
                key={id}
                className={`menu-item with-icon ${mode === 'menu' && menuIndex === i ? 'focused' : ''}`}
                onMouseEnter={() => setMenuIndex(i)}
                onClick={() => runMenu(id)}
              >
                <Icon name={icons[id]} size={26} />
                <span>{labels[id]}</span>
              </div>
            ))}
            {error && <div className="pe-error">{error}</div>}
            <div
              className={`pill-btn small ${mode === 'menu' && menu[menuIndex] === 'done' ? 'focused' : ''}`}
              onMouseEnter={() => setMenuIndex(menu.length - 1)}
              onClick={save}
            >
              {busy ? t('Saving...') : editing ? t('Done') : t('Create')}
            </div>
          </div>
          {preview}
        </div>
        {mode === 'confirm' && (
          <div className="scrim">
            <div className="dialog">
              <h2>{t('Delete Profile')}?</h2>
              <p>{editing && editing.name}</p>
              <div className="dialog-actions">
                <div className={`pill-btn ${confirmChoice === 0 ? 'focused' : ''}`}
                  onMouseEnter={() => setConfirmChoice(0)} onClick={() => setMode('menu')}>
                  {t('Keep it')}
                </div>
                <div className={`pill-btn danger ${confirmChoice === 1 ? 'focused' : ''}`}
                  onMouseEnter={() => setConfirmChoice(1)} onClick={remove}>
                  {busy ? t('Deleting...') : t('Delete')}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    )
  }

  if (mode === 'name') {
    return (
      <div className="profile-editor">
        <h1>{editing ? t('Edit profile') : t('Add a profile')}</h1>
        <p className="pe-sub">{t('Anyone who lives with you can enjoy their own profile.')}</p>
        <div className="pe-columns">
          <div className="osk">
            {layout.map((row, ri) => (
              <div className="osk-row" key={ri}>
                {row.map((key, ki) => {
                  const focused = !kb.onActions && kb.row === ri && kb.col === ki
                  let label = kb.upper && key.length === 1 ? key.toUpperCase() : key
                  if (key === 'shift') label = <Icon name="shift" size={22} />
                  if (key === 'symbols') label = kb.layer === 'symbols' ? 'abc' : '!#$'
                  if (key === 'accents') label = kb.layer === 'accents' ? 'abc' : 'àäă'
                  if (key === 'space') label = <span className="kb-space" />
                  if (key === 'delete') label = <BackspaceIcon size={24} />
                  return (
                    <div
                      key={`${ri}-${key}`}
                      className={`osk-key span-${span(key)} ${focused ? 'focused' : ''} ${key === 'shift' && kb.upper ? 'on' : ''}`}
                      onMouseEnter={() => setKb((k) => ({ ...k, onActions: false, row: ri, col: ki }))}
                      onClick={() => typeKey(key)}
                    >
                      {label}
                    </div>
                  )
                })}
              </div>
            ))}
            <div className="osk-actions">
              <div className={`pill-btn small ${kb.onActions && kb.action === 0 ? 'focused' : ''}`}
                onMouseEnter={() => setKb((k) => ({ ...k, onActions: true, action: 0 }))}
                onClick={() => finishName(false)}>
                {t('Cancel')}
              </div>
              <div className={`pill-btn small ${kb.onActions && kb.action === 1 ? 'focused' : ''}`}
                onMouseEnter={() => setKb((k) => ({ ...k, onActions: true, action: 1 }))}
                onClick={() => finishName(true)}>
                {t('Done')}
              </div>
            </div>
          </div>
          {preview}
        </div>
      </div>
    )
  }

  if (mode === 'icon') {
    return (
      <div className="profile-editor icons">
        <div className="pe-icon-head">
          <div>
            <h1>{editing ? t('Edit profile') : t('Add a profile')}</h1>
            <p className="pe-sub">{t('Update your profile icon.')}</p>
          </div>
          <div className="pe-current">
            <span>{draft.name}</span>
            <Avatar id={draft.avatar} size={84} />
          </div>
        </div>
        <div className="icon-rows" ref={iconGridRef}>
          {iconRows.map((r, ri) => (
            <div className={`icon-row ${ri === iconRow ? 'current' : ''}`} key={r.id}
              ref={(el) => { iconRowRefs.current[ri] = el }}>
              <div className="icon-row-name">{t(r.label)}</div>
              <div className="icon-row-strip">
                {r.ids.map((id, ci) => (
                  <div
                    key={id}
                    className={`icon-choice ${ri === iconRow && ci === iconCol ? 'focused' : ''} ${draft.avatar === id ? 'chosen' : ''}`}
                    onMouseEnter={() => {
                      setIconRow(ri)
                      setIconCol(ci)
                    }}
                    onClick={() => {
                      setDraft((d) => ({ ...d, avatar: id }))
                      if (ri === 1) setMode('menu')
                    }}
                  >
                    <Avatar id={id} size={120} />
                  </div>
                ))}
              </div>
            </div>
          ))}
          <div className="list-spacer" />
        </div>
      </div>
    )
  }

  if (mode === 'language') {
    return (
      <div className="profile-editor">
        <h1>{editing ? t('Edit profile') : t('Add a profile')}</h1>
        <p className="pe-sub">{t('Update your language.')}</p>
        <div className="pe-languages">
          {LANGUAGES.map((lang, i) => (
            <div
              key={lang.id}
              className={`menu-item track ${langIndex === i ? "focused" : ""}`}
              onMouseEnter={() => setLangIndex(i)}
              onClick={() => {
                setDraft((d) => ({ ...d, language: lang.id }))
                setMode('menu')
              }}
            >
              <span className="track-tick">{draft.language === lang.id ? <Icon name="check" size={24} /> : null}</span>
              <span>{lang.name}</span>
            </div>
          ))}
          <div
            className={`pill-btn small ${langIndex === LANGUAGES.length ? 'focused' : ''}`}
            onMouseEnter={() => setLangIndex(LANGUAGES.length)}
            onClick={() => setMode('menu')}
          >
            {t('Cancel')}
          </div>
        </div>
      </div>
    )
  }

  if (mode === 'switch') {
    return (
      <div className="profile-switch">
        {backdrop && <div className="ps-art" style={{ backgroundImage: `url(${backdrop})` }} />}
        <div className="ps-shade" />
        <div className="ps-panel">
          <div className="ps-mark"><Wordmark size={30} /></div>
          <div className="ps-caption">{t('Choose a Profile')}</div>
          {tiles.map((p, i) => (
            <div
              key={p.id}
              className={`ps-row ${index === i ? 'current' : ''}`}
              onMouseEnter={() => setIndex(i)}
            >
              <button
                type="button"
                className={`ps-pencil ${index === i && pencil ? 'focused' : ''} ${p.id === '__add' ? 'invisible' : ''}`}
                onMouseEnter={() => setPencil(true)}
                onClick={() => p.id !== '__add' && openEditor(p, 'switch')}
                aria-label={t('Edit profile')}
              >
                <Icon name="pencil" size={24} />
              </button>
              <button
                type="button"
                className={`ps-tile ${index === i && !pencil ? 'focused' : ''}`}
                onMouseEnter={() => setPencil(false)}
                onClick={() => (p.id === '__add' ? openEditor(null, 'switch') : choose(p))}
              >
                {p.id === '__add' ? <span className="ps-add">+</span> : <Avatar id={p.avatar} size={110} />}
              </button>
              <span className="ps-name">{p.name}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  const managing = mode === 'manage'
  return (
    <div className="profiles">
      {managing ? (
        <h1 className="profiles-title">{t('Manage')}</h1>
      ) : (
        <div className="profiles-mark"><VMark size={92} /></div>
      )}
      <div className="profile-row">
        {tiles.map((p, i) => (
          <button
            key={p.id}
            className={`profile-tile ${index === i ? 'focused' : ''}`}
            onMouseEnter={() => setIndex(i)}
            onClick={() => {
              if (managing) return openEditor(p, 'manage')
              if (p.id === '__add') return openEditor(null, 'pick')
              if (p.id === '__manage') {
                setIndex(0)
                return setMode('manage')
              }
              return choose(p)
            }}
          >
            {p.id === '__add' ? (
              <div className="profile-add">+</div>
            ) : p.id === '__manage' ? (
              <div className="profile-add"><Icon name="pencil" size={48} /></div>
            ) : (
              <div className="profile-avatar-wrap">
                <Avatar id={p.avatar} size={150} />
                {managing && <span className="profile-pencil"><Icon name="pencil" size={44} /></span>}
              </div>
            )}
            <span className="profile-name-label">{p.name}</span>
          </button>
        ))}
      </div>
    </div>
  )
}
