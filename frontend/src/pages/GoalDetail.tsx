import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CornerDownRight, History, Plus, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { useUser } from '../auth'
import { progressHint } from '../components/goals'
import { Alert, Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, Progress, Spinner } from '../components/ui'
import { fmtDate, fmtDateTime, fmtDay, label, weekLabel } from '../lib/format'
import type { Goal, GoalStatus, HistoryEntry, Task, TaskStatus, WorkLogItem } from '../types'

interface GoalHistory {
  goal_status: HistoryEntry[]
  task_status: HistoryEntry[]
  work_items: WorkLogItem[]
}

function TaskDetail({ task, onClose }: { task: Task; onClose: () => void }) {
  const { data } = useQuery({
    queryKey: ['task', task.id],
    queryFn: () => api<{ history: HistoryEntry[]; work_items: WorkLogItem[] }>(`/tasks/${task.id}`),
  })
  return (
    <Modal open onClose={onClose} title={`${task.code} ${task.title}`} wide>
      {!data ? (
        <Spinner />
      ) : (
        <div className="grid gap-5 sm:grid-cols-2">
          <div>
            <p className="label">Daily progress</p>
            {data.work_items.length === 0 ? (
              <p className="text-sm text-slate-400">No work logged yet.</p>
            ) : (
              <ol className="space-y-2 border-l-2 border-slate-100 pl-3">
                {data.work_items.map((i) => (
                  <li key={i.id} className="text-sm">
                    <p className="text-xs font-medium text-slate-500">{fmtDay(i.report_date)}</p>
                    <p className="text-slate-700">{i.task_title}</p>
                    <div className="mt-0.5 flex gap-1.5">
                      <Badge value={i.status} />
                      <Badge value={i.kind} />
                      {i.hours !== null && <Badge>{i.hours} h</Badge>}
                    </div>
                  </li>
                ))}
              </ol>
            )}
          </div>
          <div>
            <p className="label">Status history</p>
            {data.history.length === 0 ? (
              <p className="text-sm text-slate-400">No changes yet.</p>
            ) : (
              <ol className="space-y-1.5 text-sm">
                {data.history.map((h) => (
                  <li key={h.id}>
                    <span className="text-slate-500">{fmtDateTime(h.created_at)}</span> · {label(h.from_status)} → <b>{label(h.to_status)}</b>
                    {h.reason && <p className="text-xs text-slate-400">{h.reason}</p>}
                  </li>
                ))}
              </ol>
            )}
          </div>
        </div>
      )}
    </Modal>
  )
}

