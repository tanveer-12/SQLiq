import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:           '#F7F6F3',
        surface:      '#FFFFFF',
        border:       '#E4E4E7',
        text:         '#18181B',
        muted:        '#71717A',
        accent:       '#2563EB',
        'accent-dark':'#1D4ED8',
        success:      '#16A34A',
        warning:      '#CA8A04',
        danger:       '#DC2626',
        'code-bg':    '#F4F4F5',
      },
      fontFamily: {
        mono: ['SF Mono', 'Fira Code', 'Cascadia Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
} satisfies Config