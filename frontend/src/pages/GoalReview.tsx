import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CalendarCheck } from 'lucide-react'
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { api, qs } from '../api'
import { progressHint } from '../components/goals'
import { Badge, Button, Card, Empty, ErrorText, Field, Modal, PageHeader, Progress, Spinner } from '../components/ui'
import { addDays, fmtDate, mondayOf, todayIso } from '../lib/format'
import type { Goal } from '../types'
import { WeekPicker } from '../components/WeekPicker'

type Action = 'carry_forward' | 'complete' | 'defer' | 'cancel'
const ACTIONS: { value: Action; label: string; variant: 'primary' | 'secondary' }[] = [
  { value: 'carry_forward', label: 'Carry forward', variant: 'primary' },
  { value: 'complete', label: 'Mark complete', variant: 'secondary' },
  { value: 'defer', label: 'Defer', variant: 'secondary' },
  { value: 'cancel', label: 'Cancel', variant: 'secondary' },
]

export default function GoalReview() {
  const qc = useQueryClient()
  const thisWeek = mondayOf(todayIso())
  // Early in the week, the review is usually for last week.
  const [week, setWeek] = useState(() => {
    const day = new Date().getDay()
    return day >= 1 && day <= 3 ? addDays(thisWeek, -7) : thisWeek
  })
  const [target, setTarget] = useState<{ goal: Goal; action: Action } | null>(null)
  const [reason, setReason] = useState('')
  const [deadline, setDeadline] = useState('')
  const { data = [], isLoading } = useQuery({ queryKey: ['goal-review', week], queryFn: () => api<Goal[]>(`/goals/review${qs({ week_start: week })}`) })
  const decide = useMutation({
    mutationFn: () =>
      api(`/goals/${target!.goal.id}/review`, {
        method: 'POST',
        json: { action: target!.action, reason, new_deadline: target!.action === 'carry_forward' && deadline ? deadline : null },
      }),
    onSuccess: () => {
      setTarget(null)
      setReason('')
      setDeadline('')
      qc.invalidateQueries()
    },
  })

  return (
    <>
      <PageHeader
        title="End-of-week goal review"
        subtitle="Unfinished goals stay open until someone decides what happens to them. Nothing is carried over automatically."
        actions={<WeekPicker value={week} onChange={setWeek} />}
      />
      <Card>
        {isLoading ? (
          <Spinner />
        ) : data.length === 0 ? (
          <Empty icon={<CalendarCheck className="h-8 w-8" />} title="Nothing to review">All goals for this week are completed or already reviewed.</Empty>
        ) : (
          <ul className="divide-y divide-slate-100">
            {data.map((g) => (
              <li key={g.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
                <div className="min-w-64 flex-1">
                  <Link to={`/goals/${g.id}`} className="font-medium text-slate-800 hover:text-brand-600">{g.code} {g.title}</Link>
                  <p className="text-xs text-slate-500">
                    {g.owner.full_name} · due {fmtDate(g.deadline ?? g.week_end)} · {progressHint(g)}
                  </p>
                  <Progress value={g.progress} className="mt-1.5 max-w-xs" />
                </div>
                <Badge value={g.status} />
                <div className="flex flex-wrap gap-1.5">
                  {ACTIONS.map((a) => (
                    <Button key={a.value} size="sm" variant={a.variant} onClick={() => setTarget({ goal: g, action: a.value })}>
                      {a.label}
                    </Button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Modal open={!!target} onClose={() => setTarget(null)} title={target ? `${ACTIONS.find((a) => a.value === target.action)?.label}: ${target.goal.title}` : ''}>
        {target?.action === 'carry_forward' && (
          <p className="mb-3 text-sm text-slate-600">
            A new goal is created for next week with the unfinished tasks. This goal is closed as deferred, keeping its history and original deadline.
          </p>
        )}
        <Field label="Reason (required)" hint="Shown in reports, e.g. the reason for the delay">
          <textarea className="input" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
        </Field>
        {target?.action === 'carry_forward' && (
          <div className="mt-3">
            <Field label="New deadline" hint="Defaults to one week after the current deadline">
              <input type="date" className="input" value={deadline} min={target ? addDays(target.goal.week_start, 7) : undefined} onChange={(e) => setDeadline(e.target.value)} />
            </Field>
          </div>
        )}
        <ErrorText error={decide.error} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setTarget(null)}>Cancel</Button>
          <Button onClick={() => decide.mutate()} loading={decide.isPending} disabled={reason.trim().length < 3}>Confirm</Button>
        </div>
      </Modal>
    </>
  )
}
