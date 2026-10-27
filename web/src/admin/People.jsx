import { useEffect, useState } from 'react'
import Avatar from '../shared/Avatar'
import { Icon } from '../shared/icons'
import { admin } from './api'
import { ago, PageHead, Panel, useToast } from './ui'

/* A phone or tablet belongs to the profile it was last used as (routers/cast.py). */

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
  const [devices, setDevices] = useState(null)
  const [renaming, setRenaming] = useState(null)
  const say = useToast()

  const load = () => {
    admin.profiles().then((r) => setProfiles(r.profiles)).catch(() => {})
    admin.devices().then((r) => setDevices(r.devices)).catch(() => {})
  }
  useEffect(load, [])

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

      <Panel title="Profiles" icon="user" sub="Profiles are made and edited in the apps. A PIN can be taken away here.">
        {!profiles && <div className="skeleton" style={{ height: 120 }} />}
        <div className="grid four">
          {(profiles || []).map((p) => (
            <div key={p.id} className="panel" style={{ background: 'var(--panel-2)', textAlign: 'center', padding: '22px 16px 16px' }}>
              <div style={{ display: 'inline-block' }}><Avatar id={p.avatar} size={72} /></div>
              <div style={{ fontWeight: 700, marginTop: 10 }}>{p.name}</div>
              <div className="faint" style={{ fontSize: 12.5 }}>
                {p.last_used_at ? `Last in ${ago(p.last_used_at)}` : 'Not used yet'}
              </div>
              <div style={{ marginTop: 12, minHeight: 30 }}>
                {p.has_pin ? (
                  <>
                    <span className="badge good" style={{ marginRight: 8 }}><Icon name="lock" size={11} /> PIN</span>
                    <button className="btn small quiet" onClick={() => resetPin(p)}>Remove PIN</button>
                  </>
                ) : <span className="badge">No PIN</span>}
              </div>
            </div>
          ))}
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
