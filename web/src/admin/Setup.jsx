import { useEffect, useState } from 'react'
import { Icon } from '../shared/icons'
import { VMark } from '../shared/brand'
import { admin } from './api'

const STEPS = ['filelist', 'tmdb', 'subtitles', 'done']

const SUBTITLE_LANGUAGES = [
  ['en', 'English'], ['ro', 'Română'], ['de', 'Deutsch'], ['fr', 'Français'], ['es', 'Español'],
  ['it', 'Italiano'], ['hu', 'Magyar'], ['nl', 'Nederlands'], ['pt', 'Português'], ['pl', 'Polski'],
  ['sv', 'Svenska'], ['cs', 'Čeština'], ['el', 'Ελληνικά'], ['tr', 'Türkçe'],
]

const TMDB_LANGUAGES = {
  'en-US': 'English (US)', 'en-GB': 'English (UK)', 'de-DE': 'Deutsch', 'ro-RO': 'Română',
  'fr-FR': 'Français', 'es-ES': 'Español', 'it-IT': 'Italiano', 'nl-NL': 'Nederlands',
  'pt-PT': 'Português', 'pt-BR': 'Português (Brasil)', 'pl-PL': 'Polski', 'hu-HU': 'Magyar',
  'sv-SE': 'Svenska', 'da-DK': 'Dansk', 'fi-FI': 'Suomi', 'nb-NO': 'Norsk', 'cs-CZ': 'Čeština',
  'el-GR': 'Ελληνικά', 'tr-TR': 'Türkçe', 'ja-JP': '日本語', 'ko-KR': '한국어', 'zh-CN': '中文',
}

const gigabytes = (bytes) => (bytes == null ? null : Math.floor(bytes / 1024 ** 3))

export default function Setup({ onDone }) {
  const [step, setStep] = useState(0)
  const [config, setConfig] = useState(null)
  const [state, setState] = useState(null)
  const [publicSource, setPublicSource] = useState(false)

  useEffect(() => {
    admin.config().then(setConfig).catch(() => {})
    admin.setup().then((s) => {
      setState(s)
      setPublicSource(s.addons.configured && !s.filelist.configured)
    }).catch(() => {})
  }, [])

  if (!config || !state) return <div className="gate"><span className="spinner" /></div>

  const next = () => setStep((s) => Math.min(STEPS.length - 1, s + 1))
  const back = () => setStep((s) => Math.max(0, s - 1))
  const name = STEPS[step]

  return (
    <div className="gate">
      <div className="gate-card setup-card">
        <span className="gate-mark"><VMark size={48} /></span>
        <ol className="setup-steps" aria-label={`Step ${step + 1} of ${STEPS.length}`}>
          {STEPS.map((s, i) => <li key={s} className={i < step ? 'past' : i === step ? 'now' : ''} />)}
        </ol>
        {name === 'filelist' && (publicSource
          ? <Addons config={config} onNext={next} onFilelist={() => setPublicSource(false)} />
          : <Filelist config={config} onNext={next} onAddons={() => setPublicSource(true)} />)}
        {name === 'tmdb' && <Tmdb config={config} onNext={next} onBack={back} />}
        {name === 'subtitles' && <Subtitles config={config} onNext={next} onBack={back} />}
        {name === 'done' && <Done storage={state.storage} source={publicSource ? 'addons' : 'filelist'}
          onDone={onDone} onBack={back} />}
      </div>
    </div>
  )
}

/** Saves `changes`, then asks the server to test them. Resolves true when they work. */
async function saveAndCheck(changes, step, setError) {
  try {
    await admin.saveConfig(changes)
  } catch (err) {
    const fields = err.detail && err.detail.fields
    setError(fields ? Object.values(fields)[0] : err.message)
    return false
  }
  const result = await admin.checkSetup(step).catch((err) => ({ ok: false, detail: err.message }))
  if (!result.ok) setError(result.detail || 'That did not work.')
  return result.ok
}

// Turns off the unchosen source if it is configured but failing, so the hourly
// sweep does not keep the dashboard red.
async function leaveOffIfBroken(source) {
  const result = await admin.checkSetup(source).catch(() => ({ ok: false }))
  if (result.ok) return
  const off = source === 'filelist' ? { filelist_username: '' } : { addons_enabled: false }
  await admin.saveConfig(off).catch(() => {})
}

