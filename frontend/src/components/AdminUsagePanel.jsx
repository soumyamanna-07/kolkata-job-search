// Admin dashboard: how many people use the site (accounts, active users, guest visitors, applications).
// Only totals - never who did what.
import { useEffect, useState } from 'react'
import { api } from '../lib/api'

const n = (v) => (v ?? 0).toLocaleString('en-IN')
const STAGE_LABELS = { applied: 'applied', interview: 'interview', offer: 'offer', rejected: 'rejected', no_reply: 'no reply' }

function Tile({ value, label, detail }) {
  return (
    <div className="px-4 py-3">
      <p className="font-display text-3xl tabular-nums">{n(value)}</p>
      <p className="text-sm text-gray-700">{label}</p>
      <p className="mt-0.5 text-xs text-gray-500">{detail}</p>
    </div>
  )
}

export default function AdminUsagePanel() {
  const [usage, setUsage] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => { api('/api/admin/usage').then(setUsage).catch((e) => setError(e.message)) }, [])

  if (error) return <p className="p-3 rounded bg-red-50 text-sindoor text-sm">Usage numbers: {error}</p>
  if (!usage) return null
  const stages = Object.entries(usage.applications_by_stage).filter(([, c]) => c > 0)

  return (
    <section>
      <h2 className="font-display text-2xl mb-3">People using the site</h2>
      <div className="grid grid-cols-2 md:grid-cols-4 bg-white border border-gray-200 rounded divide-x divide-y md:divide-y-0 divide-gray-200">
        <Tile value={usage.accounts_total} label="accounts"
              detail={`${n(usage.new_accounts.today)} new today, ${n(usage.new_accounts.days_7)} in 7 days`} />
        <Tile value={usage.active_users.days_7} label="active users, last 7 days"
              detail={`${n(usage.active_users.today)} today, ${n(usage.active_users.days_30)} in 30 days`} />
        <Tile value={usage.visitors.days_7} label="guest visitors, last 7 days"
              detail={`${n(usage.visitors.today)} today, ${n(usage.visitors.days_30)} in 30 days`} />
        <Tile value={usage.applications_total} label="applications tracked"
              detail={`${n(usage.applications_new_7_days)} new in 7 days`} />
      </div>
      <p className="mt-2 text-xs text-gray-500">
        {stages.length > 0 && <>Applications by stage: {stages.map(([s, c]) => `${n(c)} ${STAGE_LABELS[s]}`).join(', ')}. </>}
        Active users = logged-in people who viewed, saved, applied to or tracked a job. Guest visitors are counted by
        an anonymous browser id. Days are in India time.
      </p>
    </section>
  )
}
