import { useQuery } from '@tanstack/react-query'
import clsx from 'clsx'
import { CalendarDays, Columns3, List, Plus, Target } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api'
import { useUser } from '../auth'
import { GoalRow, progressHint } from '../components/goals'
import { Badge, Button, Card, Empty, PageHeader, Progress, Spinner, Tabs } from '../components/ui'
import { addDays, fmtDate, label, mondayOf, todayIso, WEEKDAYS } from '../lib/format'
import type { Goal, GoalStatus, Page, User } from '../types'
import { WeekPicker } from '../components/WeekPicker'

const COLUMNS: GoalStatus[] = ['not_started', 'in_progress', 'blocked', 'completed']

function MiniGoal({ g, showOwner }: { g: Goal; showOwner: boolean }) {
  return (
    <Link to={`/goals/${g.id}`} className="block rounded-lg border border-slate-200 bg-white p-3 shadow-sm transition hover:border-brand-300">
      <p className="text-sm font-medium text-slate-800">{g.title}</p>
      <p className="mt-0.5 text-xs text-slate-500">
        {showOwner && `${g.owner.full_name} · `}
        {progressHint(g)}
      </p>
      <Progress value={g.progress} className="mt-2" />
      {g.health !== 'not_started' && !['completed', 'deferred', 'cancelled'].includes(g.status) && <Badge value={g.health} className="mt-2" />}
    </Link>
  )
}

export default function Goals() {
  const user = useUser()
  const [week, setWeek] = useState(mondayOf(todayIso()))
  const [view, setView] = useState<'list' | 'board' | 'calendar'>('list')
  const [owner, setOwner] = useState('')
  const isManager = user.role !== 'employee'
  const { data, isLoading } = useQuery({
    queryKey: ['goals', week, owner],
    queryFn: () => api<Page<Goal>>(`/goals${qs({ week_start: week, owner_id: owner, page_size: 300 })}`),
  })
  const { data: people } = useQuery({
    queryKey: ['users', 'visible'],
    queryFn: () => api<Page<User>>('/users?page_size=200&active=true'),
    enabled: isManager,
  })
  const goals = data?.items ?? []
  const showOwner = isManager

  return (
    <>
      <PageHeader
        title={isManager ? 'Weekly goals' : 'My weekly goals'}
        actions={
          <>
            {isManager && (
              <select className="input w-auto" value={owner} onChange={(e) => setOwner(e.target.value)} aria-label="Employee">
                <option value="">Everyone</option>
                {people?.items.filter((p) => p.role !== 'admin').map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
              </select>
            )}
            <WeekPicker value={week} onChange={setWeek} />
            {isManager && (
              <Link to={`/goals/assign?week=${week}`}>
                <Button><Plus className="h-4 w-4" /> Assign goals</Button>
              </Link>
            )}
          </>
        }
      />
      <div className="mb-4">
        <Tabs
          value={view}
          onChange={setView}
          tabs={[
            { value: 'list', label: <><List className="h-4 w-4" /> List</> },
            { value: 'board', label: <><Columns3 className="h-4 w-4" /> Board</> },
            { value: 'calendar', label: <><CalendarDays className="h-4 w-4" /> Calendar</> },
          ]}
        />
      </div>
      {isLoading ? (
        <Spinner />
      ) : goals.length === 0 ? (
        <Card>
          <Empty icon={<Target className="h-8 w-8" />} title="No goals for this week">
            {isManager ? 'Use "Assign goals" to set weekly goals for your team.' : 'Your manager has not assigned goals for this week yet.'}
          </Empty>
        </Card>
      ) : view === 'list' ? (
        <Card>
          <ul className="divide-y divide-slate-100">{goals.map((g) => <GoalRow key={g.id} goal={g} showOwner={showOwner} />)}</ul>
        </Card>
      ) : view === 'board' ? (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {COLUMNS.map((col) => {
            const items = goals.filter((g) => g.status === col)
            return (
              <div key={col} className="rounded-xl bg-slate-100/70 p-3">
                <p className="mb-2 flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-slate-500">
                  {label(col)} <span>{items.length}</span>
                </p>
                <div className="space-y-2">{items.map((g) => <MiniGoal key={g.id} g={g} showOwner={showOwner} />)}</div>
              </div>
            )
          })}
          {goals.some((g) => g.status === 'deferred' || g.status === 'cancelled') && (
            <p className="text-xs text-slate-400 md:col-span-2 xl:col-span-4">Deferred and cancelled goals are shown in the list view.</p>
          )}
        </div>
      ) : (
        <div className="grid gap-3 md:grid-cols-7">
          {WEEKDAYS.map((d, i) => {
            const day = addDays(week, i)
            const due = goals.filter((g) => (g.deadline ?? g.week_end) === day)
            return (
              <div key={d} className={clsx('min-h-40 rounded-xl border p-2', day === todayIso() ? 'border-brand-300 bg-brand-50/50' : 'border-slate-200 bg-white')}>
                <p className="mb-2 text-xs font-semibold text-slate-500">
                  {d} <span className="font-normal">{fmtDate(day)}</span>
                </p>
                <div className="space-y-2">{due.map((g) => <MiniGoal key={g.id} g={g} showOwner={showOwner} />)}</div>
              </div>
            )
          })}
        </div>
      )}
    </>
  )
}
