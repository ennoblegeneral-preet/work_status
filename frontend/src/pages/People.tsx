import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, ErrorText, Field, Modal, PageHeader, Spinner, Table, td, th } from '../components/ui'
import type { Page, Role, Team, User } from '../types'

interface UserForm {
  id?: number
  email: string
  full_name: string
  password: string
  role: Role
  department: string
  job_title: string
  team_ids: number[]
  is_active: boolean
}

function UserModal({ initial, teams, onClose }: { initial: UserForm; teams: Team[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [f, setF] = useState(initial)
  const save = useMutation({
    mutationFn: () => {
      const body = {
        full_name: f.full_name,
        role: f.role,
        department: f.department || null,
        job_title: f.job_title || null,
        team_ids: f.team_ids,
        ...(f.password ? { password: f.password } : {}),
      }
      return f.id
        ? api(`/users/${f.id}`, { method: 'PATCH', json: { ...body, is_active: f.is_active } })
        : api('/users', { method: 'POST', json: { ...body, email: f.email, password: f.password } })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['users'] })
      qc.invalidateQueries({ queryKey: ['teams'] })
      onClose()
    },
  })
  return (
    <Modal open onClose={onClose} title={f.id ? 'Edit person' : 'Add person'}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Full name"><input className="input" value={f.full_name} onChange={(e) => setF({ ...f, full_name: e.target.value })} /></Field>
        <Field label="Email"><input className="input" type="email" value={f.email} disabled={!!f.id} onChange={(e) => setF({ ...f, email: e.target.value })} /></Field>
        <Field label="Role">
          <select className="input" value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as Role })}>
            <option value="employee">Employee</option>
            <option value="manager">Manager</option>
            <option value="admin">Admin</option>
          </select>
        </Field>
        <Field label={f.id ? 'New password (optional)' : 'Initial password'} hint="At least 8 characters">
          <input className="input" type="password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} autoComplete="new-password" />
        </Field>
        <Field label="Department"><input className="input" value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} /></Field>
        <Field label="Job title"><input className="input" value={f.job_title} onChange={(e) => setF({ ...f, job_title: e.target.value })} /></Field>
        <div className="sm:col-span-2">
          <p className="label">Teams</p>
          <div className="flex flex-wrap gap-2">
            {teams.map((t) => (
              <label key={t.id} className="flex items-center gap-1.5 rounded-lg border border-slate-200 px-2.5 py-1.5 text-sm">
                <input
                  type="checkbox"
                  className="accent-brand-600"
                  checked={f.team_ids.includes(t.id)}
                  onChange={() => setF({ ...f, team_ids: f.team_ids.includes(t.id) ? f.team_ids.filter((x) => x !== t.id) : [...f.team_ids, t.id] })}
                />
                {t.name}
              </label>
            ))}
          </div>
        </div>
        {f.id && (
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" className="accent-brand-600" checked={f.is_active} onChange={(e) => setF({ ...f, is_active: e.target.checked })} />
            Active (inactive people cannot log in; their history is kept)
          </label>
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

function TeamModal({ team, users, onClose }: { team: Partial<Team>; users: User[]; onClose: () => void }) {
  const qc = useQueryClient()
  const [name, setName] = useState(team.name ?? '')
  const [department, setDepartment] = useState(team.department ?? '')
  const [manager, setManager] = useState<string>(team.manager_id?.toString() ?? '')
  const [members, setMembers] = useState<number[]>(team.members?.map((m) => m.id) ?? [])
  const save = useMutation({
    mutationFn: () => {
      const body = { name, department: department || null, manager_id: manager ? Number(manager) : null, member_ids: members }
      return team.id ? api(`/teams/${team.id}`, { method: 'PATCH', json: body }) : api('/teams', { method: 'POST', json: body })
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] })
      qc.invalidateQueries({ queryKey: ['users'] })
      onClose()
    },
  })
  const remove = useMutation({
    mutationFn: () => api(`/teams/${team.id}`, { method: 'DELETE' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['teams'] })
      onClose()
    },
  })
  return (
    <Modal open onClose={onClose} title={team.id ? 'Edit team' : 'New team'}>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Team name"><input className="input" value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Department"><input className="input" value={department} onChange={(e) => setDepartment(e.target.value)} /></Field>
        <div className="sm:col-span-2">
          <Field label="Manager">
            <select className="input" value={manager} onChange={(e) => setManager(e.target.value)}>
              <option value="">No manager</option>
              {users.filter((u) => u.role !== 'employee').map((u) => <option key={u.id} value={u.id}>{u.full_name}</option>)}
            </select>
          </Field>
        </div>
        <div className="sm:col-span-2">
          <p className="label">Members</p>
          <div className="grid max-h-56 gap-1 overflow-y-auto sm:grid-cols-2">
            {users.filter((u) => u.role !== 'admin').map((u) => (
              <label key={u.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" className="accent-brand-600" checked={members.includes(u.id)} onChange={() => setMembers(members.includes(u.id) ? members.filter((x) => x !== u.id) : [...members, u.id])} />
                {u.full_name}
              </label>
            ))}
          </div>
        </div>
      </div>
      <ErrorText error={save.error ?? remove.error} />
      <div className="mt-4 flex justify-between gap-2">
        {team.id ? <Button variant="ghost" onClick={() => confirm('Delete this team?') && remove.mutate()}><Trash2 className="h-4 w-4" /> Delete</Button> : <span />}
        <div className="flex gap-2">
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button onClick={() => save.mutate()} loading={save.isPending} disabled={!name.trim()}>Save</Button>
        </div>
      </div>
    </Modal>
  )
}

