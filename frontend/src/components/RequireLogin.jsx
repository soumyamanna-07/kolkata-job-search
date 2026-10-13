// Pages that need an account: show a short message with a Log in button instead of the page.
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'

export default function RequireLogin({ what, children }) {
  const { ready, user } = useAuth()
  if (!ready) return null
  if (user) return children
  return (
    <div className="max-w-md mx-4 sm:mx-auto my-16 bg-white border border-gray-200 rounded overflow-hidden text-center">
      <div className="laal-paar" />
      <div className="p-8">
        <p className="font-display text-2xl">Log in to see {what}</p>
        <p className="mt-2 text-sm text-gray-600">It's free, and takes a minute.</p>
        <Link to="/login" className="inline-block mt-5 px-6 py-2.5 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
          Log in or create an account
        </Link>
      </div>
    </div>
  )
}
