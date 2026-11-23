// Apply the saved theme before first paint (avoids a light flash in dark mode).
// A separate file (not inline) so the Content-Security-Policy can forbid inline scripts.
try {
  var t = JSON.parse(localStorage.getItem('documind-preferences') || '{}').state?.theme || 'system'
  if (t === 'dark' || (t === 'system' && matchMedia('(prefers-color-scheme: dark)').matches))
    document.documentElement.classList.add('dark')
} catch {
  // storage unavailable (private mode): fall back to the light theme
}
