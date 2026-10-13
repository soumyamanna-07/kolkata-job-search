// Which jobs the logged-in user has saved. Use: const { isSaved, toggleSave } = useSaved()
import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from './api'
import { useAuth } from './auth'
import { useToast } from './toast'

const SavedContext = createContext(null)

export function SavedProvider({ children }) {
  const { user } = useAuth()
  const [ids, setIds] = useState(new Set())
  const navigate = useNavigate()
  const toast = useToast()

  useEffect(() => {
    if (!user) {
      setIds(new Set())
      return
    }
    api('/api/me/saved-jobs').then((jobs) => setIds(new Set(jobs.map((j) => j.id)))).catch(() => {})
  }, [user])

  const toggleSave = useCallback(async (jobId) => {
    if (!user) {
      toast('Log in to save jobs')
      navigate('/login')
      return
    }
    const saved = ids.has(jobId)
    const next = new Set(ids)
    if (saved) next.delete(jobId)
    else next.add(jobId)
    setIds(next)                                     // update at once, undo if the server says no
    try {
      await api(`/api/me/saved-jobs/${jobId}`, { method: saved ? 'DELETE' : 'PUT' })
      toast(saved ? 'Removed from saved jobs' : 'Saved. Find it under Saved.')
    } catch (e) {
      setIds(ids)
      toast(e.message)
    }
  }, [ids, user, navigate, toast])

  const value = { isSaved: (id) => ids.has(id), toggleSave, count: ids.size }
  return <SavedContext.Provider value={value}>{children}</SavedContext.Provider>
}

export function useSaved() {
  return useContext(SavedContext)
}
