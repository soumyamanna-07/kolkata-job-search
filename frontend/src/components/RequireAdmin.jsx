// Admin pages: need a login AND the admin role (given only in the database, never in the app).
import { Link } from 'react-router-dom'
import { useAuth } from '../lib/auth'
import RequireLogin from './RequireLogin'

export default function RequireAdmin({ children }) {
  const { profile } = useAuth()
  let content = children
  if (!profile) content = <p className="max-w-6xl mx-auto px-4 py-8 text-gray-500">Loading your account</p>
  else if (profile.role !== 'admin') {
    content = (
      <div className="max-w-md mx-4 sm:mx-auto my-16 bg-white border border-gray-200 rounded p-8 text-center">
        <p className="font-display text-2xl">Admins only</p>
        <p className="mt-2 text-sm text-gray-600">This page is for the people who run the site.</p>
        <Link to="/" className="inline-block mt-5 px-6 py-2.5 rounded bg-taxi text-ink font-semibold hover:bg-taxi-deep">
          Back to jobs
        </Link>
      </div>
    )
  }
  return <RequireLogin what="the admin panel">{content}</RequireLogin>
}
