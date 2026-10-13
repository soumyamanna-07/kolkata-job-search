// Recruiter pages: need a login AND a recruiter (employer) account.
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import RequireLogin from './RequireLogin'

function NotRecruiter() {
  return (
    <div className="max-w-md mx-4 sm:mx-auto my-16 bg-white border border-gray-200 rounded overflow-hidden text-center">
      <div className="laal-paar" />
      <div className="p-8">
        <p className="font-display text-2xl">This area is for recruiters</p>
        <p className="mt-2 text-sm text-gray-600">
          Your account is a job seeker account. To post jobs, log out, create a new account and tick
          "I am a recruiter" when you sign up.
        </p>
        <Link to="/" className="inline-block mt-5 px-6 py-2.5 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
          Back to jobs
        </Link>
      </div>
    </div>
  )
}

export default function RequireEmployer({ children }) {
  const { profile } = useAuth()
  return (
    <RequireLogin what="the recruiter area">
      {!profile ? <p className="max-w-6xl mx-auto px-4 py-8 text-gray-500">Loading your account</p>
        : profile.role === 'employer' ? children : <NotRecruiter />}
    </RequireLogin>
  )
}
