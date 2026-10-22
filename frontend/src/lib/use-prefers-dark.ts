import { useEffect, useState } from 'react'

/**
 * Tracks the `prefers-color-scheme` media query.
 *
 * The force-graph draws on a canvas, so it cannot use CSS variables — the
 * canvas needs the resolved colours, which means it has to know whether the
 * dark scheme is active.
 */
export function usePrefersDark(): boolean {
  const [dark, setDark] = useState(() => {
    if (typeof window === 'undefined' || !window.matchMedia) {
      return false
    }
    return window.matchMedia('(prefers-color-scheme: dark)').matches
  })

  useEffect(() => {
    if (!window.matchMedia) {
      return
    }
    const query = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (event: MediaQueryListEvent) => setDark(event.matches)
    query.addEventListener('change', onChange)
    return () => query.removeEventListener('change', onChange)
  }, [])

  return dark
}
