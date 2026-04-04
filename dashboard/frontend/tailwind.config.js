/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        navy: {
          50: '#eef5ff',
          100: '#d9e8ff',
          200: '#bcd8ff',
          300: '#8ec0ff',
          400: '#599dff',
          500: '#3377ff',
          600: '#1b55f5',
          700: '#1440e1',
          800: '#0b1a57',
          900: '#0b0f2f',
        },
        accent: {
          DEFAULT: '#14b8a6',
          light: '#5eead4',
          dark: '#0d9488',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
