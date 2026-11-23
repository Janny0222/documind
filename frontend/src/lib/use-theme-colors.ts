import { useSyncExternalStore } from 'react'

const read = (names: readonly string[]) => {
  const css = getComputedStyle(document.documentElement)
  return names.map((n) => css.getPropertyValue(n).trim()).join('|')
}

/**
 * Resolved values of CSS custom properties (e.g. --chart-1). Charts draw SVG attributes,
 * which can't reliably use var(), so we read the tokens and re-read when the theme class flips.
 */
export function useThemeColors<const T extends readonly string[]>(names: T): Record<T[number], string> {
  const snapshot = useSyncExternalStore(
    (onChange) => {
      const observer = new MutationObserver(onChange)
      observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
      return () => observer.disconnect()
    },
    () => read(names),
    () => '',
  )
  const values = snapshot.split('|')
  return Object.fromEntries(names.map((n, i) => [n, values[i] ?? ''])) as Record<T[number], string>
}
