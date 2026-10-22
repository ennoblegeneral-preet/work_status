import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { CheckCircle2, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useUser } from '../auth'
import { Alert, Button, Card, ErrorText, Field, PageHeader } from '../components/ui'
import { addDays, label, mondayOf, todayIso, weekLabel } from '../lib/format'
import type { Goal, Page, Priority, TargetType, Team, User } from '../types'

interface Form {
  title: string
  description: string
  project: string
  expected_outcome: string
  success_criteria: string
  priority: Priority
  deadline: string
  target_type: TargetType
  target_value: string
  unit: string
  dependencies: string
  tasks: string[]
}

const blank = (): Form => ({
  title: '',
  description: '',
  project: '',
  expected_outcome: '',
  success_criteria: '',
  priority: 'medium',
  deadline: '',
  target_type: 'tasks',
  target_value: '',
  unit: '',
  dependencies: '',
  tasks: [''],
})

export default function AssignGoals() {
  const user = useUser()
  const qc = useQueryClient()
  const [params] = useSearchParams()
  const [week, setWeek] = useState(mondayOf(params.get('week') ?? todayIso()))
  const [owners, setOwners] = useState<number[]>([])
  const [f, setF] = useState<Form>(blank())
  const [created, setCreated] = useState<Goal[] | null>(null)

  const { data: people } = useQuery({ queryKey: ['users', 'visible'], queryFn: () => api<Page<User>>('/users?page_size=200&active=true') })
  const { data: teams = [] } = useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/teams') })
  const assignable = (people?.items ?? []).filter((p) => p.role !== 'admin' && (user.role === 'admin' || p.id !== user.id))

  const save = useMutation({
    mutationFn: () =>
      api<Goal[]>('/goals/bulk', {
        method: 'POST',
        json: {
          goals: owners.map((owner_id) => ({
            owner_id,
            week_start: week,
            title: f.title,
            description: f.description || null,
            project: f.project || null,
            expected_outcome: f.expected_outcome || null,
            success_criteria: f.success_criteria || null,
            priority: f.priority,
            deadline: f.deadline || null,
            start_date: week,
            target_type: f.target_type,
            target_value: f.target_type === 'number' ? Number(f.target_value) : null,
            unit: f.target_type === 'number' ? f.unit || null : null,
            dependencies: f.dependencies || null,
            tasks: f.target_type === 'tasks' ? f.tasks.filter((t) => t.trim()).map((title) => ({ title: title.trim() })) : [],
          })),
        },
      }),
    onSuccess: (goals) => {
      setCreated(goals)
      setF(blank())
      setOwners([])
      qc.invalidateQueries({ queryKey: ['goals'] })
      qc.invalidateQueries({ queryKey: ['overview'] })
    },
  })

  const bind = (k: keyof Form) => ({
    value: f[k] as string,
    onChange: (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value }),
  })
  const toggle = (id: number) => setOwners(owners.includes(id) ? owners.filter((o) => o !== id) : [...owners, id])
  const valid = f.title.trim() && owners.length > 0 && (f.target_type !== 'number' || Number(f.target_value) > 0)

  return (
    <>
      <PageHeader
        title="Assign weekly goals"
        subtitle="Pick one or more people - each gets their own copy of the goal and its tasks."
        actions={
          <select className="input w-auto" value={week} onChange={(e) => setWeek(e.target.value)} aria-label="Week">
            {[-7, 0, 7, 14].map((d) => {
              const w = addDays(mondayOf(todayIso()), d)
              return <option key={w} value={w}>{d === 0 ? 'This week' : d === 7 ? 'Next week' : d < 0 ? 'Last week' : 'In 2 weeks'} ({weekLabel(w)})</option>
            })}
          </select>
        }
      />
      {created && (
        <Alert tone="success" className="mb-4">
          <CheckCircle2 className="mr-1 inline h-4 w-4" />
          Created {created.length} goal{created.length !== 1 && 's'}: {created.map((g) => <Link key={g.id} to={`/goals/${g.id}`} className="mr-2 underline">{g.code} {g.owner.full_name}</Link>)}
        </Alert>
      )}
      <div className="grid gap-5 lg:grid-cols-3">
        <Card title={`Assign to (${owners.length})`}>
          <div className="max-h-[32rem] space-y-4 overflow-y-auto p-4">
            {people && assignable.length === 0 && (
              <Alert tone="info">
                {user.role === 'admin' ? (
                  <>
                    There is nobody to assign goals to yet. Add employees in{' '}
                    <Link to="/admin/people" className="font-medium underline">People &amp; teams</Link>.
                  </>
                ) : (
                  <>
                    You don't manage a team with members yet, so there is nobody you can assign goals to. Ask an admin to
                    open <b>People &amp; teams</b>, create a team with you as manager, and add your team members.
                  </>
                )}
              </Alert>
            )}
            {teams.map((t) => {
              const members = assignable.filter((p) => t.members.some((m) => m.id === p.id))
              if (!members.length) return null
              const all = members.every((m) => owners.includes(m.id))
              return (
                <div key={t.id}>
                  <div className="mb-1 flex items-center justify-between">
                    <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{t.name}</p>
                    <button
                      className="text-xs text-brand-600 hover:underline"
                      onClick={() => setOwners(all ? owners.filter((o) => !members.some((m) => m.id === o)) : [...new Set([...owners, ...members.map((m) => m.id)])])}
                    >
                      {all ? 'Clear' : 'Select all'}
                    </button>
                  </div>
                  {members.map((p) => (
                    <label key={p.id} className={clsx('flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-sm hover:bg-slate-50', owners.includes(p.id) && 'bg-brand-50')}>
                      <input type="checkbox" checked={owners.includes(p.id)} onChange={() => toggle(p.id)} className="accent-brand-600" />
                      <span className="flex-1">{p.full_name}</span>
                      <span className="text-xs text-slate-400">{p.job_title}</span>
                    </label>
                  ))}
                </div>
              )
            })}
            {assignable.filter((p) => !teams.some((t) => t.members.some((m) => m.id === p.id))).map((p) => (
              <label key={p.id} className="flex items-center gap-2 px-2 py-1.5 text-sm">
                <input type="checkbox" checked={owners.includes(p.id)} onChange={() => toggle(p.id)} className="accent-brand-600" />
                {p.full_name} <span className="text-xs text-slate-400">(no team)</span>
              </label>
            ))}
          </div>
        </Card>

        <Card className="lg:col-span-2" title="Goal">
          <div className="grid gap-3 p-4 sm:grid-cols-2">
            <div className="sm:col-span-2"><Field label="Goal title *"><input className="input" {...bind('title')} placeholder="e.g. Ship donor CSV export" /></Field></div>
            <div className="sm:col-span-2"><Field label="Description"><textarea className="input" {...bind('description')} /></Field></div>
            <Field label="Project / application"><input className="input" {...bind('project')} placeholder="e.g. Donor IQ" /></Field>
            <Field label="Priority">
              <select className="input" {...bind('priority')}>{['low', 'medium', 'high', 'critical'].map((p) => <option key={p} value={p}>{label(p)}</option>)}</select>
            </Field>
            <Field label="Expected outcome"><textarea className="input" {...bind('expected_outcome')} placeholder="What should exist at the end of the week?" /></Field>
            <Field label="Success criteria"><textarea className="input" {...bind('success_criteria')} placeholder="How will we know it's done?" /></Field>
            <Field label="Deadline" hint="Defaults to the end of the week">
              <input type="date" className="input" min={week} max={addDays(week, 6)} {...bind('deadline')} />
            </Field>
            <Field label="Dependencies"><input className="input" {...bind('dependencies')} placeholder="e.g. Needs API keys from client" /></Field>
            <div className="sm:col-span-2">
              <Field label="How is progress measured?">
                <div className="grid gap-2 sm:grid-cols-3">
                  {([
                    ['tasks', 'Tasks / milestones', 'Progress = completed tasks'],
                    ['number', 'Numeric target', 'e.g. 5 meetings booked'],
                    ['boolean', 'Done / not done', 'Single deliverable'],
                  ] as const).map(([v, t, d]) => (
                    <button
                      type="button"
                      key={v}
                      onClick={() => setF({ ...f, target_type: v })}
                      className={clsx('rounded-lg border p-2.5 text-left', f.target_type === v ? 'border-brand-500 bg-brand-50' : 'border-slate-200 hover:bg-slate-50')}
                    >
                      <p className="text-sm font-medium text-slate-800">{t}</p>
                      <p className="text-xs text-slate-500">{d}</p>
                    </button>
                  ))}
                </div>
              </Field>
            </div>
            {f.target_type === 'number' && (
              <>
                <Field label="Target value *"><input type="number" min={1} className="input" {...bind('target_value')} /></Field>
                <Field label="Unit"><input className="input" {...bind('unit')} placeholder="meetings, proposals..." /></Field>
              </>
            )}
            {f.target_type === 'tasks' && (
              <div className="sm:col-span-2">
                <p className="label">Tasks / milestones</p>
                <div className="space-y-2">
                  {f.tasks.map((t, i) => (
                    <div key={i} className="flex gap-2">
                      <input
                        className="input"
                        value={t}
                        placeholder={`Task ${i + 1}`}
                        onChange={(e) => setF({ ...f, tasks: f.tasks.map((x, j) => (j === i ? e.target.value : x)) })}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            setF({ ...f, tasks: [...f.tasks, ''] })
                          }
                        }}
                      />
                      <button className="rounded p-2 text-slate-400 hover:text-rose-600" onClick={() => setF({ ...f, tasks: f.tasks.filter((_, j) => j !== i) })} aria-label="Remove task">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                  <Button variant="secondary" size="sm" onClick={() => setF({ ...f, tasks: [...f.tasks, ''] })}><Plus className="h-4 w-4" /> Add task</Button>
                </div>
              </div>
            )}
          </div>
          <div className="border-t border-slate-100 p-4">
            <ErrorText error={save.error} />
            <div className="mt-2 flex items-center justify-end gap-3">
              <span className="text-sm text-slate-500">Week of {weekLabel(week)}</span>
              <Button onClick={() => save.mutate()} disabled={!valid} loading={save.isPending}>
                Assign to {owners.length || '...'} {owners.length === 1 ? 'person' : 'people'}
              </Button>
            </div>
          </div>
        </Card>
      </div>
    </>
  )
}
