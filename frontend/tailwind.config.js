/** @type {import('tailwindcss').Config} */
// REQ-009: class-based dark mode — the StatusHeader toggle controls `.dark` on
// the root <html> (set by useTheme + the FOUC inline script in index.html),
// NOT OS-level prefers-color-scheme. Default stays light (matches REQ-005/006/008).
//
// REQ-010: ColdVault brand alignment. The `purple` scale (anchored at #1E4970)
// and `accent` scale (anchored at #5BD3F4 / #AEEDF5) mirror
// `coldvault/src/ui/react/tailwind.config.js` verbatim so the two products
// share a visible brand identity. Lato is the primary sans font for the same
// reason — coldvault.ai uses Lato. niobe's reference doc explicitly says USE
// the palette tokens, don't reach for inline `bg-[#hex]` literals.
//
// `surface`/`card`/`border` GlassHood-specific tokens stay for the
// REQ-005 light theme — dark-mode equivalents applied per-component via
// the `dark:` prefix (e.g. `bg-card dark:bg-purple-800`).
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: {
        sans: ['Lato', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
      },
      colors: {
        surface: '#f8fafc',
        card: '#ffffff',
        border: '#e2e8f0',

        // ColdVault `purple` scale (dark blue with blue tint). Mirror exactly
        // from coldvault/src/ui/react/tailwind.config.js. `purple-500`
        // (#1E4970) is the brand dark-blue anchor; `purple-300` (#5BD3F4) is
        // the medium-blue accent used across both products; `purple-100`
        // (#AEEDF5) is the light-blue subtle text tone.
        purple: {
          950: '#020810',
          900: '#040e17',
          800: '#081621',
          700: '#0d1f30',
          600: '#13293e',
          500: '#1E4970',
          400: '#2a6496',
          300: '#5BD3F4',
          200: '#8DE4F8',
          100: '#AEEDF5',
          50:  '#edf8fc',
        },

        // ColdVault `accent` scale — blue accents from darkest to lightest.
        // accent-500 (#5BD3F4) is the primary brand blue.
        accent: {
          700: '#0d3654',
          600: '#155580',
          500: '#5BD3F4',
          400: '#7DDDF7',
          300: '#AEEDF5',
          200: '#D0F5FA',
          100: '#EDF9FC',
        },
      },
    },
  },
  plugins: [],
}
