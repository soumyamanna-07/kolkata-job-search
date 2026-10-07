// Light / dark display. index.html sets the starting theme before the page draws (no white flash);
// this hook lets the header button switch it and remembers the choice in this browser.
import { useState } from 'react'

export function useTheme() {
  const [theme, setTheme] = useState(() => document.documentElement.dataset.theme || 'light')

  function toggle() {
    const next = theme === 'dark' ? 'light' : 'dark'
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('kjs_theme', next)
    } catch { /* private window: the choice lasts until the tab closes */ }
    setTheme(next)
  }

  return { theme, toggle }
}
