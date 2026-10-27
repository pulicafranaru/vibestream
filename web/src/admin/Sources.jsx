import { useEffect, useState } from 'react'
import { Icon } from '../shared/icons'
import { useConfig, PageHead, Panel, Row, NumberInput, SecretInput, Select, Switch, TextInput } from './ui'

const SCHEDULES = [
  { cron: '*/30 * * * *', label: 'Every 30 minutes', perHour: 2 },
  { cron: '17 * * * *', label: 'Every hour', perHour: 1 },
  { cron: '17 */2 * * *', label: 'Every 2 hours', perHour: 1 / 2 },
  { cron: '17 */4 * * *', label: 'Every 4 hours', perHour: 1 / 4 },
  { cron: '17 3 * * *', label: 'Once a day, at night', perHour: 1 / 24 },
]

const LANGUAGE_NAMES = {
  'en-US': 'English (US)', 'en-GB': 'English (UK)', 'de-DE': 'Deutsch', 'ro-RO': 'Română',
  'fr-FR': 'Français', 'es-ES': 'Español', 'it-IT': 'Italiano', 'nl-NL': 'Nederlands',
  'pt-PT': 'Português', 'pt-BR': 'Português (Brasil)', 'pl-PL': 'Polski', 'hu-HU': 'Magyar',
  'sv-SE': 'Svenska', 'da-DK': 'Dansk', 'fi-FI': 'Suomi', 'nb-NO': 'Norsk', 'cs-CZ': 'Čeština',
  'el-GR': 'Ελληνικά', 'tr-TR': 'Türkçe', 'ja-JP': '日本語', 'ko-KR': '한국어', 'zh-CN': '中文',
}

export default function Sources() {
  const c = useConfig()
  if (!c.config) return <PageHead title="Sources" />
  const categories = c.get('filelist_categories') || []
  const cron = c.get('filelist_sweep_cron')
  const known = SCHEDULES.find((s) => s.cron === cron)
  const perHour = categories.length * (known ? known.perHour : 1)

  const toggle = (id) => {
    const next = categories.includes(id) ? categories.filter((x) => x !== id) : [...categories, id]
    c.set('filelist_categories', next.sort((a, b) => a - b))
  }

  return (
    <>
      <PageHead title="Sources" text="Where new releases come from, and where their posters and descriptions come from." />

      <Panel title="Filelist" icon="download" sub="Your account, and what to look for.">
        <div className="rows">
          <Row title="Username" name="filelist_username" text="The name you sign in to filelist with.">
            <TextInput name="filelist_username" placeholder="username" />
          </Row>
          <Row title="Passkey" name="filelist_passkey"
            text="On your filelist profile page, next to Reset passkey (do not tick it). It is also inside every .torrent you have from filelist.">
            <SecretInput name="filelist_passkey" />
          </Row>
          <Row title="Categories" name="filelist_categories" text="Which sections to sweep for new releases." layout="stack">
            <div className="chips">
              {c.config.categories.map((cat) => (
                <button key={cat.id} type="button" className={`chip ${categories.includes(cat.id) ? 'on' : ''}`}
                  onClick={() => toggle(cat.id)}>
                  {cat.name}
                </button>
              ))}
            </div>
          </Row>
          <Row title="How often to look" name="filelist_sweep_cron"
            text={`Each look costs one request per category. Filelist allows 150 an hour; this uses about ${perHour < 1 ? perHour.toFixed(2) : Math.round(perHour)}.`}>
            <select className="input" value={known ? cron : 'custom'}
              onChange={(e) => e.target.value !== 'custom' && c.set('filelist_sweep_cron', e.target.value)}>
              {SCHEDULES.map((s) => <option key={s.cron} value={s.cron}>{s.label}</option>)}
              {!known && <option value="custom">Custom: {cron}</option>}
            </select>
          </Row>
          <Row title="Fewest seeders" name="filelist_min_seeders" text="Releases with fewer people seeding are left out: they download slowly, if at all.">
            <NumberInput name="filelist_min_seeders" unit="seeders" />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Stremio addons" icon="download" sub="Torrentio, Comet, MediaFusion, or your debrid service's own. No account needed.">
        <div className="rows">
          <Row title="Use addons" name="addons_enabled" end
            text="Every addon is asked what it has when a title is opened or searched for, and twice a day for what is trending. Public torrents show your server's address to everybody sharing them.">
            <Switch name="addons_enabled" label="Use addons" />
          </Row>
          <Row title="Addresses" name="addon_urls" layout="stack"
            text="Paste each addon's address as its configure page gives it to you. One set up with a debrid service gives links as well as torrents: films and single episodes are then fetched from the service at full speed, with nobody else's computer involved.">
            <AddressList name="addon_urls" />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="TorBox" icon="download" sub="A debrid service: it downloads releases for you, and this server fetches the finished file.">
        <div className="rows">
          <Row title="API key" name="torbox_api_key"
            text="From torbox.app, under Settings. Films and single episodes the addons find then come through TorBox: at full speed when it already has them, after it downloads them otherwise, and never from this server's address. Filelist releases are never sent to it.">
            <SecretInput name="torbox_api_key" />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="TMDB" icon="film" sub="The Movie Database: titles, posters, cast and descriptions.">
        <div className="rows">
          <Row title="API key" name="tmdb_api_key"
            text="Free, from themoviedb.org under Settings, API. The v3 key, not the long read access token.">
            <SecretInput name="tmdb_api_key" />
          </Row>
          <Row title="Language" name="tmdb_language" text="The language titles and descriptions are fetched in. Titles already fetched change as they are next refreshed.">
            <Select name="tmdb_language"
              options={c.fields.tmdb_language.choices.map((v) => ({ value: v, label: LANGUAGE_NAMES[v] || v }))} />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Privacy" icon="lock" sub="How this server introduces itself to the services above.">
        <div className="rows">
          <Row title="Introduce it as" name="outbound_identity"
            text="As VibeStream, the services can see their users run it, which helps the project. As a browser, requests look like any visitor's and say nothing about this server. Neither ever includes your name, address or accounts.">
            <Select name="outbound_identity" options={[
              { value: 'vibestream', label: 'VibeStream' },
              { value: 'browser', label: 'An ordinary browser' },
            ]} />
          </Row>
          <Row title="Look for updates" name="update_check" end
            text="Every few hours, GitHub is asked whether a newer VibeStream is out, and the overview says so. Nothing is ever installed without you.">
            <Switch name="update_check" label="Look for updates" />
          </Row>
        </div>
      </Panel>
    </>
  )
}

