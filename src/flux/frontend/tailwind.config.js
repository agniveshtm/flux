/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './index.html',
    './components/**/*.js',
    './composables/**/*.js',
    './main.js',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      spacing: {
        '18': '4.5rem',
      },
      colors: {
        bg: 'var(--color-bg)',
        surface: 'var(--color-surface)',
        'surface-2': 'var(--color-surface-2)',
        fg: 'var(--color-text)',
        muted: 'var(--color-muted)',
        line: 'var(--color-border)',
        accent: 'var(--color-accent)',
        'accent-hover': 'var(--color-accent-hover)',
        'accent-active': 'var(--color-accent-active)',
        'accent-tint': 'var(--color-accent-tint)',
        success: 'var(--color-success)',
        'on-accent': '#FFFFFF',
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
      fontSize: {
        'xs': ['0.75rem', { lineHeight: '1.5' }],
        'sm': ['0.875rem', { lineHeight: '1.5' }],
        'base': ['1rem', { lineHeight: '1.5' }],
        'lg': ['1.125rem', { lineHeight: '1.5' }],
        'xl': ['1.25rem', { lineHeight: '1.4' }],
      },
      borderRadius: {
        'lg': '0.5rem',
      },
      boxShadow: {
        'focus-accent': '0 0 0 2px var(--color-accent)',
      },
      transitionDuration: {
        '150': '150ms',
        '200': '200ms',
      },
    },
  },
  plugins: [],
}