export default function People() {
  const { data: users, isLoading } = useQuery({ queryKey: ['users', 'all'], queryFn: () => api<Page<User>>('/users?page_size=200') })
  const { data: teams = [] } = useQuery({ queryKey: ['teams'], queryFn: () => api<Team[]>('/teams') })
  const [userForm, setUserForm] = useState<UserForm | null>(null)
  const [teamForm, setTeamForm] = useState<Partial<Team> | null>(null)
  const teamName = (id: number) => teams.find((t) => t.id === id)?.name

  return (
    <>
      <PageHeader
        title="People & teams"
        actions={
          <>
            <Button variant="secondary" onClick={() => setTeamForm({})}><Plus className="h-4 w-4" /> New team</Button>
            <Button
              onClick={() => setUserForm({ email: '', full_name: '', password: '', role: 'employee', department: '', job_title: '', team_ids: [], is_active: true })}
            >
              <UserPlus className="h-4 w-4" /> Add person
            </Button>
          </>
        }
      />
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {teams.map((t) => (
          <Card key={t.id}>
            <div className="flex items-start justify-between p-4">
              <div>
                <p className="font-semibold text-slate-800">{t.name}</p>
                <p className="text-xs text-slate-500">{t.department ?? 'No department'} · Manager: {t.manager?.full_name ?? 'none'}</p>
                <p className="mt-2 text-xs text-slate-500">{t.members.map((m) => m.full_name).join(', ') || 'No members'}</p>
              </div>
              <button className="rounded p-1.5 text-slate-400 hover:bg-slate-100" onClick={() => setTeamForm(t)} title="Edit team"><Pencil className="h-4 w-4" /></button>
            </div>
          </Card>
        ))}
      </div>
      <Card title={`People (${users?.total ?? 0})`}>
        {isLoading ? <Spinner /> : (
          <Table>
            <thead className="bg-slate-50">
              <tr>
                <th className={th}>Name</th>
                <th className={th}>Email</th>
                <th className={th}>Role</th>
                <th className={th}>Department</th>
                <th className={th}>Teams</th>
                <th className={th}>Status</th>
                <th className={th} />
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {users?.items.map((u) => (
                <tr key={u.id} className={u.is_active ? '' : 'opacity-50'}>
                  <td className={td + ' font-medium'}>{u.full_name}<p className="text-xs font-normal text-slate-400">{u.job_title}</p></td>
                  <td className={td}>{u.email}</td>
                  <td className={td + ' capitalize'}>{u.role}</td>
                  <td className={td}>{u.department ?? '-'}</td>
                  <td className={td}>{u.team_ids.map(teamName).join(', ') || '-'}</td>
                  <td className={td}>{u.is_active ? <Badge value="completed">Active</Badge> : <Badge>Inactive</Badge>}</td>
                  <td className={td + ' text-right'}>
                    <button
                      className="rounded p-1.5 text-slate-400 hover:bg-slate-100"
                      title="Edit"
                      onClick={() =>
                        setUserForm({
                          id: u.id, email: u.email, full_name: u.full_name, password: '', role: u.role, department: u.department ?? '',
                          job_title: u.job_title ?? '', team_ids: u.team_ids, is_active: u.is_active,
                        })
                      }
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      {userForm && <UserModal initial={userForm} teams={teams} onClose={() => setUserForm(null)} />}
      {teamForm && <TeamModal team={teamForm} users={users?.items ?? []} onClose={() => setTeamForm(null)} />}
    </>
  )
}
