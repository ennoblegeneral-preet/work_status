import { ClipboardList } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth'
import { Button, ErrorText, Field } from '../components/ui'

const DEMO = [
  ['Admin', 'admin@teamtrack.local'],
  ['Manager', 'priya@teamtrack.local'],
  ['Employee', 'arjun@teamtrack.local'],
]

export default function Login() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  if (user) return <Navigate to="/" replace />

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(email, password)
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-gradient-to-br from-brand-50 via-white to-slate-50 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <span className="mb-3 flex h-12 w-12 items-center justify-center rounded-xl bg-brand-600 text-white shadow-lg">
            <ClipboardList className="h-6 w-6" />
          </span>
          <h1 className="text-2xl font-semibold text-slate-900">TeamTrack AI</h1>
          <p className="mt-1 text-sm text-slate-500">Weekly goals, daily updates, automatic reports</p>
        </div>
        <form onSubmit={submit} className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <Field label="Email">
            <input className="input" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </Field>
          <Field label="Password">
            <input
              className="input"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </Field>
          <ErrorText error={error} />
          <Button type="submit" className="w-full" loading={busy}>
            Sign in
          </Button>
        </form>
        {import.meta.env.DEV && (
          <div className="mt-4 rounded-xl border border-dashed border-slate-300 bg-white/60 p-3 text-xs text-slate-500">
            <p className="mb-1 font-medium text-slate-600">Demo accounts (password Password123!)</p>
            <div className="flex flex-wrap gap-2">
              {DEMO.map(([role, mail]) => (
                <button
                  key={mail}
                  type="button"
                  className="rounded bg-slate-100 px-2 py-1 hover:bg-slate-200"
                  onClick={() => {
                    setEmail(mail)
                    setPassword('Password123!')
                  }}
                >
                  {role}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
