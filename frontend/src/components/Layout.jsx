// Header (with menu on phones) + page area + footer, shared by every page.
import { useEffect, useState } from 'react'
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import Icon from '../lib/icons'
import { useSaved } from '../lib/saved'
import { useTheme } from '../lib/theme'

const LINKS = [
  ['/', 'Jobs', 'briefcase'],
  ['/match', 'Match my CV', 'file'],
  ['/ask', 'Ask AI', 'spark'],
  ['/insights', 'Insights', 'chart'],
]

function navClass({ isActive }) {
  return `inline-flex items-center gap-2 px-3 py-2 rounded text-sm ${
    isActive ? 'text-white bg-white/12' : 'text-steel hover:text-white hover:bg-white/5'}`
}

export default function Layout() {
  const { user, profile, signOut } = useAuth()
  const { count } = useSaved()
  const [menu, setMenu] = useState(false)
  const { theme, toggle } = useTheme()
  const location = useLocation()

  useEffect(() => setMenu(false), [location.pathname])           // close the phone menu after navigating

  const userLinks = user ? [['/saved', `Saved${count ? ` (${count})` : ''}`, 'bookmark'],
    ['/alerts', 'Alerts', 'bell'], ['/share-job', 'Share a job', 'link']] : []

  return (
    <div className="min-h-screen flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:p-2 focus:bg-white">Skip to content</a>
      <header className="bg-dusk text-white sticky top-0 z-30 border-b border-white/10">
        <div className="max-w-6xl mx-auto px-4 h-16 flex items-center gap-4">
          <Link to="/" className="flex items-center gap-2 whitespace-nowrap">
            <svg viewBox="0 0 32 32" className="w-8 h-8" aria-hidden="true">
              <rect width="32" height="32" rx="6" fill="#f4c430" />
              <path d="M5 22h22M9 22V9M23 22V9M9 9l7 7l7-7M9 14l14 0" stroke="#17324a" strokeWidth="2.2" fill="none"
                    strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <span className="font-display text-xl">Kolkata Live Jobs</span>
          </Link>

          <nav className="hidden lg:flex gap-1 ml-4" aria-label="Main">
            {[...LINKS, ...userLinks].map(([to, label, icon]) => (
              <NavLink key={to} to={to} end={to === '/'} className={navClass}>
                <Icon name={icon} className="w-4 h-4" />{label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-2 text-sm">
            <button onClick={toggle} className="p-2 rounded text-steel hover:text-taxi hover:bg-white/10"
                    aria-label={theme === 'dark' ? 'Switch to light display' : 'Switch to dark display'}
                    title={theme === 'dark' ? 'Light display' : 'Dark display'}>
              <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
            </button>
            {user ? (
              <>
                <span className="hidden md:inline-flex items-center gap-1.5 text-steel max-w-44 truncate">
                  <Icon name="user" className="w-4 h-4" />{profile?.full_name || user.email}
                </span>
                <button onClick={signOut} className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded border border-white/30 hover:bg-white/10">
                  <Icon name="logout" className="w-4 h-4" /> Log out
                </button>
              </>
            ) : (
              <Link to="/login" className="px-4 py-2 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
                Log in
              </Link>
            )}
            <button className="lg:hidden p-2 rounded hover:bg-white/10" onClick={() => setMenu(!menu)}
                    aria-expanded={menu} aria-label="Menu">
              <Icon name={menu ? 'close' : 'menu'} />
            </button>
          </div>
        </div>

        {menu && (
          <nav className="lg:hidden border-t border-white/10 px-4 py-3 grid gap-1" aria-label="Main">
            {[...LINKS, ...userLinks].map(([to, label, icon]) => (
              <NavLink key={to} to={to} end={to === '/'} className={navClass}>
                <Icon name={icon} className="w-4 h-4" />{label}
              </NavLink>
            ))}
            {user && (
              <button onClick={signOut} className="text-left inline-flex items-center gap-2 px-3 py-2 text-steel">
                <Icon name="logout" className="w-4 h-4" /> Log out
              </button>
            )}
          </nav>
        )}
      </header>

      <main id="main" className="flex-1">
        <Outlet />
      </main>

      <footer className="bg-dusk-deep text-steel">
        <div className="laal-paar" />
        <div className="max-w-6xl mx-auto px-4 py-8 grid gap-6 sm:grid-cols-3 text-sm">
          <div>
            <p className="font-display text-lg text-white">Kolkata Live Jobs</p>
            <p className="mt-1">Current jobs across Kolkata, Salt Lake, New Town and Howrah, collected every day.</p>
          </div>
          <div className="grid gap-1">
            <Link to="/match" className="hover:text-white">Match my CV</Link>
            <Link to="/ask" className="hover:text-white">Ask AI about jobs</Link>
            <Link to="/insights" className="hover:text-white">Job market insights</Link>
            <Link to="/share-job" className="hover:text-white">Share a job (students and TPOs)</Link>
          </div>
          <p>
            A final-year project at Techno Main Salt Lake. Only jobs from the last 30 days are shown.
            Always apply on the employer's or job site's own page, and never pay to get a job.
          </p>
        </div>
      </footer>
    </div>
  )
}
