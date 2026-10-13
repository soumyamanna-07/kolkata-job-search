// Log in or create an account: "Continue with Google" first, email + password below it.
// ?next=/jobs/123 brings the user back to that page afterwards.
import { useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { safeNext } from '../lib/next'
import { supabase } from '../lib/supabase'

const GOOGLE_NUDGE = 'Please continue with Google \u2014 it takes one click.'

// Supabase's free email service allows only a few sign-up emails per hour. When that limit
// (or the per-IP sign-up limit) is reached we don't show "too many sign-ups" - we point to Google.
function isRateLimit(error) {
  if (!error) return false
  const code = String(error.code || '')
  return error.status === 429 || code.startsWith('over_') || /rate limit|too many/i.test(error.message || '')
}

function GoogleLogo() {
  return (
    <svg aria-hidden="true" viewBox="0 0 48 48" className="w-5 h-5 shrink-0">
      <path fill="#EA4335" d="M24 9.5c3.54 0 6.71 1.22 9.21 3.6l6.85-6.85C35.9 2.38 30.47 0 24 0 14.62 0 6.51 5.38 2.56 13.22l7.98 6.19C12.43 13.72 17.74 9.5 24 9.5z" />
      <path fill="#4285F4" d="M46.98 24.55c0-1.57-.15-3.09-.38-4.55H24v9.02h12.94c-.58 2.96-2.26 5.48-4.78 7.18l7.73 6c4.51-4.18 7.09-10.36 7.09-17.65z" />
      <path fill="#FBBC05" d="M10.53 28.59c-.48-1.45-.76-2.99-.76-4.59s.27-3.14.76-4.59l-7.98-6.19C.92 16.46 0 20.12 0 24c0 3.88.92 7.54 2.56 10.78l7.97-6.19z" />
      <path fill="#34A853" d="M24 48c6.48 0 11.93-2.13 15.89-5.81l-7.73-6c-2.15 1.45-4.92 2.3-8.16 2.3-6.26 0-11.57-4.22-13.47-9.91l-7.98 6.19C6.51 42.62 14.62 48 24 48z" />
    </svg>
  )
}

export default function LoginPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const next = safeNext(params.get('next'))
  const [mode, setMode] = useState('login')            // login | signup
  const [form, setForm] = useState({ email: '', password: '', fullName: '', recruiter: false })
  const [message, setMessage] = useState(null)         // { tone: 'error' | 'ok' | 'google', text }
  const [busy, setBusy] = useState(false)
  const [googleBusy, setGoogleBusy] = useState(false)

  if (user) return <Navigate to={next} replace />

  const update = (key) => (e) =>
    setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function continueWithGoogle() {
    setGoogleBusy(true)
    setMessage(null)
    // Google sends the user back to this site; Supabase then finishes the login by itself
    const { error } = await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: window.location.origin + next },
    })
    if (error) {
      setGoogleBusy(false)
      setMessage({ tone: 'error', text: 'Could not open Google sign-in. Please try again.' })
    }
  }

  function showError(error) {
    if (isRateLimit(error)) setMessage({ tone: 'google', text: GOOGLE_NUDGE })
    else setMessage({ tone: 'error', text: error.message })
  }

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    if (mode === 'login') {
      const { error } = await supabase.auth.signInWithPassword({ email: form.email, password: form.password })
      setBusy(false)
      if (error) showError(error)
      else navigate(next)
      return
    }
    const { data, error } = await supabase.auth.signUp({
      email: form.email,
      password: form.password,
      options: {
        emailRedirectTo: window.location.origin + next,
        // our database reads these when it creates the profile ('admin' can never be chosen here)
        data: { full_name: form.fullName.trim(), account_type: form.recruiter ? 'employer' : 'candidate' },
      },
    })
    setBusy(false)
    if (error) showError(error)
    else if (data.session) navigate(next)
    else setMessage({ tone: 'ok', text: 'Account created. Check your email and click the link to confirm, then log in.' })
  }

  const input = 'w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-dusk'
  const googleHighlighted = message?.tone === 'google'

  return (
    <div className="max-w-sm mx-4 sm:mx-auto my-10 bg-white rounded border border-gray-200 overflow-hidden">
      <div className="laal-paar" />
      <div className="p-6">
      <h1 className="font-display text-2xl">{mode === 'login' ? 'Log in' : 'Create an account'}</h1>
      <p className="text-sm text-gray-600 mt-1">
        {mode === 'login'
          ? 'Save jobs, match your CV and get job alerts.'
          : 'Free. We never share your details.'}
      </p>

      <button type="button" onClick={continueWithGoogle} disabled={googleBusy}
              className={`w-full mt-5 flex items-center justify-center gap-3 py-2.5 rounded border bg-white font-medium text-gray-800 hover:bg-gray-50 disabled:opacity-60 focus:outline-none focus:ring-2 focus:ring-dusk ${googleHighlighted ? 'border-dusk ring-2 ring-dusk' : 'border-gray-300'}`}>
        <GoogleLogo />
        {googleBusy ? 'Opening Google...' : 'Continue with Google'}
      </button>
      {googleHighlighted && (
        <p role="status" className="text-sm mt-2 p-2 rounded bg-blue-50 text-dusk text-center">{message.text}</p>
      )}

      <div className="flex items-center gap-3 my-5 text-xs text-gray-500">
        <span className="flex-1 h-px bg-gray-200" />
        or use email
        <span className="flex-1 h-px bg-gray-200" />
      </div>

      <form onSubmit={submit} className="space-y-3">
        {mode === 'signup' && (
          <input required maxLength={100} placeholder="Full name" value={form.fullName}
                 onChange={update('fullName')} className={input} />
        )}
        <input required type="email" placeholder="Email" autoComplete="email" value={form.email}
               onChange={update('email')} className={input} />
        <input required type="password" minLength={8} placeholder="Password (8+ characters)"
               autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
               value={form.password} onChange={update('password')} className={input} />
        {mode === 'signup' && (
          <label className="flex items-start gap-2 text-sm text-gray-700">
            <input type="checkbox" checked={form.recruiter} onChange={update('recruiter')} className="mt-1" />
            I am a recruiter (company HR or recruitment agency) and want to post jobs
          </label>
        )}
        {message && !googleHighlighted && (
          <p className={`text-sm p-2 rounded ${message.tone === 'error' ? 'bg-red-50 text-sindoor' : 'bg-green-50 text-green-700'}`}>
            {message.text}
          </p>
        )}
        <button disabled={busy}
                className="w-full py-2 rounded bg-dusk text-white font-medium hover:bg-dusk-deep disabled:opacity-50">
          {busy ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Create account'}
        </button>
      </form>

      {mode === 'signup' && (
        <p className="text-xs text-gray-500 mt-3">
          Recruiters: please sign up with email and tick the box above, so we can set up your employer account.
        </p>
      )}

      <p className="text-sm text-gray-600 mt-4 text-center">
        {mode === 'login' ? 'New here? ' : 'Already have an account? '}
        <button onClick={() => { setMode(mode === 'login' ? 'signup' : 'login'); setMessage(null) }}
                className="text-dusk hover:underline">
          {mode === 'login' ? 'Create an account' : 'Log in'}
        </button>
      </p>
      </div>
    </div>
  )
}