// Blank rows are kept as typed but not saved. A saved address comes back masked
// (it may hold a debrid key), so it can be removed, not edited.
function AddressList({ name }) {
  const c = useConfig()
  const value = c.get(name) || []
  const key = JSON.stringify(value)
  const [rows, setRows] = useState(value.length ? value : [''])
  const filled = (list) => list.map((u) => u.trim()).filter(Boolean)

  useEffect(() => {
    if (JSON.stringify(filled(rows)) !== key) setRows(value.length ? value : [''])
  }, [key])

  const put = (next) => {
    setRows(next.length ? next : [''])
    c.set(name, filled(next))
  }
  // The server identifies a refused address by its index among the filled ones.
  const refused = /Address (\d+)/.exec(c.errors[name] || '')
  let place = 0
  return (
    <div className="address-list">
      {rows.map((url, i) => {
        const number = url.trim() ? ++place : null
        const hidden = url.includes('\u2026')
        return (
          <div className="address-row" key={i}>
            <input className={`input mono ${refused && number === Number(refused[1]) ? 'bad' : ''}`}
              value={url} readOnly={hidden}
              title={hidden ? 'Hidden, as it can hold a debrid key. Remove it and paste it again to change it.' : undefined}
              placeholder="https://torrentio.strem.fun/..." spellCheck={false} autoComplete="off"
              onChange={(e) => put(rows.map((u, j) => (j === i ? e.target.value : u)))} />
            {rows.length > 1 && (
              <button type="button" className="btn quiet small" onClick={() => put(rows.filter((_, j) => j !== i))}
                aria-label="Remove this addon">
                <Icon name="trash" size={16} />
              </button>
            )}
          </div>
        )
      })}
      {rows.length < 8 && (
        <button type="button" className="btn small" onClick={() => setRows([...rows, ''])}>
          <Icon name="plus" size={16} /> Add an addon
        </button>
      )}
    </div>
  )
}
