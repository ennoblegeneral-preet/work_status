import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { api, getToken, setToken } from './api'
import type { User } from './types'

interface AuthState {
  user: User | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  refresh: () => Promise<void>
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(true)
  const qc = useQueryClient()

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      setUser(await api<User>('/auth/me'))
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const onLogout = () => setUser(null)
    window.addEventListener('teamtrack:logout', onLogout)
    return () => window.removeEventListener('teamtrack:logout', onLogout)
  }, [refresh])

  const login = async (email: string, password: string) => {
    const res = await api<{ access_token: string; user: User }>('/auth/login', { method: 'POST', json: { email, password } })
    setToken(res.access_token)
    qc.clear()
    setUser(res.user)
  }

  const logout = () => {
    api('/auth/logout', { method: 'POST' }).catch(() => undefined)
    setToken(null)
    qc.clear()
    setUser(null)
  }

  return <AuthContext.Provider value={{ user, loading, login, logout, refresh }}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth outside AuthProvider')
  return ctx
}

export function useUser(): User {
  const { user } = useAuth()
  if (!user) throw new Error('No user')
  return user
}