function Filelist({ config, onNext, onAddons }) {
  const saved = config.fields.filelist_username.value || ''
  const keySet = config.fields.filelist_passkey.value.set
  const [username, setUsername] = useState(saved)
  const [passkey, setPasskey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    const changes = { filelist_username: username }
    if (passkey) changes.filelist_passkey = passkey
    if (await saveAndCheck(changes, 'filelist', setError)) {
      if (config.fields.addons_enabled.value) await leaveOffIfBroken('addons')
      onNext()
    }
    setBusy(false)
  }

  return (
    <form onSubmit={submit}>
      <h1>Filelist</h1>
      <p className="lead">Where new films and episodes come from.</p>
      <label className="field">
        <span className="field-label">Username</span>
        <input className="input" value={username} onChange={(e) => setUsername(e.target.value)}
          autoComplete="off" autoFocus spellCheck={false} />
      </label>
      <label className="field">
        <span className="field-label">Passkey</span>
        <input className="input mono" type="password" value={passkey} onChange={(e) => setPasskey(e.target.value)}
          placeholder={keySet ? 'Saved. Type to replace it.' : '32 letters and numbers'}
          autoComplete="off" spellCheck={false} />
      </label>
      <p className="setup-help">
        On your filelist profile page, next to Reset passkey (do not tick it). It is also in every
        .torrent you have from filelist, after <span className="mono">reactor.filelist.io/</span>.
      </p>
      <div className="gate-error" role="alert">{error}</div>
      <button className="btn primary wide" disabled={busy || !username || (!passkey && !keySet)}>
        {busy ? <span className="spinner" /> : null}
        Check and continue
      </button>
      <p className="setup-help centred">
        No filelist account? <button type="button" className="link" onClick={onAddons}>Use Stremio addons instead</button>
      </p>
    </form>
  )
}

function Addons({ config, onNext, onFilelist }) {
  const saved = config.fields.addon_urls.value || []
  const [url, setUrl] = useState(saved[0] || '')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    // Only the address on the card: a hidden extra one could fail the check unremovably.
    if (await saveAndCheck({ addons_enabled: true, addon_urls: [url.trim()] }, 'addons', setError)) {
      await leaveOffIfBroken('filelist')
      onNext()
    }
    setBusy(false)
  }

  return (
    <form onSubmit={submit}>
      <h1>Stremio addons</h1>
      <p className="lead">Releases from the addons Stremio uses. No account needed.</p>
      <label className="field">
        <span className="field-label">Addon address</span>
        <input className="input mono" value={url} onChange={(e) => setUrl(e.target.value)}
          autoComplete="off" autoFocus spellCheck={false} />
      </label>
      <p className="setup-help">
        This is Torrentio, set to leave out dubbed copies and camcorder recordings. Any addon's
        address works here, as its configure page gives it to you. Public torrents show your
        server's address to everybody sharing them. Set an addon up with a debrid service and
        most downloads come from the service instead. More addons can be added later, in Sources.
        {saved.length > 1 && ` This replaces the ${saved.length} addresses set up before.`}
      </p>
      <div className="gate-error" role="alert">{error}</div>
      <button className="btn primary wide" disabled={busy || !url.trim()}>
        {busy ? <span className="spinner" /> : null}
        Check and continue
      </button>
      <p className="setup-help centred">
        Have a filelist account? <button type="button" className="link" onClick={onFilelist}>Use filelist</button>
      </p>
    </form>
  )
}

