import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  Bell,
  CalendarCheck,
  ClipboardList,
  FileText,
  History,
  LayoutDashboard,
  ListChecks,
  LogOut,
  Menu,
  MessageSquarePlus,
  Settings,
  Sparkles,
  Target,
  User as UserIcon,
  Users,
  X,
} from 'lucide-react'
import { Suspense, useEffect, useRef, useState } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { api } from '../api'
import { useUser, useAuth } from '../auth'
import { fmtDateTime } from '../lib/format'
import { Spinner } from './ui'
import type { Notification, OrgSettings, Role } from '../types'

const NAV: { to: string; label: string; icon: typeof Bell; roles: Role[]; end?: boolean }[] = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, roles: ['employee'], end: true },
  { to: '/', label: 'Team dashboard', icon: LayoutDashboard, roles: ['manager', 'admin'], end: true },
  { to: '/me', label: 'My work', icon: UserIcon, roles: ['manager'] },
  { to: '/update', label: 'Daily update', icon: MessageSquarePlus, roles: ['employee', 'manager'] },
  { to: '/goals', label: 'Weekly goals', icon: Target, roles: ['employee', 'manager', 'admin'], end: true },
  { to: '/goals/assign', label: 'Assign goals', icon: ListChecks, roles: ['manager', 'admin'] },
  { to: '/goals/review', label: 'End-of-week review', icon: CalendarCheck, roles: ['manager', 'admin'] },
  { to: '/history', label: 'Work history', icon: History, roles: ['employee', 'manager', 'admin'] },
  { to: '/reports', label: 'Reports', icon: FileText, roles: ['employee', 'manager', 'admin'] },
  { to: '/admin/people', label: 'People & teams', icon: Users, roles: ['admin'] },
  { to: '/settings', label: 'Settings', icon: Settings, roles: ['employee', 'manager', 'admin'] },
]

function NotificationBell() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data = [] } = useQuery({
    queryKey: ['notifications'],
    queryFn: () => api<Notification[]>('/notifications'),
    refetchInterval: 60_000,
  })
  const unread = data.filter((n) => !n.read_at).length
  const readAll = useMutation({
    mutationFn: () => api('/notifications/read-all', { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  const readOne = useMutation({
    mutationFn: (id: number) => api(`/notifications/${id}/read`, { method: 'POST' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['notifications'] }),
  })
  useEffect(() => {
    const close = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && setOpen(false)
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [])

  return (
    <div className="relative" ref={ref}>
      <button onClick={() => setOpen(!open)} className="relative rounded-lg p-2 text-slate-500 hover:bg-slate-100" aria-label="Notifications">
        <Bell className="h-5 w-5" />
        {unread > 0 && (
          <span className="absolute right-1 top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-bold text-white">
            {unread}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-80 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
            <span className="text-sm font-semibold">Notifications</span>
            {unread > 0 && (
              <button className="text-xs text-brand-600 hover:underline" onClick={() => readAll.mutate()}>
                Mark all read
              </button>
            )}
          </div>
          <div className="max-h-96 overflow-y-auto">
            {data.length === 0 && <p className="px-4 py-6 text-center text-sm text-slate-400">You're all caught up</p>}
            {data.map((n) => (
              <button
                key={n.id}
                onClick={() => {
                  if (!n.read_at) readOne.mutate(n.id)
                  setOpen(false)
                  if (n.link) navigate(n.link)
                }}
                className={clsx('block w-full border-b border-slate-50 px-4 py-2.5 text-left hover:bg-slate-50', !n.read_at && 'bg-brand-50/60')}
              >
                <p className="text-sm font-medium text-slate-800">{n.title}</p>
                {n.body && <p className="line-clamp-2 text-xs text-slate-500">{n.body}</p>}
                <p className="mt-0.5 text-[11px] text-slate-400">{fmtDateTime(n.created_at)}</p>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Layout() {
  const user = useUser()
  const { logout } = useAuth()
  const [mobileOpen, setMobileOpen] = useState(false)
  const location = useLocation()
  useEffect(() => setMobileOpen(false), [location.pathname])
  const { data: settings } = useQuery({ queryKey: ['settings'], queryFn: () => api<OrgSettings>('/settings'), staleTime: 300_000 })
  const nav = NAV.filter((n) => n.roles.includes(user.role))

  const sidebar = (
    <nav className="flex h-full flex-col">
      <Link to="/" className="flex items-center gap-2 px-5 py-5">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
          <ClipboardList className="h-4 w-4" />
        </span>
        <span className="font-semibold text-slate-900">TeamTrack AI</span>
      </Link>
      <div className="flex-1 space-y-0.5 px-3">
        {nav.map((n) => (
          <NavLink
            key={n.to + n.label}
            to={n.to}
            end={n.end}
            className={({ isActive }) =>
              clsx(
                'flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium transition',
                isActive ? 'bg-brand-50 text-brand-700' : 'text-slate-600 hover:bg-slate-100 hover:text-slate-900',
              )
            }
          >
            <n.icon className="h-4 w-4" />
            {n.label}
          </NavLink>
        ))}
      </div>
      <div className="border-t border-slate-100 p-3">
        {settings && (
          <div
            className={clsx(
              'mb-2 flex items-center gap-1.5 rounded-lg px-3 py-2 text-xs',
              settings.ai_mode === 'ai' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-800',
            )}
            title={settings.ai_mode === 'ai' ? 'Claude is parsing updates and drafting reports' : 'Set ANTHROPIC_API_KEY on the server to enable AI'}
          >
            <Sparkles className="h-3.5 w-3.5" />
            {settings.ai_mode === 'ai' ? 'AI assistant on' : 'AI off - basic parser'}
          </div>
        )}
        <div className="flex items-center gap-2 px-2">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-slate-200 text-xs font-semibold text-slate-600">
            {user.full_name
              .split(' ')
              .map((p) => p[0])
              .slice(0, 2)
              .join('')}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-slate-800">{user.full_name}</p>
            <p className="text-xs capitalize text-slate-400">{user.role}</p>
          </div>
          <button onClick={logout} className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="Log out">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </nav>
  )

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 hidden w-60 border-r border-slate-200 bg-white lg:block">{sidebar}</aside>
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 bg-white shadow-xl">
            <button className="absolute right-3 top-5 p-1 text-slate-400" onClick={() => setMobileOpen(false)} aria-label="Close menu">
              <X className="h-5 w-5" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}
      <div className="lg:pl-60">
        <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:px-8">
          <button className="rounded p-1.5 text-slate-500 lg:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <Menu className="h-5 w-5" />
          </button>
          <p className="hidden text-sm text-slate-500 lg:block">{settings?.org_name}</p>
          <div className="flex items-center gap-2">
            {user.role !== 'admin' && (
              <Link
                to="/update"
                className="hidden items-center gap-1.5 rounded-lg bg-brand-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-brand-700 sm:inline-flex"
              >
                <MessageSquarePlus className="h-4 w-4" /> Add today's update
              </Link>
            )}
            <NotificationBell />
          </div>
        </header>
        <main className="mx-auto max-w-7xl px-4 py-6 lg:px-8">
          <Suspense fallback={<Spinner />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}
