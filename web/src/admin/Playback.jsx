import { Icon } from '../shared/icons'
import { NumberInput, PageHead, Panel, Row, SecretInput, useConfig } from './ui'

const ENGINES = [
  {
    id: 'live',
    title: 'Live',
    text: 'Plays straight from the downloaded file, prepared a few seconds at a time as it is watched.',
    points: ['Ready to watch as soon as the download finishes', 'One copy of each title on disk', 'Keeps every original file'],
  },
  {
    id: 'renditions',
    title: 'Converted',
    text: 'Each title is converted for streaming once it has downloaded, then played from that copy.',
    points: ['A wait after each download while it converts', 'Two copies while converting; the original can then go', 'The way VibeStream always worked'],
  },
]

const LANGUAGES = {
  en: 'English', ro: 'Română', de: 'Deutsch', fr: 'Français', es: 'Español', it: 'Italiano',
  hu: 'Magyar', nl: 'Nederlands', pt: 'Português', pl: 'Polski', sv: 'Svenska', tr: 'Türkçe',
  el: 'Ελληνικά', ru: 'Русский', uk: 'Українська', cs: 'Čeština', bg: 'Български', ja: '日本語',
}

export default function Playback() {
  const c = useConfig()
  if (!c.config) return <PageHead title="Playback" />
  const engine = c.get('playback_engine')
  const chosen = c.get('subtitle_languages') || []

  const toggleLanguage = (code) => {
    c.set('subtitle_languages', chosen.includes(code) ? chosen.filter((x) => x !== code) : [...chosen, code])
  }

  return (
    <>
      <PageHead title="Playback" text="How titles get to the screen, and the subtitles that come with them." />

      <Panel title="Engine" icon="now-playing" sub="Either can be switched to at any time, and switched back.">
        <div className="choices">
          {ENGINES.map((e) => (
            <button key={e.id} type="button" className={`choice ${engine === e.id ? 'on' : ''}`}
              onClick={() => c.set('playback_engine', e.id)}>
              <h3><span className="radio" /> {e.title}</h3>
              <p>{e.text}</p>
              <ul>{e.points.map((p) => <li key={p}>{p}</li>)}</ul>
            </button>
          ))}
        </div>
        {c.errors.playback_engine && <p className="row-error">{c.errors.playback_engine}</p>}
        {c.fields.playback_engine.changed_at && (
          <p className="faint" style={{ margin: '12px 0 0', fontSize: 12.5 }}>
            Set here. <button className="link" onClick={() => c.reset('playback_engine')}>Use the value from .env</button>
          </p>
        )}
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Quality" icon="film">
        <div className="rows">
          <Row title="Largest release to prefer" name="quality_max_gb"
            text="Bigger releases are still offered, just ranked below ones under this size. A 60 GB remux is not a better watch than a 20 GB one, only a longer download.">
            <NumberInput name="quality_max_gb" unit="GB" />
          </Row>
        </div>
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Subtitles" icon="subtitles"
        sub="Subtitles inside the file always come first. Languages missing from it are looked up on OpenSubtitles, when a key is set.">
        <div className="rows">
          <Row title="Languages, in order" name="subtitle_languages" text="Tap to add or remove. The first is the one offered first." layout="stack">
            <div className="chips">
              {chosen.map((code, i) => (
                <button key={code} type="button" className="chip on" onClick={() => toggleLanguage(code)}>
                  <span className="order">{i + 1}</span>{LANGUAGES[code] || code}<Icon name="close" size={12} />
                </button>
              ))}
              {Object.keys(LANGUAGES).filter((code) => !chosen.includes(code)).map((code) => (
                <button key={code} type="button" className="chip" onClick={() => toggleLanguage(code)}>
                  {LANGUAGES[code]}
                </button>
              ))}
            </div>
          </Row>
          <Row title="OpenSubtitles API key" name="opensubtitles_api_key" text="Optional. Free from opensubtitles.com, under API consumers.">
            <SecretInput name="opensubtitles_api_key" />
          </Row>
        </div>
      </Panel>
    </>
  )
}
