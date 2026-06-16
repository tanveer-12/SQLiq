import { Link } from 'react-router-dom'

interface HeaderProps {
  tagline?: string
}

export default function Header({ tagline }: HeaderProps) {
  return (
    <header className="bg-surface border-b border-border sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 py-3.5 flex items-center gap-4">
        <Link
          to="/"
          className="text-[18px] font-bold tracking-tight text-text no-underline"
        >
          SQLiq
        </Link>
        {tagline && (
          <span className="text-muted text-[13px] flex-1">{tagline}</span>
        )}
        <a
          href={`/dashboard?key=${encodeURIComponent(import.meta.env.VITE_API_KEY ?? '1HwzNCXxMscQTvPmZwvC3wVd2uA_J2BbFn_DYIbdWyw')}`}
          target="_blank"
          rel="noreferrer"
          className="text-[13px] text-accent no-underline px-2.5 py-1 border border-border rounded-md hover:bg-code-bg"
        >
          Agent Dashboard ↗
        </a>
      </div>
    </header>
  )
}