function EditGoal({ goal, onClose }: { goal: Goal; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({
    title: goal.title,
    description: goal.description ?? '',
    project: goal.project ?? '',
    expected_outcome: goal.expected_outcome ?? '',
    success_criteria: goal.success_criteria ?? '',
    priority: goal.priority,
    deadline: goal.deadline ?? '',
    dependencies: goal.dependencies ?? '',
    target_value: goal.target_value ?? '',
    unit: goal.unit ?? '',
  })
  const save = useMutation({
    mutationFn: () =>
      api(`/goals/${goal.id}`, {
        method: 'PATCH',
        json: {
          ...f,
          deadline: f.deadline || null,
          target_value: goal.target_type === 'number' && f.target_value !== '' ? Number(f.target_value) : undefined,
          unit: goal.target_type === 'number' ? f.unit : undefined,
        },
      }),
    onSuccess: () => {
      qc.invalidateQueries()
      onClose()
    },
  })
  const bind = (k: keyof typeof f) => ({ value: f[k] as string, onChange: (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value }) })
  return (
    <Modal open onClose={onClose} title="Edit goal" wide>
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2"><Field label="Title"><input className="input" {...bind('title')} /></Field></div>
        <div className="sm:col-span-2"><Field label="Description"><textarea className="input" {...bind('description')} /></Field></div>
        <Field label="Project"><input className="input" {...bind('project')} /></Field>
        <Field label="Priority">
          <select className="input" {...bind('priority')}>
            {['low', 'medium', 'high', 'critical'].map((p) => <option key={p} value={p}>{label(p)}</option>)}
          </select>
        </Field>
        <Field label="Expected outcome"><textarea className="input" {...bind('expected_outcome')} /></Field>
        <Field label="Success criteria"><textarea className="input" {...bind('success_criteria')} /></Field>
        <Field label="Deadline" hint="The original deadline is kept in history"><input type="date" className="input" {...bind('deadline')} /></Field>
        <Field label="Dependencies"><input className="input" {...bind('dependencies')} /></Field>
        {goal.target_type === 'number' && (
          <>
            <Field label="Target value"><input type="number" className="input" {...bind('target_value')} /></Field>
            <Field label="Unit"><input className="input" {...bind('unit')} /></Field>
          </>
        )}
      </div>
      <ErrorText error={save.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
      </div>
    </Modal>
  )
}

export default function GoalDetail() {
  const { id } = useParams()
  const user = useUser()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data: goal, isLoading, error } = useQuery({ queryKey: ['goal', id], queryFn: () => api<Goal>(`/goals/${id}`) })
  const { data: history } = useQuery({ queryKey: ['goal-history', id], queryFn: () => api<GoalHistory>(`/goals/${id}/history`) })
  const [newTask, setNewTask] = useState('')
  const [openTask, setOpenTask] = useState<Task | null>(null)
  const [editing, setEditing] = useState(false)
  const [statusModal, setStatusModal] = useState<GoalStatus | null>(null)
  const [reason, setReason] = useState('')
  const [blockers, setBlockers] = useState<string | null>(null)
  const [value, setValue] = useState<string | null>(null)

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ['goal', id] })
    qc.invalidateQueries({ queryKey: ['goal-history', id] })
    qc.invalidateQueries({ queryKey: ['goals'] })
  }
  const patchGoal = useMutation({
    mutationFn: (body: Record<string, unknown>) => api(`/goals/${id}`, { method: 'PATCH', json: body }),
    onSuccess: () => {
      refresh()
      setStatusModal(null)
      setReason('')
      setBlockers(null)
      setValue(null)
    },
  })
  const addTask = useMutation({
    mutationFn: () => api('/tasks', { method: 'POST', json: { goal_id: Number(id), title: newTask } }),
    onSuccess: () => {
      setNewTask('')
      refresh()
    },
  })
  const patchTask = useMutation({
    mutationFn: ({ task, status }: { task: Task; status: TaskStatus }) => api(`/tasks/${task.id}`, { method: 'PATCH', json: { status } }),
    onSuccess: refresh,
  })
  const deleteTask = useMutation({ mutationFn: (t: Task) => api(`/tasks/${t.id}`, { method: 'DELETE' }), onSuccess: refresh })
  const deleteGoal = useMutation({ mutationFn: () => api(`/goals/${id}`, { method: 'DELETE' }), onSuccess: () => navigate('/goals') })

  if (isLoading) return <Spinner />
  if (error || !goal) return <ErrorText error={error ?? 'Not found'} />

  const isOwner = goal.owner_id === user.id
  const isManager = user.role === 'admin' || (user.role === 'manager' && !isOwner)
  const canEditTasks = isOwner || isManager
  const closed = ['completed', 'cancelled', 'deferred'].includes(goal.status)
  const ownerStatuses: GoalStatus[] = ['in_progress', 'blocked', 'completed']
  const statuses: GoalStatus[] = isManager ? ['not_started', 'in_progress', 'blocked', 'completed', 'deferred', 'cancelled'] : ownerStatuses

  return (
    <>
      <Link to="/goals" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Goals
      </Link>
      <PageHeader
        title={goal.title}
        subtitle={
          <>
            <span className="font-mono">{goal.code}</span> · {goal.owner.full_name} · {goal.project ?? 'No project'} · Week of {weekLabel(goal.week_start)}
          </>
        }
        actions={
          <>
            {(isOwner || isManager) && (
              <select
                className="input w-auto"
                value=""
                onChange={(e) => e.target.value && setStatusModal(e.target.value as GoalStatus)}
                aria-label="Change status"
              >
                <option value="">Change status...</option>
                {statuses.filter((s) => s !== goal.status).map((s) => <option key={s} value={s}>{label(s)}</option>)}
              </select>
            )}
            {isManager && <Button variant="secondary" onClick={() => setEditing(true)}>Edit</Button>}
            {isManager && (
              <Button variant="ghost" onClick={() => confirm('Delete this goal?') && deleteGoal.mutate()} title="Delete goal">
                <Trash2 className="h-4 w-4" />
              </Button>
            )}
          </>
        }
      />
      <ErrorText error={deleteGoal.error} />
      {goal.carried_from_goal_id && (
        <Alert tone="info" className="mb-4">
          <CornerDownRight className="mr-1 inline h-4 w-4" />
          Carried forward from <Link className="underline" to={`/goals/${goal.carried_from_goal_id}`}>G-{goal.carried_from_goal_id}</Link>
          {goal.carry_forward_reason && `: ${goal.carry_forward_reason}`}
          {goal.original_deadline && ` · original deadline ${fmtDate(goal.original_deadline)}`}
        </Alert>
      )}

      <div className="grid gap-5 lg:grid-cols-3">
        <div className="space-y-5 lg:col-span-2">
          <Card>
            <div className="grid gap-4 p-4 sm:grid-cols-3">
              <div>
                <p className="label">Status</p>
                <div className="flex gap-1.5"><Badge value={goal.status} />{!closed && goal.health !== 'not_started' && <Badge value={goal.health} />}</div>
              </div>
              <div>
                <p className="label">Deadline</p>
                <p className="text-sm">
                  {fmtDate(goal.deadline ?? goal.week_end, { weekday: 'short', day: 'numeric', month: 'short' })}
                  {goal.original_deadline && goal.original_deadline !== goal.deadline && (
                    <span className="ml-1 text-xs text-slate-400 line-through">{fmtDate(goal.original_deadline)}</span>
                  )}
                </p>
              </div>
              <div>
                <p className="label">Priority</p>
                <Badge value={goal.priority} />
              </div>
              <div className="sm:col-span-3">
                <p className="label">Progress · {progressHint(goal)}</p>
                <Progress value={goal.progress} />
                <p className="mt-1 text-xs text-slate-400">
                  {goal.target_type === 'tasks' && 'Calculated from completed tasks (weighted). Logging work alone does not count as completion.'}
                  {goal.target_type === 'number' && 'Calculated from the current value against the target.'}
                  {goal.target_type === 'boolean' && 'Done when the goal is marked completed.'}
                </p>
                {goal.target_type === 'number' && canEditTasks && !closed && (
                  <div className="mt-2 flex items-center gap-2">
                    <input
                      type="number"
                      min={0}
                      className="input w-32 py-1.5"
                      value={value ?? goal.current_value ?? 0}
                      onChange={(e) => setValue(e.target.value)}
                      aria-label="Current value"
                    />
                    <span className="text-sm text-slate-500">/ {goal.target_value} {goal.unit}</span>
                    {value !== null && <Button size="sm" onClick={() => patchGoal.mutate({ current_value: Number(value) })}>Update</Button>}
                  </div>
                )}
              </div>
              {goal.description && <div className="sm:col-span-3"><p className="label">Description</p><p className="whitespace-pre-wrap text-sm text-slate-700">{goal.description}</p></div>}
              <div><p className="label">Expected outcome</p><p className="text-sm text-slate-700">{goal.expected_outcome ?? '-'}</p></div>
              <div><p className="label">Success criteria</p><p className="text-sm text-slate-700">{goal.success_criteria ?? '-'}</p></div>
              <div><p className="label">Dependencies</p><p className="text-sm text-slate-700">{goal.dependencies ?? '-'}</p></div>
              <div className="sm:col-span-3">
                <p className="label">Blockers</p>
                {blockers === null ? (
                  <p className="text-sm text-slate-700">
                    {goal.blockers ?? <span className="text-slate-400">None</span>}
                    {canEditTasks && <button className="ml-2 text-xs text-brand-600 hover:underline" onClick={() => setBlockers(goal.blockers ?? '')}>edit</button>}
                  </p>
                ) : (
                  <div className="flex gap-2">
                    <input className="input" value={blockers} onChange={(e) => setBlockers(e.target.value)} autoFocus />
                    <Button size="sm" onClick={() => patchGoal.mutate({ blockers: blockers || null })}>Save</Button>
                  </div>
                )}
              </div>
            </div>
          </Card>

          <Card title={`Tasks & milestones (${goal.tasks.length})`}>
            {goal.tasks.length === 0 ? (
              <Empty title="No tasks yet">Tasks are also created automatically from daily updates.</Empty>
            ) : (
              <ul className="divide-y divide-slate-100">
                {goal.tasks.map((t) => (
                  <li key={t.id} className="flex flex-wrap items-center gap-2 px-4 py-2.5">
                    <button className="min-w-0 flex-1 text-left" onClick={() => setOpenTask(t)}>
                      <span className="mr-2 font-mono text-xs text-slate-400">{t.code}</span>
                      <span className={t.status === 'completed' ? 'text-slate-500 line-through' : 'text-slate-800'}>{t.title}</span>
                      {t.weight > 1 && <span className="ml-2 text-xs text-slate-400">weight {t.weight}</span>}
                    </button>
                    {canEditTasks ? (
                      <select
                        className="input w-36 py-1"
                        value={t.status}
                        onChange={(e) => patchTask.mutate({ task: t, status: e.target.value as TaskStatus })}
                        aria-label="Task status"
                      >
                        {['not_started', 'in_progress', 'blocked', 'completed', 'cancelled'].map((s) => <option key={s} value={s}>{label(s)}</option>)}
                      </select>
                    ) : (
                      <Badge value={t.status} />
                    )}
                    {canEditTasks && (
                      <button className="rounded p-1 text-slate-300 hover:text-rose-600" onClick={() => deleteTask.mutate(t)} title="Delete task">
                        <Trash2 className="h-4 w-4" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            <ErrorText error={patchTask.error ?? deleteTask.error} />
            {canEditTasks && !closed && (
              <form
                className="flex gap-2 border-t border-slate-100 p-3"
                onSubmit={(e) => {
                  e.preventDefault()
                  if (newTask.trim()) addTask.mutate()
                }}
              >
                <input className="input" placeholder="Add a task or milestone" value={newTask} onChange={(e) => setNewTask(e.target.value)} />
                <Button type="submit" variant="secondary" loading={addTask.isPending}><Plus className="h-4 w-4" /> Add</Button>
              </form>
            )}
          </Card>
        </div>

        <Card title={<span className="flex items-center gap-1.5"><History className="h-4 w-4" /> Progress history</span>}>
          {!history ? (
            <Spinner />
          ) : history.work_items.length === 0 && history.goal_status.length === 0 ? (
            <Empty title="No activity yet" />
          ) : (
            <ol className="max-h-[36rem] space-y-3 overflow-y-auto p-4">
              {[
                ...history.work_items.map((i) => ({ at: i.report_date, key: `i${i.id}`, node: (
                  <>
                    <p className="text-slate-700">{i.task_title}</p>
                    <div className="mt-0.5 flex gap-1.5"><Badge value={i.status} /><Badge value={i.kind} />{i.hours !== null && <Badge>{i.hours} h</Badge>}</div>
                  </>
                ) })),
                ...history.goal_status.map((h) => ({ at: h.created_at.slice(0, 10), key: `g${h.id}`, node: (
                  <p className="text-slate-600">Goal → <b>{label(h.to_status)}</b>{h.reason && <span className="text-slate-400"> · {h.reason}</span>}</p>
                ) })),
              ]
                .sort((a, b) => (a.at < b.at ? 1 : -1))
                .map((e) => (
                  <li key={e.key} className="border-l-2 border-slate-100 pl-3 text-sm">
                    <p className="text-xs font-medium text-slate-400">{fmtDay(e.at)}</p>
                    {e.node}
                  </li>
                ))}
            </ol>
          )}
        </Card>
      </div>

      {openTask && <TaskDetail task={openTask} onClose={() => setOpenTask(null)} />}
      {editing && <EditGoal goal={goal} onClose={() => setEditing(false)} />}
      <Modal open={statusModal !== null} onClose={() => setStatusModal(null)} title={`Mark goal as ${label(statusModal)}`}>
        <Field label="Reason" hint={statusModal === 'completed' ? 'Required if some tasks are still open' : 'Recorded in the goal history'}>
          <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <ErrorText error={patchGoal.error} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setStatusModal(null)}>Cancel</Button>
          <Button onClick={() => patchGoal.mutate({ status: statusModal, reason: reason || null })} loading={patchGoal.isPending}>Confirm</Button>
        </div>
      </Modal>
    </>
  )
}
