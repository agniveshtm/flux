/**
 * Flux Theme Composable
 * Manages light/dark theme with OS detection and localStorage persistence
 */
window.Flux = window.Flux || {};
window.Flux.useTheme = function() {
  const STORAGE_KEY = 'flux-theme';

  function getInitialTheme() {
    if (typeof window === 'undefined') return 'light';
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  const theme = Vue.ref(getInitialTheme());

  function applyTheme(t) {
    if (t === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }

  applyTheme(theme.value);

  // Once the user explicitly picks a theme, stop following OS changes
  let hasUserPreference = localStorage.getItem(STORAGE_KEY) !== null;

  function toggleTheme() {
    theme.value = theme.value === 'dark' ? 'light' : 'dark';
    localStorage.setItem(STORAGE_KEY, theme.value);
    hasUserPreference = true;
    applyTheme(theme.value);
  }

  function setTheme(t) {
    if (t === 'light' || t === 'dark') {
      theme.value = t;
      localStorage.setItem(STORAGE_KEY, t);
      hasUserPreference = true;
      applyTheme(t);
    }
  }

  // Listen for OS theme changes (only if user hasn't set a preference)
  const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
  const handleChange = (e) => {
    if (!hasUserPreference) {
      theme.value = e.matches ? 'dark' : 'light';
      applyTheme(theme.value);
    }
  };
  mediaQuery.addEventListener('change', handleChange);

  // Provide cleanup
  const cleanup = () => {
    mediaQuery.removeEventListener('change', handleChange);
  };

  return {
    theme,
    toggleTheme,
    setTheme,
    cleanup,
  };
};