import React from 'react'
import { createRoot } from 'react-dom/client'
// AMK's fonts: Lato for English, Kantumruy Pro for Khmer (bundled, so the TV needs no internet for them)
import '@fontsource/lato/latin-400.css'
import '@fontsource/lato/latin-700.css'
import '@fontsource/lato/latin-900.css'
import '@fontsource/kantumruy-pro/khmer-400.css'
import '@fontsource/kantumruy-pro/khmer-700.css'
import App from './App.jsx'
import './styles.css'

createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
