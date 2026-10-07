// All pages of the web app.
import { Link, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import RequireAdmin from './components/RequireAdmin'
import RequireEmployer from './components/RequireEmployer'
import RequireLogin from './components/RequireLogin'
import AdminDashboardPage from './pages/AdminDashboardPage'
import AdminReviewPage from './pages/AdminReviewPage'
import AlertsPage from './pages/AlertsPage'
import AskPage from './pages/AskPage'
import EmployerJobsPage from './pages/EmployerJobsPage'
import EmployerPostPage from './pages/EmployerPostPage'
import EmployerProfilePage from './pages/EmployerProfilePage'
import InsightsPage from './pages/InsightsPage'
import JobPage from './pages/JobPage'
import LoginPage from './pages/LoginPage'
import MatchPage from './pages/MatchPage'
import SavedPage from './pages/SavedPage'
import SearchPage from './pages/SearchPage'
import ShareJobPage from './pages/ShareJobPage'

function NotFound() {
  return (
    <div className="text-center py-16">
      <p className="text-gray-700">Page not found.</p>
      <Link to="/" className="inline-block mt-3 text-dusk underline">See all current jobs</Link>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<SearchPage />} />
        <Route path="/jobs/:id" element={<JobPage />} />
        <Route path="/match" element={<MatchPage />} />
        <Route path="/ask" element={<AskPage />} />
        <Route path="/insights" element={<InsightsPage />} />
        <Route path="/saved" element={<RequireLogin what="your saved jobs"><SavedPage /></RequireLogin>} />
        <Route path="/alerts" element={<RequireLogin what="your job alerts"><AlertsPage /></RequireLogin>} />
        <Route path="/share-job" element={<RequireLogin what="the share-a-job form"><ShareJobPage /></RequireLogin>} />
        <Route path="/employer" element={<RequireEmployer><EmployerProfilePage /></RequireEmployer>} />
        <Route path="/employer/post" element={<RequireEmployer><EmployerPostPage /></RequireEmployer>} />
        <Route path="/employer/jobs" element={<RequireEmployer><EmployerJobsPage /></RequireEmployer>} />
        <Route path="/employer/jobs/:id/edit" element={<RequireEmployer><EmployerPostPage /></RequireEmployer>} />
        <Route path="/admin" element={<RequireAdmin><AdminDashboardPage /></RequireAdmin>} />
        <Route path="/admin/review" element={<RequireAdmin><AdminReviewPage /></RequireAdmin>} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
