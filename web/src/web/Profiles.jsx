import { useState } from 'react'
import { api } from '../api'
import Avatar, { allAvatars, AVATAR_COLOURS, AVATAR_FACES } from '../shared/Avatar'
import { Icon } from '../shared/icons'
import { VMark } from '../shared/brand'
import PinDialog from './PinDialog'
import { confirmDialog } from './Confirm'

/* A profile with a PIN asks for it before it is switched to (unless current) and before its editor opens. */

const verdict = (e) => (e.status === 429 ? 'wait' : e.status === 403 ? 'wrong' : 'error')

/**
 * Asking for a profile's PIN before doing something with it: `ask(profile,
 * then)` runs `then(pin)` at once when it has none, or after the right one.
 * Under parental controls an adult without one chooses it first.
 */
function usePinGate(title) {
  const [asking, setAsking] = useState(null)
  const [choosing, setChoosing] = useState(null)
  const ask = (profile, then) => {
    if (profile.needs_pin) setChoosing({ profile, then, step: 'choose' })
    else if (!profile.has_pin) then(null)
    else setAsking({ profile, then })
  }
  const chosen = async (value) => {
    if (choosing.step === 'choose') {
      setChoosing({ ...choosing, step: 'again', first: value })
      return true
    }
    if (value !== choosing.first) return 'mismatch'
    try {
      await api.setPin(choosing.profile.id, value, null)
    } catch (e) {
      return verdict(e)
    }
    setChoosing(null)
    choosing.then(value)
    return true
  }
  const dialog = choosing ? (
    <PinDialog
      profile={choosing.profile}
      title={choosing.step === 'choose' ? 'Choose a PIN' : 'Enter it again'}
      subtitle={choosing.step === 'choose'
        ? 'Parental controls are on, so every adult profile has a PIN. Four digits, asked for when someone chooses this profile.'
        : null}
      onEntered={chosen}
      onClose={() => setChoosing(null)}
    />
  ) : asking && (
    <PinDialog
      profile={asking.profile}
      title={title}
      onClose={() => setAsking(null)}
      onEntered={async (pin) => {
        try {
          await api.checkPin(asking.profile.id, pin)
        } catch (e) {
          return verdict(e)
        }
        setAsking(null)
        asking.then(pin)
        return true
      }}
    />
  )
  return { ask, dialog }
}

// Editing a profile: `open(profile)` asks for its PIN when it has one, then shows the editor;
// `open(null)` makes a new one. `onSaved(saved, opened)` hears what was saved, null when it was
// deleted, and which profile was opened. Render `element` somewhere.
export function useProfileEditor({ onSaved, onPinChanged, guarded = false }) {
  // { profile, pin }, profile null for a new one.
  const [editing, setEditing] = useState(null)
  const gate = usePinGate('Enter the PIN to edit this profile')

  const open = (profile) => {
    if (!profile) setEditing({ profile: null, pin: null })
    else gate.ask(profile, (pin) => setEditing({ profile, pin }))
  }

  const element = (
    <>
      {editing && (
        <Editor
          profile={editing.profile}
          guarded={guarded}
          unlocked={editing.pin}
          onPinChanged={() => onPinChanged && onPinChanged(editing.profile)}
          onClose={() => setEditing(null)}
          onSaved={async (saved) => {
            const opened = editing.profile
            setEditing(null)
            await onSaved(saved, opened)
          }}
        />
      )}
      {gate.dialog}
    </>
  )
  return { open, element }
}

// Who's watching: shown when nobody is chosen yet, and by Switch Profile.
export function ProfileGate({ profiles, guarded, onChoose, onChanged }) {
  const gate = usePinGate('Enter your PIN')
  const editor = useProfileEditor({
    guarded,
    onSaved: async (saved, opened) => {
      await onChanged()
      if (saved && !opened) onChoose(saved)
    },
    onPinChanged: onChanged,
  })

  return (
    <div className="gate">
      <VMark size={64} />
      <div className="gate-grid">
        {profiles.map((profile) => (
          <div key={profile.id} className="gate-cell">
            <button className="gate-tile" onClick={() => gate.ask(profile, async () => {
              // A PIN just chosen: the profile as the server now has it.
              if (profile.needs_pin) await onChanged()
              onChoose({ ...profile, needs_pin: false, has_pin: profile.has_pin || profile.needs_pin })
            })}>
              <Avatar id={profile.avatar} size={140} />
              <span>{profile.name}</span>
            </button>
            <button
              className="gate-edit"
              onClick={() => editor.open(profile)}
              aria-label={`Edit ${profile.name}`}
              title="Edit profile"
            >
              <Icon name="pencil" size={18} />
            </button>
          </div>
        ))}
        {/* Under parental controls, profiles are added in the admin dashboard. */}
        {!guarded && (
          <button className="gate-tile add" onClick={() => editor.open(null)}>
            <span className="plus">+</span>
            <span>Add profile</span>
          </button>
        )}
      </div>

      {editor.element}
      {gate.dialog}
    </div>
  )
}

