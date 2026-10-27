import { useEffect, useRef, useState } from 'react'

/*
 * Any element with a `title` gets a styled tooltip. On first hover the title
 * moves to `data-tip` (and aria-label if none), so the browser shows no tooltip of its own.
 */
const DELAY = 350
const GAP = 10
const EDGE = 8

function tipTarget(node) {
  const el = node instanceof Element ? node.closest('[title], [data-tip]') : null
  if (!el) return null
  const title = el.getAttribute('title')
  if (title) {
    el.setAttribute('data-tip', title)
    el.removeAttribute('title')
    if (!el.getAttribute('aria-label') && !el.textContent.trim()) {
      el.setAttribute('aria-label', title)
    }
  }
  return el.getAttribute('data-tip') ? el : null
}

export default function Tooltips() {
  const [tip, setTip] = useState(null)
  const timer = useRef(null)
  const current = useRef(null)
  const bubble = useRef(null)
  const [placed, setPlaced] = useState(null)

  useEffect(() => {
    const hide = () => {
      clearTimeout(timer.current)
      current.current = null
      setTip(null)
      setPlaced(null)
    }
    const over = (event) => {
      if (event.pointerType && event.pointerType !== 'mouse') return
      const el = tipTarget(event.target)
      if (el === current.current) return
      hide()
      if (!el) return
      current.current = el
      timer.current = setTimeout(() => {
        if (current.current !== el || !el.isConnected) return
        // Point at the disc, not the centre, when the control is larger than it.
        const anchor = el.querySelector('[data-tip-anchor]') || el
        setTip({ text: el.getAttribute('data-tip'), box: anchor.getBoundingClientRect() })
      }, DELAY)
    }
    const out = (event) => {
      if (current.current && !current.current.contains(event.relatedTarget)) hide()
    }
    window.addEventListener('pointerover', over, true)
    window.addEventListener('pointerout', out, true)
    window.addEventListener('pointerdown', hide, true)
    window.addEventListener('scroll', hide, true)
    window.addEventListener('keydown', hide, true)
    return () => {
      clearTimeout(timer.current)
      window.removeEventListener('pointerover', over, true)
      window.removeEventListener('pointerout', out, true)
      window.removeEventListener('pointerdown', hide, true)
      window.removeEventListener('scroll', hide, true)
      window.removeEventListener('keydown', hide, true)
    }
  }, [])

  useEffect(() => {
    if (!tip || !bubble.current) return
    const width = bubble.current.offsetWidth
    const height = bubble.current.offsetHeight
    const centre = tip.box.left + tip.box.width / 2
    const viewport = document.documentElement.clientWidth
    const left = Math.min(Math.max(EDGE, centre - width / 2), viewport - EDGE - width)
    const below = tip.box.top - GAP - height < EDGE
    const top = below ? tip.box.bottom + GAP : tip.box.top - GAP - height
    setPlaced({ left, top, below, arrow: centre - left })
  }, [tip])

  if (!tip) return null
  return (
    <div
      ref={bubble}
      className={`tooltip ${placed ? 'shown' : ''} ${placed?.below ? 'below' : ''}`}
      style={placed ? { left: placed.left, top: placed.top, '--arrow': `${placed.arrow}px` } : undefined}
      role="tooltip"
    >
      {tip.text}
    </div>
  )
}
