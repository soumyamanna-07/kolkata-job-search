// Admin: find accounts and block or unblock them. A blocked user cannot use any logged-in feature.
// The CV itself is never shown here, only whether one is saved. Admins cannot be blocked from the panel.
import { useCallback, useEffect, useState } from 'react'
import AdminTabs from '../components/AdminTabs'
import Modal from '../components/Modal'
import { api } from '../lib/api'
import { postedText } from '../lib/format'
import { useToast } from '../lib/toast'

const ROLES = { candidate: 'Job seeker', employer: 'Recruiter', admin: 'Admin' }

export default function AdminUsersPage() {
  const toast = useToast()
  const [users, setUsers] = useState(null)
  const [filters, setFilters] = useState({ q: '', role: '', blocked: '' })
  const [error, setError] = useState('')
  const [target, setTarget] = useState(null)        // user being blocked / unblocked
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)

  const load = useCallback((f) => {
    api('/api/admin/users', { params: { q: f.q.trim(), role: f.role, blocked: f.blocked, limit: 100 } })
      .then(setUsers).catch((err) => setError(err.message))
  }, [])
  useEffect(() => { load({ q: '', role: '', blocked: '' }) }, [load])

  const update = (key) => (e) => {
    const next = { ...filters, [key]: e.target.value }
    setFilters(next)
    if (key !== 'q') load(next)
  }

  async function confirm(e) {
    e.preventDefault()
    setBusy(true)
    try {
      await api(`/api/admin/users/${target.id}/block`, { method: 'POST', body: { blocked: !target.is_blocked, reason: reason.trim() } })
      toast(target.is_blocked ? 'Account unblocked.' : 'Account blocked.')
      setTarget(null)
      setReason('')
      load(filters)
    } catch (err) {
      toast(err.message)
    }
    setBusy(false)
  }

  const select = 'rounded border border-gray-300 px-3 py-2 text-sm bg-white'
  return (
    <div className="max-w-5xl mx-auto px-4 py-8">
      <AdminTabs />
      <form onSubmit={(e) => { e.preventDefault(); load(filters) }} className="flex flex-wrap gap-2 mb-4">
        <label className="sr-only" htmlFor="user-search">Search users</label>
        <input id="user-search" value={filters.q} onChange={update('q')} placeholder="Email or name" className={select} />
        <button className="px-4 py-2 rounded border border-gray-300 text-sm">Search</button>
        <label className="sr-only" htmlFor="user-role">Account type</label>
        <select id="user-role" value={filters.role} onChange={update('role')} className={select}>
          <option value="">All account types</option>
          {Object.entries(ROLES).map(([v, l]) => <option key={v} value={v}>{l}s</option>)}
        </select>
        <label className="sr-only" htmlFor="user-blocked">Blocked</label>
        <select id="user-blocked" value={filters.blocked} onChange={update('blocked')} className={select}>
          <option value="">Blocked or not</option>
          <option value="true">Blocked only</option>
          <option value="false">Not blocked</option>
        </select>
      </form>

      {error && <p className="p-4 rounded bg-red-50 text-sindoor text-sm">{error}</p>}
      {!users && !error && <p className="text-gray-500">Loading</p>}
      {users && (users.length === 0 ? <p className="text-sm text-gray-600">No accounts found.</p> : (
        <div className="bg-white border border-gray-200 rounded overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-gray-600 border-b border-gray-200">
                <th className="px-4 py-2 font-medium">Account</th>
                <th className="px-4 py-2 font-medium">Type</th>
                <th className="px-4 py-2 font-medium">CV saved</th>
                <th className="px-4 py-2 font-medium">Joined</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-gray-100">
                  <td className="px-4 py-2">
                    <p className="font-medium break-all">{u.email || '-'}</p>
                    {u.full_name && <p className="text-xs text-gray-500">{u.full_name}</p>}
                  </td>
                  <td className="px-4 py-2">{ROLES[u.role] || u.role}</td>
                  <td className="px-4 py-2">{u.has_cv ? 'Yes' : 'No'}</td>
                  <td className="px-4 py-2 text-gray-600">{postedText(u.created_at)}</td>
                  <td className="px-4 py-2">
                    {u.is_blocked ? <span className="px-2 py-0.5 rounded-sm bg-red-50 text-sindoor font-medium">Blocked</span>
                      : <span className="text-green-700">Active</span>}
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap">
                    {u.role !== 'admin' && (
                      <button onClick={() => setTarget(u)}
                              className={`px-2 py-1 rounded ${u.is_blocked ? 'text-dusk hover:bg-paper' : 'text-sindoor hover:bg-red-50'}`}>
                        {u.is_blocked ? 'Unblock' : 'Block'}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {target && (
        <Modal title={`${target.is_blocked ? 'Unblock' : 'Block'} ${target.email || 'this account'}?`} onClose={() => setTarget(null)}>
          <form onSubmit={confirm}>
            <p className="text-sm text-gray-600">
              {target.is_blocked ? 'They can use their account again.'
                : 'They can no longer save jobs, upload a CV, share links, report jobs or post jobs.'}
            </p>
            <label className="block mt-3 text-sm">Reason (kept in the audit log)
              <textarea required minLength={3} maxLength={500} rows={2} value={reason} onChange={(e) => setReason(e.target.value)}
                        className="mt-1 w-full rounded border border-gray-300 px-3 py-2" />
            </label>
            <div className="mt-4 flex gap-2">
              <button disabled={busy || reason.trim().length < 3}
                      className={`px-4 py-2 rounded text-white font-semibold disabled:opacity-50 ${target.is_blocked ? 'bg-dusk' : 'bg-sindoor'}`}>
                {busy ? 'Saving' : target.is_blocked ? 'Unblock' : 'Block'}
              </button>
              <button type="button" onClick={() => setTarget(null)} className="px-4 py-2 rounded border border-gray-300">Cancel</button>
            </div>
          </form>
        </Modal>
      )}
    </div>
  )
}