function Editor({ profile, guarded, unlocked = null, onPinChanged, onClose, onSaved }) {
  const [name, setName] = useState(profile ? profile.name : '')
  const [avatar, setAvatar] = useState(profile ? profile.avatar : allAvatars()[0])
  const [kids, setKids] = useState(profile ? !!profile.is_kids : false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [pin, setPin] = useState(unlocked)
  const [hasPin, setHasPin] = useState(profile ? !!profile.has_pin : false)
  const [choosing, setChoosing] = useState(null)

  const removePin = async () => {
    setError(null)
    try {
      await api.setPin(profile.id, null, pin)
      setPin(null)
      setHasPin(false)
      onPinChanged()
    } catch (e) {
      setError(e.message)
    }
  }

  const pinEntered = async (value) => {
    if (choosing.step === 'choose') {
      setChoosing({ step: 'again', chosen: value })
      return true
    }
    if (value !== choosing.chosen) return 'mismatch'
    try {
      await api.setPin(profile.id, value, pin)
    } catch (e) {
      return verdict(e)
    }
    setPin(value)
    setHasPin(true)
    setChoosing(null)
    onPinChanged()
    return true
  }

  const save = async () => {
    if (!name.trim()) return
    setBusy(true)
    setError(null)
    try {
      const saved = profile
        ? await api.updateProfile(profile.id, guarded
          ? { name: name.trim(), avatar }
          : { name: name.trim(), avatar, is_kids: kids }, pin)
        : await api.createProfile(name.trim(), avatar, undefined, kids)
      await onSaved(saved)
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  const remove = async () => {
    if (!await confirmDialog({
      title: `Delete ${profile.name}?`,
      message: 'Its progress, ratings and Watchlist go with it. Everything downloaded stays.',
      action: 'Delete Profile',
    })) return
    setBusy(true)
    try {
      await api.deleteProfile(profile.id, pin)
      await onSaved(null)
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="sheet-backdrop" onClick={onClose}>
      <div className="sheet narrow" onClick={(e) => e.stopPropagation()}>
        <button className="sheet-close" onClick={onClose} aria-label="Close"><Icon name="close" size={22} /></button>
        <div className="sheet-body">
          <h2>{profile ? 'Edit profile' : 'New profile'}</h2>

          <label className="field">
            <span>Name</span>
            <input
              value={name}
              autoFocus
              maxLength={40}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && save()}
            />
          </label>

          <span className="field-label">Avatar</span>
          <div className="avatar-grid">
            {AVATAR_FACES.map((face) => {
              const id = `${avatar.split('-')[0]}-${face}`
              return (
                <button key={id} className={id === avatar ? 'on' : ''} onClick={() => setAvatar(id)} aria-label={face}>
                  <Avatar id={id} size={56} />
                </button>
              )
            })}
          </div>
          <div className="avatar-colours">
            {Object.keys(AVATAR_COLOURS).map((colour) => (
              <button
                key={colour}
                className={avatar.split('-')[0] === colour ? 'on' : ''}
                onClick={() => setAvatar(`${colour}-${avatar.split('-')[1] || 'smile'}`)}
                aria-label={colour}
                title={colour}
                style={{ background: `linear-gradient(${AVATAR_COLOURS[colour][0]}, ${AVATAR_COLOURS[colour][1]})` }}
              />
            ))}
          </div>

          <div className="editor-settings">
            {guarded ? (
              <div className="editor-setting">
                <div>
                  <div className="editor-setting-title">{kids ? 'Kids profile' : 'Adult profile'}</div>
                  <div className="editor-setting-detail">
                    {kids
                      ? `Parental controls are on: titles rated up to ${profile.max_maturity_label}. Changed in the admin dashboard.`
                      : 'Parental controls are on, so this profile keeps a PIN.'}
                  </div>
                </div>
              </div>
            ) : (
            <div className="editor-setting">
              <div className="editor-setting-title">Kids profile</div>
              <button
                type="button"
                role="switch"
                aria-checked={kids}
                aria-label="Kids profile"
                className={`switch ${kids ? 'on' : ''}`}
                onClick={() => setKids((v) => !v)}
              >
                <span className="switch-knob" />
              </button>
            </div>
            )}
            {profile && !(guarded && kids) && (
              <div className="editor-setting">
                <div>
                  <div className="editor-setting-title">
                    PIN
                    {hasPin && (
                      <button type="button" className="link editor-setting-link" onClick={() => setChoosing({ step: 'choose' })}>
                        Change
                      </button>
                    )}
                  </div>
                  <div className="editor-setting-detail">
                    {hasPin ? 'Asked for when someone chooses this profile.' : 'Anyone can choose this profile.'}
                  </div>
                </div>
                <button
                  type="button"
                  role="switch"
                  aria-checked={hasPin}
                  aria-label="PIN"
                  className={`switch ${hasPin ? 'on' : ''}`}
                  disabled={guarded && hasPin}
                  onClick={() => (hasPin ? removePin() : setChoosing({ step: 'choose' }))}
                >
                  <span className="switch-knob" />
                </button>
              </div>
            )}
          </div>

          {error && <p className="note error">{error}</p>}

          <div className="editor-footer">
            {profile && !(guarded && kids) && (
              <button type="button" className="editor-delete" onClick={remove} disabled={busy}>
                Delete Profile
              </button>
            )}
            <div className="editor-footer-end">
              <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
              <button className="btn primary" onClick={save} disabled={busy || !name.trim()}>
                Save
              </button>
            </div>
          </div>
        </div>
      </div>
      {choosing && (
        <PinDialog
          profile={profile}
          title={choosing.step === 'choose' ? 'Choose a PIN' : 'Enter it again'}
          subtitle={choosing.step === 'choose' ? 'Four digits, asked for when someone chooses this profile.' : null}
          onEntered={pinEntered}
          onClose={() => setChoosing(null)}
        />
      )}
    </div>
  )
}
