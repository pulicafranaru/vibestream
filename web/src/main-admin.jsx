import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './admin/App'
import './shared/fonts/figtree.css'
import './admin/admin.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
