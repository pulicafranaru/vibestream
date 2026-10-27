import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import legacy from '@vitejs/plugin-legacy'

// webOS 6 is Chromium 79, which cannot parse `?.` or `??`; naming the target compiles them away.
const TV_TARGET = 'chrome79'

// VIBESTREAM_LEGACY_TV=1 builds the TV entry alone for webOS 4.5 (Chromium 53).
const LEGACY = process.env.VIBESTREAM_LEGACY_TV === '1'

// Chromium 53 lacks object spread, module scripts and APIs like Array.prototype.flat,
// so plugin-legacy emits a polyfilled SystemJS bundle.
const LEGACY_TV_TARGET = 'chrome53'
const LEGACY_BROWSERSLIST = ['chrome >= 53']

// `inset` is Chromium 87; unexpanded, every full-bleed overlay collapses on the TV.
// splitValue keeps function arguments whole: "calc(var(--u) * 18) 4px" is two parts.
function splitValue(value) {
  const parts = []
  let depth = 0
  let part = ''
  for (const ch of value.trim()) {
    if (ch === '(') depth += 1
    if (ch === ')') depth -= 1
    if (/\s/.test(ch) && depth === 0) {
      if (part) parts.push(part)
      part = ''
    } else {
      part += ch
    }
  }
  if (part) parts.push(part)
  return parts
}

const expandInset = () => ({
  postcssPlugin: 'vibestream-expand-inset',
  Declaration: {
    inset: (decl) => {
      const parts = splitValue(decl.value)
      const [top, right = top, bottom = top, left = right] = parts
      decl.cloneBefore({ prop: 'top', value: top })
      decl.cloneBefore({ prop: 'right', value: right })
      decl.cloneBefore({ prop: 'bottom', value: bottom })
      decl.cloneBefore({ prop: 'left', value: left })
      decl.remove()
    },
  },
})
expandInset.postcss = true

// Flexbox `gap` is Chromium 84. The margin fallback applies only under a class the app
// adds after detecting the failure; the cross-axis gap of wrapping rows is not handled.
const FALLBACK_SCOPE = 'body.no-flex-gap'

const flexGapFallback = () => ({
  postcssPlugin: 'vibestream-flex-gap-fallback',
  Declaration: {
    gap: (decl, { Rule, Declaration }) => {
      const rule = decl.parent
      if (!rule || rule.type !== 'rule') return

      let display = ''
      let direction = 'row'
      rule.walkDecls((d) => {
        if (d.prop === 'display') display = d.value.trim()
        if (d.prop === 'flex-direction') direction = d.value.trim()
      })
      // Grid gap works on this engine; only flex needs rescuing.
      if (!/(^|-)flex$/.test(display)) return

      // gap: <row> [<column>]; only the main-axis component can become a margin.
      const parts = splitValue(decl.value)
      const [rowGap, columnGap = rowGap] = parts
      const isColumn = direction.indexOf('column') === 0
      const property = isColumn ? 'margin-top' : 'margin-left'
      const value = isColumn ? rowGap : columnGap

      const selector = rule.selectors
        .map((s) => `${FALLBACK_SCOPE} ${s} > * + *`)
        .join(',\n')

      rule.after(
        new Rule({ selector }).append(new Declaration({ prop: property, value })),
      )
    },
  },
})
flexGapFallback.postcss = true

// Dev proxy keeps streaming Range requests same-origin, as in production.
export default defineConfig({
  plugins: [
    react(),
    ...(LEGACY
      ? [legacy({ targets: LEGACY_BROWSERSLIST, renderModernChunks: false })]
      : []),
  ],
  base: LEGACY ? '/legacy/' : '/',
  define: { 'import.meta.env.LEGACY_TV': JSON.stringify(LEGACY) },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.VIBESTREAM_API || 'http://localhost:8100',
        changeOrigin: true,
      },
    },
  },
  css: {
    postcss: { plugins: [expandInset(), flexGapFallback()] },
  },
  build: {
    // Not dist/legacy: the modern build empties dist/ and would delete it.
    outDir: LEGACY ? 'dist-legacy' : 'dist',
    rollupOptions: {
      input: LEGACY
        ? { tv: 'tv.html' }
        : {
            // Relative to the Vite root; __dirname does not exist in an ESM config.
            main: 'index.html',
            tv: 'tv.html',
            admin: 'admin.html',
          },
    },
    sourcemap: false,
    chunkSizeWarningLimit: 900,
    // plugin-legacy overrides `target` but not `cssTarget`.
    ...(LEGACY ? {} : { target: TV_TARGET }),
    cssTarget: LEGACY ? LEGACY_TV_TARGET : TV_TARGET,
  },
})
