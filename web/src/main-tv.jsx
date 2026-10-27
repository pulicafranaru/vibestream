import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './tv/App'
import { setBase } from './tv/router'

// Measured, not asked: CSS.supports says yes on webOS 6.0, where grid gap works but flex gap does not.
function flexGapSupported() {
  const probe = document.createElement('div')
  probe.style.cssText =
    'position:absolute;top:-9999px;left:-9999px;display:flex;gap:40px'
  for (let i = 0; i < 2; i += 1) {
    const child = document.createElement('div')
    child.style.cssText = 'width:10px;height:10px'
    probe.appendChild(child)
  }
  document.body.appendChild(probe)
  const supported = probe.getBoundingClientRect().width > 25
  probe.remove()
  return supported
}

// Measured, not asked: Chromium 53 (webOS 4.5) has no CSS Grid.
function cssGridSupported() {
  const probe = document.createElement('div')
  probe.style.cssText =
    'position:absolute;top:-9999px;left:-9999px;width:100px;' +
    'display:grid;grid-template-columns:repeat(2,1fr)'
  for (let i = 0; i < 2; i += 1) {
    const child = document.createElement('div')
    child.style.cssText = 'height:10px'
    probe.appendChild(child)
  }
  document.body.appendChild(probe)
  // Indexed, not destructured: an HTMLCollection is not reliably iterable on Chromium 53.
  const first = probe.children[0].getBoundingClientRect()
  const second = probe.children[1].getBoundingClientRect()
  probe.remove()
  return first.top === second.top
}

// Without stageReady the webOS splash stays over the window for about nine seconds.
{
  const sys = window.webOSSystem || window.PalmSystem
  if (sys && sys.stageReady) sys.stageReady()
}

if (!flexGapSupported()) document.body.classList.add('no-flex-gap')
// Legacy webOS 4.5 bundle: some effects are disabled in the stylesheet as too slow.
if (import.meta.env.LEGACY_TV) document.body.classList.add('legacy-tv')
if (!cssGridSupported()) document.body.classList.add('no-css-grid')

// The base must match where the bundle was served from: the router rewrites the URL on startup.
setBase(import.meta.env.LEGACY_TV ? '/legacy/tv' : '/tv')

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
