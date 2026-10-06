// Log in or create an account (Supabase email + password).
import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import { supabase } from '../lib/supabase'

export default function LoginPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [mode, setMode] = useState('login')            // login | signup
  const [form, setForm] = useState({ email: '', password: '', fullName: '', recruiter: false })
  const [message, setMessage] = useState(null)         // { tone: 'error' | 'ok', text }
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const update = (key) => (e) =>
    setForm({ ...form, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    if (mode === 'login') {
      const { error } = await supabase.auth.signInWithPassword({ email: form.email, password: form.password })
      setBusy(false)
      if (error) setMessage({ tone: 'error', text: error.message })
      else navigate('/')
      return
    }
    const { data, error } = await supabase.auth.signUp({
      email: form.email,
      password: form.password,
      options: {
        emailRedirectTo: window.location.origin,
        // our database reads these when it creates the profile ('admin' can never be chosen here)
        data: { full_name: form.fullName.trim(), account_type: form.recruiter ? 'employer' : 'candidate' },
      },
    })
    setBusy(false)
    if (error) setMessage({ tone: 'error', text: error.message })
    else if (data.session) navigate('/')
    else setMessage({ tone: 'ok', text: 'Account created. Check your email and click the link to confirm, then log in.' })
  }

  const input = 'w-full rounded border border-gray-300 px-3 py-2 focus:outline-none focus:ring-2 focus:ring-dusk'

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

      <form onSubmit={submit} className="space-y-3 mt-5">
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
        {message && (
          <p className={`text-sm p-2 rounded ${message.tone === 'error' ? 'bg-red-50 text-sindoor' : 'bg-green-50 text-green-700'}`}>
            {message.text}
          </p>
        )}
        <button disabled={busy}
                className="w-full py-2 rounded bg-dusk text-white font-medium hover:bg-dusk-deep disabled:opacity-50">
          {busy ? 'Please wait...' : mode === 'login' ? 'Log in' : 'Create account'}
        </button>
      </form>

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
