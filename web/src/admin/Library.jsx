import { useEffect, useState } from 'react'
import { Icon } from '../shared/icons'
import { admin } from './api'
import { bytes, NumberInput, PageHead, Panel, Ring, Row, Switch, TextInput, useConfig, useToast } from './ui'

export default function Library() {
  const c = useConfig()
  const [disks, setDisks] = useState(null)
  const [preview, setPreview] = useState(null)
  const [busy, setBusy] = useState(false)
  const say = useToast()

  useEffect(() => { admin.overview().then((o) => setDisks(o.disks)).catch(() => {}) }, [])

  const dryRun = async () => {
    setBusy(true)
    try {
      setPreview(await admin.reap(true))
    } catch (e) {
      say(e.message, true)
    } finally {
      setBusy(false)
    }
  }

  if (!c.config) return <PageHead title="Library & storage" />
  const live = c.get('playback_engine') === 'live'

  return (
    <>
      <PageHead title="Library & storage" text="Where films and shows are kept, and how room is made when the disk fills up." />

      <div className="grid two" style={{ marginBottom: 18 }}>
        <Panel title="Folders" icon="storage" className="span-2"
          sub="Full paths as the server sees them, inside its container. Changing one does not move what is already there.">
          <div className="rows">
            <Row title="Movies" name="movies_dir" layout="wide"><TextInput name="movies_dir" mono /></Row>
            <Row title="Shows" name="shows_dir" layout="wide"><TextInput name="shows_dir" mono /></Row>
          </div>
        </Panel>
      </div>

      <Panel title="Disks" icon="storage" sub="Every disk the library and downloads are on.">
        {!disks && <div className="skeleton" style={{ height: 92 }} />}
        {disks && disks.length === 0 && <div className="empty">None of the folders exist on the server.</div>}
        {disks && disks.map((d, i) => {
          const used = d.total - d.free
          return (
            <div className="disk" key={i}>
              <Ring used={used} total={d.total} />
              <div style={{ flex: 1 }}>
                <b>{d.labels.join(', ')}</b>
                <div className="dim">{bytes(used)} used, {bytes(d.free)} free of {bytes(d.total)}</div>
                <div className="paths mono">{d.paths.join('  ')}</div>
              </div>
            </div>
          )
        })}
      </Panel>

      <div style={{ height: 18 }} />

      <Panel title="Making room" icon="trash"
        sub="Watched titles can be removed on their own when space runs low. Off, nothing is ever deleted unless someone deletes it."
        action={(
          <button className="btn small" onClick={dryRun} disabled={busy}>
            {busy ? <span className="spinner" /> : <Icon name="search" size={15} />} Preview
          </button>
        )}>
        <div className="rows">
          <Row title="Remove watched titles automatically" name="reaper_enabled" end>
            <Switch name="reaper_enabled" label="Remove watched titles automatically" />
          </Row>
          <Row title="Keep at least this much free" name="reaper_min_free_gb" text="Removing starts only once free space falls below this.">
            <NumberInput name="reaper_min_free_gb" unit="GB" />
          </Row>
          <Row title="Days after watching" name="reaper_grace_days" text="A finished title stays this long after it was last played.">
            <NumberInput name="reaper_grace_days" unit="days" />
          </Row>
          <Row title="Seed for at least" name="reaper_min_seed_hours"
            text="Filelist expects what you download to be shared back. Nothing goes before it has seeded this long, or reached the ratio below.">
            <NumberInput name="reaper_min_seed_hours" unit="hours" />
          </Row>
          <Row title="Or up to a ratio of" name="reaper_min_seed_ratio" text="Uploaded divided by downloaded. 1 means you gave back as much as you took.">
            <NumberInput name="reaper_min_seed_ratio" step={0.1} />
          </Row>
          <Row title="Remove originals once converted" name="sources_auto_remove" end
            text={live
              ? 'Only applies with converted playback. Live playback streams from the original, so it is always kept.'
              : 'After seeding, the original file goes and the converted copy stays, which halves the space a title takes.'}>
            <Switch name="sources_auto_remove" label="Remove originals once converted" />
          </Row>
        </div>

        {preview && (
          <div className="result">
            <table>
              <tbody>
                <tr><td>Titles looked at</td><td>{preview.considered}</td></tr>
                <tr><td>Would be removed</td><td>{preview.reaped.length}</td></tr>
                <tr><td>Space it would free</td><td>{preview.gb_freed} GB</td></tr>
                <tr><td>Free now</td><td>{preview.free_before_gb} GB</td></tr>
              </tbody>
            </table>
            {preview.reaped.length > 0 && (
              <ul className="dim" style={{ margin: '10px 0 0', paddingLeft: 18 }}>
                {preview.reaped.slice(0, 12).map((name) => <li key={name}>{name}</li>)}
              </ul>
            )}
            <p className="faint" style={{ margin: '10px 0 0' }}>A preview only. Nothing was deleted.</p>
          </div>
        )}
      </Panel>
    </>
  )
}
