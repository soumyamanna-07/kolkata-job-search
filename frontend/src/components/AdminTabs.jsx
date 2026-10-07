// Title and tabs shared by all admin pages.
import { NavLink } from 'react-router-dom'

const TABS = [
  ['/admin', 'Dashboard'],
  ['/admin/review', 'Review recruiters and jobs'],
  ['/admin/reports', 'Reports and shared links'],
  ['/admin/companies', 'Companies'],
]

export default function AdminTabs() {
  return (
    <div className="mb-6">
      <p className="text-sm font-semibold text-sindoor">Admin panel</p>
      <h1 className="font-display text-4xl">Run Kolkata Live Jobs</h1>
      <nav className="mt-4 flex flex-wrap gap-1 border-b border-gray-200" aria-label="Admin">
        {TABS.map(([to, label]) => (
          <NavLink key={to} to={to} end
                   className={({ isActive }) => `px-4 py-2 -mb-px border-b-2 text-sm whitespace-nowrap ${
                     isActive ? 'border-sindoor font-semibold' : 'border-transparent text-gray-600 hover:text-dusk'}`}>
            {label}
          </NavLink>
        ))}
      </nav>
    </div>
  )
}
