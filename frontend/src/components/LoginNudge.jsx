// A soft, one-time reminder for guests to log in. It appears only after someone has looked
// around a little (3 pages, or 40 seconds), sits in the corner without blocking the page,
// and never comes back once it has been shown.
import { useEffect, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import Icon from '../lib/icons'
import { loginUrl } from '../lib/next'
import { supabase } from '../lib/supabase'

const SEEN_KEY = 'kjs_login_nudge_seen'
const PAGES_BEFORE = 3
const SECONDS_BEFORE = 40
const QUIET_PAGES = ['/login', '/privacy.html']        // never on these pages

function alreadySeen() {
  try { return localStorage.getItem(SEEN_KEY) === '1' } catch { return false }
}

function markSeen() {
  try { localStorage.setItem(SEEN_KEY, '1') } catch { /* private window: it just shows again next visit */ }
}

export default function LoginNudge() {
  const { ready, user } = useAuth()
  const location = useLocation()
  const [pages, setPages] = useState(0)
  const [timeUp, setTimeUp] = useState(false)
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState(alreadySeen)

  useEffect(() => setPages((n) => n + 1), [location.pathname])
  useEffect(() => {
    const timer = setTimeout(() => setTimeUp(true), SECONDS_BEFORE * 1000)
    return () => clearTimeout(timer)
  }, [])

  const quiet = QUIET_PAGES.includes(location.pathname)
  useEffect(() => {
    if (!ready || user || done || open || quiet) return
    if (pages >= PAGES_BEFORE || timeUp) {
      setOpen(true)
      markSeen()                    // shown once; closing or ignoring it is fine
    }
  }, [ready, user, done, open, quiet, pages, timeUp])

  if (!open || user || quiet) return null
  const here = location.pathname + location.search
  const close = () => { setOpen(false); setDone(true) }

  function google() {
    supabase.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin + here } })
  }

  return (
    <aside aria-label="Log in to keep track" className="fixed z-30 bottom-4 inset-x-4 sm:left-auto sm:right-4 sm:w-96">
      <div className="bg-white border border-gray-200 rounded-lg shadow-2xl overflow-hidden">
        <div className="laal-paar" />
        <div className="p-5">
          <div className="flex items-start justify-between gap-3">
            <p className="font-display text-xl leading-snug">Keep track of your job hunt</p>
            <button onClick={close} className="p-1 -m-1 rounded hover:bg-paper" aria-label="Close">
              <Icon name="close" className="w-5 h-5" />
            </button>
          </div>
          <p className="mt-1.5 text-sm text-gray-600">
            Log in free to track every job you apply to, save jobs, and get new Kolkata jobs by email.
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button onClick={google}
                    className="px-4 py-2 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
              Continue with Google
            </button>
            <Link to={loginUrl(here)} onClick={close} className="text-sm text-dusk hover:underline">
              Other ways to log in
            </Link>
            <button onClick={close} className="ml-auto text-sm text-gray-500 hover:text-ink">Not now</button>
          </div>
        </div>
      </div>
    </aside>
  )
}
