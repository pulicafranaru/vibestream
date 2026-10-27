import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './web/App'
import Tooltips from './web/Tooltip'
import './shared/fonts/figtree.css'
import './web/web.css'

/* Browser bundle: no webOS Chromium fallbacks here, those belong to the TV bundle. */
createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <>
      <App />
      <Tooltips />
    </>
  </React.StrictMode>,
)
