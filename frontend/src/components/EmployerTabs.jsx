// Title and tabs shared by all recruiter pages.
import { NavLink } from 'react-router-dom'

const TABS = [
  ['/employer', 'Company details'],
  ['/employer/post', 'Post a job'],
]

export default function EmployerTabs() {
  return (
    <div className="mb-6">
      <p className="text-sm font-semibold text-sindoor">Recruiter area</p>
      <h1 className="font-display text-4xl">Hire in Kolkata</h1>
      <nav className="mt-4 flex flex-wrap gap-1 border-b border-gray-200" aria-label="Recruiter">
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
