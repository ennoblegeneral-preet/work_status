import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { AlertTriangle, ArrowRight, ChevronDown, Clock, History as HistoryIcon, Pencil } from 'lucide-react'
import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, qs } from '../api'
import { useUser } from '../auth'
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, Spinner } from '../components/ui'
import { addDays, fmtDateTime, fmtDay, todayIso } from '../lib/format'
import type { AuditEntry, DailyLog, Page, User, WorkLogItem } from '../types'

function EditItem({ item, onClose }: { item: WorkLogItem; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState({ task_title: item.task_title, status: item.status, kind: item.kind, hours: item.hours?.toString() ?? '' })
  const save = useMutation({
    mutationFn: () =>
      api(`/work-log-items/${item.id}`, {
        method: 'PATCH',
        json: { task_title: f.task_title, status: f.status, kind: f.kind, hours: f.hours === '' ? null : Number(f.hours) },
      }),
    onSuccess: () => {
      qc.invalidateQueries()
      onClose()
    },
  })
  return (
    <Modal open onClose={onClose} title="Edit work item">
      <div className="space-y-3">
        <Field label="Title"><input className="input" value={f.task_title} onChange={(e) => setF({ ...f, task_title: e.target.value })} /></Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Status">
            <select className="input" value={f.status} onChange={(e) => setF({ ...f, status: e.target.value as WorkLogItem['status'] })}>
              <option value="in_progress">In progress</option>
              <option value="completed">Completed</option>
              <option value="blocked">Blocked</option>
            </select>
          </Field>
          <Field label="Type">
            <select className="input" value={f.kind} onChange={(e) => setF({ ...f, kind: e.target.value as WorkLogItem['kind'] })}>
              <option value="activity">Activity</option>
              <option value="outcome">Outcome</option>
            </select>
          </Field>
          <Field label="Hours"><input type="number" min={0} max={24} step={0.25} className="input" value={f.hours} onChange={(e) => setF({ ...f, hours: e.target.value })} /></Field>
        </div>
        <p className="text-xs text-slate-400">Changes are recorded in the edit history.</p>
      </div>
      <ErrorText error={save.error} />
      <div className="mt-4 flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>Cancel</Button>
        <Button onClick={() => save.mutate()} loading={save.isPending}>Save</Button>
      </div>
    </Modal>
  )
}

function AuditModal({ logId, onClose }: { logId: number; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ['log-history', logId], queryFn: () => api<AuditEntry[]>(`/work-logs/${logId}/history`) })
  return (
    <Modal open onClose={onClose} title="Edit history" wide>
      {!data ? (
        <Spinner />
      ) : (
        <ol className="space-y-3 text-sm">
          {data.map((a) => (
            <li key={a.id} className="border-l-2 border-slate-100 pl-3">
              <p className="text-xs text-slate-400">{fmtDateTime(a.created_at)}</p>
              <p className="font-medium text-slate-700">{a.action.replace(/_/g, ' ')}</p>
              {a.action === 'edit_work_log_item' && a.before && a.after && (
                <ul className="mt-1 text-xs text-slate-600">
                  {Object.keys(a.after)
                    .filter((k) => JSON.stringify(a.before![k]) !== JSON.stringify(a.after![k]))
                    .map((k) => (
                      <li key={k}>
                        {k}: <span className="text-slate-400 line-through">{String(a.before![k] ?? '-')}</span> <ArrowRight className="inline h-3 w-3" /> {String(a.after![k] ?? '-')}
                      </li>
                    ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      )}
    </Modal>
  )
}

function LogCard({ log, defaultOpen, canEdit, showName }: { log: DailyLog; defaultOpen: boolean; canEdit: boolean; showName: boolean }) {
  const [open, setOpen] = useState(defaultOpen)
  const [editing, setEditing] = useState<WorkLogItem | null>(null)
  const [audit, setAudit] = useState(false)
  return (
    <Card className={clsx(defaultOpen && 'ring-2 ring-brand-200')}>
      <button className="flex w-full items-center gap-3 px-4 py-3 text-left" onClick={() => setOpen(!open)}>
        <div className="flex-1">
          <p className="font-medium text-slate-800">
            {fmtDay(log.report_date)}
            {showName && <span className="ml-2 font-normal text-slate-500">· {log.employee.full_name}</span>}
          </p>
          <p className="text-xs text-slate-500">
            {log.items.length} item{log.items.length !== 1 && 's'} · {log.total_hours !== null ? `${log.total_hours} h` : 'hours not reported'} ·{' '}
            {log.input_method === 'chat' ? 'AI chat' : 'pasted'} · {log.parse_mode === 'ai' ? 'AI parsed' : 'basic parser'}
          </p>
        </div>
        {log.blockers.length > 0 && <Badge value="blocked">{log.blockers.length} blocker{log.blockers.length > 1 && 's'}</Badge>}
        <ChevronDown className={clsx('h-4 w-4 text-slate-400 transition', open && 'rotate-180')} />
      </button>
      {open && (
        <div className="grid gap-4 border-t border-slate-100 p-4 lg:grid-cols-2">
          <div>
            <p className="label">Original update (as submitted)</p>
            <p className="whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-sm text-slate-700">{log.raw_text}</p>
            {log.chat_messages.length > 0 && (
              <div className="mt-2 space-y-1">
                {log.chat_messages.map((m, i) => (
                  <p key={i} className={clsx('rounded px-2 py-1 text-xs', m.role === 'assistant' ? 'bg-brand-50 text-brand-700' : 'bg-slate-50 text-slate-600')}>
                    <b>{m.role === 'assistant' ? 'Assistant' : 'Employee'}:</b> {m.content}
                  </p>
                ))}
              </div>
            )}
            <button className="mt-2 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-700" onClick={() => setAudit(true)}>
              <HistoryIcon className="h-3.5 w-3.5" /> Edit history
            </button>
          </div>
          <div className="space-y-3">
            <div>
              <p className="label">Extracted work items</p>
              <ul className="space-y-1.5">
                {log.items.map((i) => (
                  <li key={i.id} className="flex items-start gap-2 rounded-lg border border-slate-100 px-3 py-2 text-sm">
                    <div className="flex-1">
                      <p className="text-slate-800">{i.task_title}</p>
                      <div className="mt-1 flex flex-wrap gap-1.5 text-xs">
                        <Badge value={i.status} />
                        <Badge value={i.kind} />
                        {i.goal_id ? <Link to={`/goals/${i.goal_id}`} className="text-brand-600 hover:underline">G-{i.goal_id}</Link> : <Badge>additional work</Badge>}
                        {i.hours !== null && <span className="inline-flex items-center gap-0.5 text-slate-500"><Clock className="h-3 w-3" />{i.hours} h</span>}
                      </div>
                    </div>
                    {canEdit && (
                      <button className="rounded p-1 text-slate-400 hover:bg-slate-100" onClick={() => setEditing(i)} title="Edit">
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
            {log.blockers.length > 0 && (
              <div>
                <p className="label">Blockers</p>
                {log.blockers.map((b) => <p key={b} className="flex gap-1.5 text-sm text-rose-700"><AlertTriangle className="mt-0.5 h-3.5 w-3.5" />{b}</p>)}
              </div>
            )}
            {log.next_steps.length > 0 && (
              <div>
                <p className="label">Next steps</p>
                <ul className="list-disc pl-5 text-sm text-slate-700">{log.next_steps.map((n) => <li key={n}>{n}</li>)}</ul>
              </div>
            )}
          </div>
        </div>
      )}
      {editing && <EditItem item={editing} onClose={() => setEditing(null)} />}
      {audit && <AuditModal logId={log.id} onClose={() => setAudit(false)} />}
    </Card>
  )
}

export default function History() {
  const user = useUser()
  const [params, setParams] = useSearchParams()
  const employee = params.get('employee') ?? ''
  const highlight = Number(params.get('log') ?? 0)
  const [start, setStart] = useState(addDays(todayIso(), -27))
  const [end, setEnd] = useState(todayIso())
  const [page, setPage] = useState(1)
  const isManager = user.role !== 'employee'
  const { data: people } = useQuery({ queryKey: ['users', 'visible'], queryFn: () => api<Page<User>>('/users?page_size=200'), enabled: isManager })
  const { data, isLoading } = useQuery({
    queryKey: ['work-logs', employee, start, end, page],
    queryFn: () => api<Page<DailyLog>>(`/work-logs${qs({ employee_id: employee, start, end, page, page_size: 20 })}`),
  })
  const pages = data ? Math.ceil(data.total / data.page_size) : 1

  return (
    <>
      <PageHeader
        title="Work history"
        subtitle="Every daily update with the original text and the extracted work items."
        actions={
          <>
            {isManager && (
              <select
                className="input w-auto"
                value={employee}
                onChange={(e) => {
                  setPage(1)
                  setParams(e.target.value ? { employee: e.target.value } : {})
                }}
                aria-label="Employee"
              >
                <option value="">Everyone I can see</option>
                {people?.items.filter((p) => p.role !== 'admin').map((p) => <option key={p.id} value={p.id}>{p.full_name}</option>)}
              </select>
            )}
            <input type="date" className="input w-auto" value={start} max={end} onChange={(e) => setStart(e.target.value)} aria-label="From" />
            <input type="date" className="input w-auto" value={end} min={start} max={todayIso()} onChange={(e) => setEnd(e.target.value)} aria-label="To" />
          </>
        }
      />
      {isLoading ? (
        <Spinner />
      ) : !data?.items.length ? (
        <Card><Empty icon={<HistoryIcon className="h-8 w-8" />} title="No updates in this period" /></Card>
      ) : (
        <div className="space-y-3">
          {data.items.map((log) => (
            <LogCard
              key={log.id}
              log={log}
              defaultOpen={log.id === highlight}
              canEdit={log.employee_id === user.id || user.role === 'admin'}
              showName={isManager}
            />
          ))}
          {pages > 1 && (
            <div className="flex items-center justify-center gap-2 pt-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</Button>
              <span className="text-sm text-slate-500">Page {page} of {pages}</span>
              <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
            </div>
          )}
        </div>
      )}
    </>
  )
}
