import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FileText, Sparkles, Users } from 'lucide-react'
import { useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, qs } from '../api'
import { useUser } from '../auth'
import { Badge, Button, Card, Empty, ErrorText, PageHeader, Spinner, Table, td, th } from '../components/ui'
import { fmtDateTime, mondayOf, todayIso } from '../lib/format'
import type { Page, Report, ReportListItem, Team, User } from '../types'
import { WeekPicker } from '../components/WeekPicker'

export default function Reports() {
  const user = useUser()
  const qc = useQueryClient()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [week, setWeek] = useState(mondayOf(todayIso()))
  const [status, setStatus] = useState(params.get('status') ?? '')
  const isManager = user.role !== 'employee'

  const { data: reports, isLoading } = useQuery({
    queryKey: ['reports', week, status],
    queryFn: () => api<ReportListItem[]>(`/reports${qs({ week_start: status === 'submitted' ? undefined : week, status })}`),
  })
  const { data: people } = useQuery({
    queryKey: ['users', 'visible'],
    queryFn: () => api<Page<User>>('/users?page_size=200&active=true'),
    enabled: isManager,
  })
  const { data: teams = [] } = useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/teams'), enabled: isManager })
  const generate = useMutation({
    mutationFn: (body: { employee_id?: number; team_id?: number }) => api<Report>('/reports/generate', { method: 'POST', json: { week_start: week, ...body } }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ['reports'] })
      navigate(`/reports/${r.id}`)
    },
  })

  const byEmployee = new Map((reports ?? []).filter((r) => r.report_type === 'employee').map((r) => [r.employee_id, r]))
  const byTeam = new Map((reports ?? []).filter((r) => r.report_type === 'team').map((r) => [r.team_id, r]))
  const employees = isManager
    ? (people?.items ?? []).filter((p) => p.role !== 'admin' && (user.role === 'admin' || p.id !== user.id))
    : [user]
  const reviewTeams = teams.filter((t) => user.role === 'admin' || t.manager_id === user.id)

  return (
    <>
      <PageHeader
        title={isManager ? 'Report center' : 'My weekly reports'}
        subtitle="Reports are drafted from saved daily updates and goal records, then reviewed and approved by a manager."
        actions={
          <>
            {isManager && (
              <select className="input w-auto" value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
                <option value="">All statuses</option>
                <option value="submitted">Awaiting my review (all weeks)</option>
                <option value="draft">Draft</option>
                <option value="returned">Returned</option>
                <option value="approved">Approved</option>
              </select>
            )}
            {status !== 'submitted' && <WeekPicker value={week} onChange={setWeek} />}
          </>
        }
      />
      <ErrorText error={generate.error} />
      {isLoading ? (
        <Spinner />
      ) : status === 'submitted' ? (
        <Card title="Awaiting review">
          {!reports?.length ? <Empty title="No reports awaiting review" /> : (
            <ul className="divide-y divide-slate-100">
              {reports.map((r) => (
                <li key={r.id}>
                  <Link to={`/reports/${r.id}`} className="flex items-center justify-between px-4 py-3 hover:bg-slate-50">
                    <span className="text-sm font-medium">{r.employee?.full_name ?? r.team_name} · week of {r.week_start}</span>
                    <Badge value={r.status} />
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ) : (
        <div className="space-y-5">
          {isManager && reviewTeams.length > 0 && (
            <Card title={<span className="flex items-center gap-1.5"><Users className="h-4 w-4" /> Consolidated team reports</span>}>
              <Table>
                <tbody className="divide-y divide-slate-100">
                  {reviewTeams.map((t) => {
                    const r = byTeam.get(t.id)
                    return (
                      <tr key={t.id}>
                        <td className={td + ' font-medium'}>{t.name}</td>
                        <td className={td}>{r ? <Badge value={r.status} /> : <span className="text-slate-400">Not generated</span>}</td>
                        <td className={td + ' text-right'}>
                          {r && <Link to={`/reports/${r.id}`}><Button variant="secondary" size="sm">Open</Button></Link>}{' '}
                          {(!r || r.status === 'draft') && (
                            <Button size="sm" onClick={() => generate.mutate({ team_id: t.id })} loading={generate.isPending && generate.variables?.team_id === t.id}>
                              <Sparkles className="h-3.5 w-3.5" /> {r ? 'Regenerate' : 'Generate'}
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </Table>
            </Card>
          )}
          <Card title={<span className="flex items-center gap-1.5"><FileText className="h-4 w-4" /> Individual reports</span>}>
            {employees.length === 0 ? (
              <Empty title="No people to report on" />
            ) : (
              <Table>
                <thead className="bg-slate-50">
                  <tr>
                    <th className={th}>Employee</th>
                    <th className={th}>Status</th>
                    <th className={th}>Mode</th>
                    <th className={th}>Updated</th>
                    <th className={th} />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {employees.map((p) => {
                    const r = byEmployee.get(p.id)
                    const canRegenerate = !r || r.status === 'draft' || r.status === 'returned'
                    return (
                      <tr key={p.id}>
                        <td className={td + ' font-medium'}>{p.full_name}</td>
                        <td className={td}>{r ? <Badge value={r.status} /> : <span className="text-slate-400">Not generated</span>}</td>
                        <td className={td + ' text-xs text-slate-500'}>{r ? (r.generation_mode === 'ai' ? 'AI + records' : 'Records only') : '-'}</td>
                        <td className={td + ' text-xs text-slate-500'}>{r ? fmtDateTime(r.updated_at) : '-'}</td>
                        <td className={td + ' whitespace-nowrap text-right'}>
                          {r && <Link to={`/reports/${r.id}`}><Button variant="secondary" size="sm">Open</Button></Link>}{' '}
                          {canRegenerate && (
                            <Button size="sm" onClick={() => generate.mutate({ employee_id: p.id })} loading={generate.isPending && generate.variables?.employee_id === p.id}>
                              <Sparkles className="h-3.5 w-3.5" /> {r ? 'Regenerate' : 'Generate'}
                            </Button>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </Table>
            )}
          </Card>
        </div>
      )}
    </>
  )
}
