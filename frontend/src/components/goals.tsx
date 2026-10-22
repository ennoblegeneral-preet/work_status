import clsx from 'clsx'
import { AlertTriangle, CornerDownRight } from 'lucide-react'
import { Link } from 'react-router-dom'
import { fmtDate } from '../lib/format'
import type { Goal } from '../types'
import { Badge, Progress } from './ui'

export function progressHint(g: Goal): string {
  if (g.target_type === 'number') return `${g.current_value ?? 0} / ${g.target_value} ${g.unit ?? ''}`.trim()
  if (g.target_type === 'boolean') return 'Done / not done'
  const tasks = g.tasks.filter((t) => t.status !== 'cancelled')
  return `${tasks.filter((t) => t.status === 'completed').length}/${tasks.length} tasks`
}

export function GoalRow({ goal: g, showOwner }: { goal: Goal; showOwner?: boolean }) {
  return (
    <li>
      <Link to={`/goals/${g.id}`} className="block px-4 py-3 transition hover:bg-slate-50">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-mono text-slate-400">{g.code}</span>
          <span className="font-medium text-slate-800">{g.title}</span>
          {g.priority === 'high' || g.priority === 'critical' ? <Badge value={g.priority} /> : null}
          {g.carried_from_goal_id && (
            <span className="inline-flex items-center gap-0.5 text-xs text-violet-600">
              <CornerDownRight className="h-3 w-3" /> carried over
            </span>
          )}
          <span className="ml-auto flex items-center gap-1.5">
            <Badge value={g.status} />
            {!['completed', 'cancelled', 'deferred'].includes(g.status) && g.health !== 'not_started' && <Badge value={g.health} />}
          </span>
        </div>
        <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
          {showOwner && <span className="font-medium text-slate-600">{g.owner.full_name}</span>}
          {g.project && <span>{g.project}</span>}
          <span>Due {fmtDate(g.deadline ?? g.week_end)}</span>
          <span>{progressHint(g)}</span>
          {g.blockers && (
            <span className="inline-flex items-center gap-1 text-rose-600">
              <AlertTriangle className="h-3 w-3" /> {g.blockers}
            </span>
          )}
        </div>
        <Progress value={g.progress} className={clsx('mt-2 max-w-md')} />
      </Link>
    </li>
  )
}