function Tmdb({ config, onNext, onBack }) {
  const keySet = config.fields.tmdb_api_key.value.set
  const [key, setKey] = useState('')
  const [language, setLanguage] = useState(config.fields.tmdb_language.value)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    const changes = { tmdb_language: language }
    if (key) changes.tmdb_api_key = key
    if (await saveAndCheck(changes, 'tmdb', setError)) onNext()
    setBusy(false)
  }

  return (
    <form onSubmit={submit}>
      <h1>TMDB</h1>
      <p className="lead">Posters, descriptions and cast, from The Movie Database.</p>
      <label className="field">
        <span className="field-label">API key</span>
        <input className="input mono" type="password" value={key} onChange={(e) => setKey(e.target.value)}
          placeholder={keySet ? 'Saved. Type to replace it.' : '32 letters and numbers'}
          autoComplete="off" autoFocus spellCheck={false} />
      </label>
      <p className="setup-help">
        Free: make an account at themoviedb.org, then Settings, API. Use the API key, not the long
        read access token.
      </p>
      <label className="field">
        <span className="field-label">Language</span>
        <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
          {config.fields.tmdb_language.choices.map((v) => <option key={v} value={v}>{TMDB_LANGUAGES[v] || v}</option>)}
        </select>
      </label>
      <div className="gate-error" role="alert">{error}</div>
      <div className="setup-buttons">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button className="btn primary" disabled={busy || (!key && !keySet)}>
          {busy ? <span className="spinner" /> : null}
          Check and continue
        </button>
      </div>
    </form>
  )
}

function Subtitles({ config, onNext, onBack }) {
  const [chosen, setChosen] = useState(config.fields.subtitle_languages.value || ['en'])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const toggle = (code) => setChosen((list) => (list.includes(code) ? list.filter((c) => c !== code) : [...list, code]))

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await admin.saveConfig({ subtitle_languages: chosen })
      onNext()
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  return (
    <form onSubmit={submit}>
      <h1>Subtitles</h1>
      <p className="lead">The languages to keep subtitles in, first choice first.</p>
      <div className="chips setup-chips">
        {SUBTITLE_LANGUAGES.map(([code, label]) => {
          const at = chosen.indexOf(code)
          return (
            <button key={code} type="button" className={`chip ${at >= 0 ? 'on' : ''}`} onClick={() => toggle(code)}>
              {at >= 0 && <span className="order">{at + 1}</span>}
              {label}
            </button>
          )
        })}
      </div>
      <div className="gate-error" role="alert">{error}</div>
      <div className="setup-buttons">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button className="btn primary" disabled={busy || !chosen.length}>
          {busy ? <span className="spinner" /> : null}
          Continue
        </button>
      </div>
    </form>
  )
}

function Done({ storage, source, onDone, onBack }) {
  const [busy, setBusy] = useState(false)
  const [finished, setFinished] = useState(false)
  const [error, setError] = useState('')
  const free = gigabytes(storage.free_bytes)

  const finish = async () => {
    setError('')
    setBusy(true)
    try {
      await admin.finishSetup()
      setFinished(true)
    } catch (err) {
      setError(err.message)
    }
    setBusy(false)
  }

  if (finished) {
    return (
      <>
        <h1>Looking for releases</h1>
        <p className="lead">
          {source === 'addons'
            ? "This week's most watched films and shows appear in a minute or two. Anything else turns up when you search for it."
            : 'The first films and shows appear in a minute or two, with their posters soon after.'}
        </p>
        <div className="setup-buttons stacked">
          <a className="btn primary wide" href="/">Open VibeStream</a>
          <button type="button" className="btn wide" onClick={onDone}>Go to the dashboard</button>
        </div>
        <p className="setup-help centred">
          On a TV, phone or tablet, the app finds this server at <span className="mono">{window.location.host}</span>.
        </p>
      </>
    )
  }

  return (
    <>
      <h1>Ready</h1>
      <p className="lead">
        VibeStream looks for new releases {source === 'addons' ? 'twice a day' : 'every hour'}. The first look can start now.
      </p>
      <ul className="setup-facts">
        <li><Icon name="check" size={16} /> {source === 'addons' ? 'The addons answer' : 'Filelist works'}</li>
        <li><Icon name="check" size={16} /> TMDB works</li>
        <li>
          <Icon name="storage" size={16} />
          {free == null ? <>Downloads go to <span className="mono">{storage.path}</span></> : <>{free} GB free for downloads</>}
        </li>
      </ul>
      <div className="gate-error" role="alert">{error}</div>
      <div className="setup-buttons">
        <button type="button" className="btn" onClick={onBack}>Back</button>
        <button type="button" className="btn primary" disabled={busy} onClick={finish}>
          {busy ? <span className="spinner" /> : null}
          Start
        </button>
      </div>
    </>
  )
}
