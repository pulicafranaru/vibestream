import { useEffect, useState } from 'react'
import Avatar from '../shared/Avatar'
import { Icon } from '../shared/icons'
import { admin } from './api'
import { ago, PageHead, Panel, Row, Switch, useConfig, useToast } from './ui'

// The household: its profiles, and the devices VibeStream is open on. A forgotten PIN is cleared
// here, since nobody else can. Under parental controls this is also the only place profiles are
// made, made kids or adults, and given a maturity ceiling.

function DeviceGlyph({ kind }) {
  if (kind === 'phone' || kind === 'tablet') {
    const tall = kind === 'phone'
    return (
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
        <rect x={tall ? 7 : 4.5} y={tall ? 2.5 : 3} width={tall ? 10 : 15} height={tall ? 19 : 18} rx="2.5" />
        <path d={tall ? 'M11 18.5h2' : 'M11 18h2'} strokeLinecap="round" />
      </svg>
    )
  }
  return <Icon name={kind === 'web' ? 'globe' : 'tv'} size={20} />
}

export default function People() {
  const [profiles, setProfiles] = useState(null)
  const [household, setHousehold] = useState(null)
  const [devices, setDevices] = useState(null)
  const [renaming, setRenaming] = useState(null)
  const [pinning, setPinning] = useState(null)
  const c = useConfig()
  const say = useToast()
  const saved = c.fields.parental_controls && c.fields.parental_controls.value

  const load = () => {
    admin.profiles().then((r) => {
      setProfiles(r.profiles)
      setHousehold(r)
    }).catch(() => {})
    admin.devices().then((r) => setDevices(r.devices)).catch(() => {})
  }
  useEffect(load, [])
  // Once saved, the profiles say what the setting now means for them.
  useEffect(load, [saved])
  const guarded = !!(household && household.parental_controls)

  const act = async (fn, message) => {
    try {
      await fn()
      if (message) say(message)
      load()
    } catch (e) {
      say(e.message, true)
    }
  }

  const setPin = (p, pin) => act(async () => {
    await admin.setPin(p.id, pin)
    setPinning(null)
  }, `${p.name} has a new PIN.`)

  const remove = (p) => {
    if (!window.confirm(`Remove ${p.name}? What it watched, liked and saved goes with it.`)) return
    act(() => admin.removeProfile(p.id), `${p.name} is gone.`)
  }

  const resetPin = async (p) => {
    if (!window.confirm(`Remove ${p.name}'s PIN? Anyone will be able to choose the profile until a new one is set.`)) return
    try {
      await admin.resetPin(p.id)
      say(`${p.name} has no PIN now.`)
      load()
    } catch (e) {
      say(e.message, true)
    }
  }

  const change = async (d, body, message) => {
    try {
      setDevices((await admin.changeDevice(d.id, body)).devices)
      if (message) say(message)
    } catch (e) {
      say(e.message, true)
    }
  }

  const forget = async (d) => {
    if (!window.confirm(`Forget ${d.name || d.own_name || 'this device'}? Its name and owner go; if it is open, it comes back as new.`)) return
    try {
      setDevices((await admin.forgetDevice(d.id)).devices)
    } catch (e) {
      say(e.message, true)
    }
  }

  const nameOf = (id) => (profiles || []).find((p) => p.id === id)?.name
  const screens = devices && devices.filter((d) => !d.personal)
  const mobiles = devices && devices.filter((d) => d.personal)

  const deviceList = (list, empty, owner) => (
    <>
      {!list && <div className="skeleton" style={{ height: 120 }} />}
      {list && list.length === 0 && <div className="empty">{empty}</div>}
      <div className="list">
        {(list || []).map((d) => (
          <div className="item" key={d.id}>
            <span className="device-icon"><DeviceGlyph kind={d.kind} /></span>
            <div className="item-main">
              {renaming === d.id ? (
                <form onSubmit={(e) => {
                  e.preventDefault()
                  change(d, { name: e.target.elements.name.value }, 'Renamed.')
                  setRenaming(null)
                }}>
                  <input name="name" className="input" defaultValue={d.name || d.own_name || ''} autoFocus
                    onBlur={() => setRenaming(null)} style={{ height: 32, maxWidth: 280 }} />
                </form>
              ) : (
                <b>{d.name || d.own_name || 'Unnamed device'}</b>
              )}
              <span>
                <span className={`dot ${d.online ? 'good' : ''}`} style={{ marginRight: 6 }} />
                {d.online ? (d.playing ? `Playing ${d.playing}` : 'Open now') : 'Not open'}
                {d.name && d.own_name && d.name !== d.own_name ? `  ·  ${d.own_name}` : ''}
              </span>
            </div>
            <div className="item-side">
              {owner(d)}
              <button className="btn small quiet" onClick={() => setRenaming(d.id)} title="Rename"><Icon name="pencil" size={14} /></button>
              <button className="btn small quiet danger" onClick={() => forget(d)} title="Forget"><Icon name="trash" size={14} /></button>
            </div>
          </div>
        ))}
      </div>
    </>
  )

  return (
    <>
      <PageHead title="People & devices" text="Who watches, and what they watch on." />

      <Panel title="Parental controls" icon="lock" sub="For a household with children.">
        <div className="rows">
          <Row title="Parental controls" name="parental_controls" end
            text="Every adult profile needs a PIN, profiles are added only here, and each kids profile sees titles up to the rating chosen for it below. A title with no rating is never shown to a kids profile.">
            <Switch name="parental_controls" label="Parental controls" />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Profiles" icon="user"
        sub={guarded
          ? 'Kids profiles have no PIN. An adult without one is asked to choose it the next time it is picked, or you can set it here.'
          : 'Profiles are made and edited in the apps. A PIN can be taken away here.'}>
        {!profiles && <div className="skeleton" style={{ height: 120 }} />}
        <div className="grid four">
          {(profiles || []).map((p) => (
            <div key={p.id} className="panel profile-card">
              <div style={{ display: 'inline-block' }}><Avatar id={p.avatar} size={72} /></div>
              <div style={{ fontWeight: 700, marginTop: 10 }}>{p.name}</div>
              <div className="faint" style={{ fontSize: 12.5 }}>
                {p.last_used_at ? `Last in ${ago(p.last_used_at)}` : 'Not used yet'}
              </div>
              {guarded && household && (
                <div className="profile-kind">
                  <select className="input" value={p.is_kids ? 'kids' : 'adult'} aria-label={`${p.name}: adult or kids`}
                    onChange={(e) => act(() => admin.changeProfile(p.id, { is_kids: e.target.value === 'kids' }))}>
                    <option value="adult">Adult</option>
                    <option value="kids">Kids</option>
                  </select>
                  {p.is_kids && (
                    <select className="input" value={p.max_maturity ?? household.default_level} aria-label={`${p.name}: highest rating`}
                      onChange={(e) => act(() => admin.changeProfile(p.id, { max_maturity: Number(e.target.value) }),
                        `${p.name} now sees titles rated up to ${e.target.selectedOptions[0].text}.`)}>
                      {household.levels.map((l) => <option key={l.value} value={l.value}>Up to {l.label}</option>)}
                    </select>
                  )}
                </div>
              )}
              <div style={{ marginTop: 12, minHeight: 30 }}>
                {pinning === p.id ? (
                  <form className="pin-form" onSubmit={(e) => { e.preventDefault(); setPin(p, e.target.elements.pin.value) }}>
                    <input name="pin" className="input mono" inputMode="numeric" pattern="[0-9]{4}" maxLength={4}
                      placeholder="4 digits" autoFocus required aria-label={`New PIN for ${p.name}`} />
                    <button className="btn small primary" type="submit">Set</button>
                    <button className="btn small quiet" type="button" onClick={() => setPinning(null)}>Cancel</button>
                  </form>
                ) : p.is_kids && guarded ? (
                  <span className="badge">No PIN, as a kids profile</span>
                ) : p.has_pin ? (
                  <>
                    <span className="badge good" style={{ marginRight: 8 }}><Icon name="lock" size={11} /> PIN</span>
                    {guarded
                      ? <button className="btn small quiet" onClick={() => setPinning(p.id)}>Change</button>
                      : <button className="btn small quiet" onClick={() => resetPin(p)}>Remove PIN</button>}
                  </>
                ) : (
                  <>
                    <span className={`badge ${p.needs_pin ? 'warn' : ''}`} style={{ marginRight: 8 }}>
                      {p.needs_pin ? 'Needs a PIN' : 'No PIN'}
                    </span>
                    {guarded && <button className="btn small quiet" onClick={() => setPinning(p.id)}>Set PIN</button>}
                  </>
                )}
              </div>
              {guarded && profiles.length > 1 && (
                <button className="btn small quiet danger profile-remove" onClick={() => remove(p)}
                  title={`Remove ${p.name}`} aria-label={`Remove ${p.name}`}>
                  <Icon name="trash" size={14} />
                </button>
              )}
            </div>
          ))}
          {guarded && household && <NewProfile household={household} onMade={(p) => act(() => {}, `${p.name} is ready.`)} />}
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="TVs and browsers" icon="tv"
        sub="Shared with everyone, unless given to one profile. Then only that profile can send it something to play.">
        {deviceList(screens, 'No TV or browser has VibeStream open right now.', (d) => (
          <select className="input" style={{ height: 32, width: 160 }} value={d.owner_id || 0}
            onChange={(e) => change(d, { owner_id: Number(e.target.value) },
              Number(e.target.value) ? `Now ${nameOf(Number(e.target.value))}'s.` : 'Now shared.')}>
            <option value={0}>Shared</option>
            {(profiles || []).map((p) => <option key={p.id} value={p.id}>{p.name}'s</option>)}
          </select>
        ))}
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Phones and tablets" icon="user"
        sub="Each belongs to the profile last used on it, and only that profile can send it something to play.">
        {deviceList(mobiles, 'No phone or tablet has used VibeStream yet.', (d) => (
          d.owner_id && nameOf(d.owner_id)
            ? <span className="badge">{nameOf(d.owner_id)}'s</span>
            : <span className="badge">Not used as anyone yet</span>
        ))}
      </Panel>
    </>
  )
}

// Under parental controls, the one place a profile is made.
function NewProfile({ household, onMade }) {
  const [name, setName] = useState('')
  const [kids, setKids] = useState(true)
  const [level, setLevel] = useState(household.default_level)
  const [busy, setBusy] = useState(false)
  const say = useToast()
  const taken = new Set(household.profiles.map((p) => p.avatar))
  const avatar = household.avatars.find((a) => !taken.has(a)) || household.avatars[0]

  const submit = async (e) => {
    e.preventDefault()
    setBusy(true)
    try {
      const made = await admin.makeProfile({ name, avatar, is_kids: kids, max_maturity: kids ? level : null })
      setName('')
      onMade(made)
    } catch (err) {
      say(err.message, true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel profile-card new" onSubmit={submit}>
      <div style={{ display: 'inline-block', opacity: name ? 1 : 0.45 }}><Avatar id={avatar} size={72} /></div>
      <input className="input" value={name} onChange={(e) => setName(e.target.value)} placeholder="New profile's name"
        maxLength={64} required aria-label="New profile's name" style={{ marginTop: 10 }} />
      <div className="profile-kind">
        <select className="input" value={kids ? 'kids' : 'adult'} onChange={(e) => setKids(e.target.value === 'kids')}
          aria-label="Adult or kids">
          <option value="kids">Kids</option>
          <option value="adult">Adult</option>
        </select>
        {kids && (
          <select className="input" value={level} onChange={(e) => setLevel(Number(e.target.value))} aria-label="Highest rating">
            {household.levels.map((l) => <option key={l.value} value={l.value}>Up to {l.label}</option>)}
          </select>
        )}
      </div>
      <button className="btn small primary" type="submit" disabled={busy || !name.trim()} style={{ marginTop: 12 }}>
        <Icon name="plus" size={14} /> Add profile
      </button>
      {!kids && <div className="faint" style={{ fontSize: 12, marginTop: 8 }}>Asked to choose a PIN the first time it is picked.</div>}
    </form>
  )
}
