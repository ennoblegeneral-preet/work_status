import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import { Bot, CheckCircle2, ClipboardPaste, Loader2, MessageSquare, Plus, Send, Sparkles, Trash2, User as UserIcon } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api } from '../api'
import { Alert, Badge, Button, Card, ErrorText, Field, PageHeader, Spinner, Tabs } from '../components/ui'
import { fmtDay, todayIso } from '../lib/format'
import type { DailyLog, Draft, DraftItem, DraftOut, GoalOption } from '../types'

const EXAMPLE =
  'Fixed the scoring error in the Scoring Agent, added a new guardrail to the Interviewer Agent, tested phone detection, and reviewed the code. Total time spent: 7.5 hours.'

// ---------------------------------------------------------------- start screen

function StartUpdate() {
  const navigate = useNavigate()
  const [mode, setMode] = useState<'paste' | 'chat'>('paste')
  const [text, setText] = useState('')
  const [date, setDate] = useState(todayIso())
  const { data: drafts = [] } = useQuery({ queryKey: ['drafts'], queryFn: () => api<DraftOut[]>('/daily-updates/drafts') })
  const parse = useMutation({
    mutationFn: () =>
      api<DraftOut>('/daily-updates/parse', {
        method: 'POST',
        json: { text, input_method: mode, report_date: date === todayIso() ? null : date },
      }),
    onSuccess: (d) => navigate(`/update/${d.log_id}`),
  })

  return (
    <>
      <PageHeader
        title="Daily work update"
        subtitle="Paste your status (from ChatGPT or anywhere) or just type what you did. AI turns it into tracked work - you review before anything is saved."
      />
      <div className="grid gap-5 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 px-4 py-3">
            <Tabs
              value={mode}
              onChange={setMode}
              tabs={[
                { value: 'paste', label: <><ClipboardPaste className="h-4 w-4" /> Paste report</> },
                { value: 'chat', label: <><MessageSquare className="h-4 w-4" /> AI chat</> },
              ]}
            />
            <label className="flex items-center gap-2 text-sm text-slate-600">
              Work date
              <input type="date" className="input w-auto py-1.5" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value)} />
            </label>
          </div>
          <div className="space-y-3 p-4">
            {mode === 'chat' && (
              <div className="flex gap-2 rounded-lg bg-brand-50 p-3 text-sm text-brand-700">
                <Bot className="h-5 w-5 shrink-0" />
                <p>Hi! Tell me what you worked on today, in your own words. I'll match it to your weekly goals and ask if anything is unclear.</p>
              </div>
            )}
            <textarea
              className="input min-h-56 resize-y font-[inherit] leading-relaxed"
              placeholder={
                mode === 'paste'
                  ? 'Paste your daily status report here...'
                  : 'e.g. I worked on Donor IQ today. Fixed a bug in the search agent, added a fallback query and deployed. Spent 6 hours.'
              }
              value={text}
              onChange={(e) => setText(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && text.trim().length >= 3) parse.mutate()
              }}
              autoFocus
            />
            <ErrorText error={parse.error} />
            <div className="flex flex-wrap items-center justify-between gap-2">
              <button className="text-xs text-slate-400 hover:text-slate-600" onClick={() => setText(EXAMPLE)}>
                Try an example
              </button>
              <Button onClick={() => parse.mutate()} loading={parse.isPending} disabled={text.trim().length < 3}>
                {parse.isPending ? 'Reading your update...' : <><Sparkles className="h-4 w-4" /> {mode === 'paste' ? 'Parse update' : 'Send'}</>}
              </Button>
            </div>
          </div>
        </Card>
        <div className="space-y-4">
          <Card title="How it works">
            <ol className="space-y-2.5 p-4 text-sm text-slate-600">
              {[
                'Paste or type your update - any format works.',
                'AI splits it into work items, links them to your weekly goals and picks up hours, blockers and next steps.',
                'Check the highlighted items, fix anything, then save.',
              ].map((s, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-700">{i + 1}</span>
                  {s}
                </li>
              ))}
            </ol>
          </Card>
          {drafts.length > 0 && (
            <Card title="Unsaved drafts">
              <ul className="divide-y divide-slate-100">
                {drafts.map((d) => (
                  <li key={d.log_id}>
                    <Link to={`/update/${d.log_id}`} className="block px-4 py-2.5 hover:bg-slate-50">
                      <p className="text-sm font-medium text-slate-700">{fmtDay(d.draft.report_date)}</p>
                      <p className="truncate text-xs text-slate-500">{d.raw_text}</p>
                    </Link>
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      </div>
    </>
  )
}

// ---------------------------------------------------------------- item editor

function linkValue(i: DraftItem): string {
  if (i.task_id) return `task:${i.task_id}`
  if (i.goal_id) return `goal:${i.goal_id}`
  return 'none'
}

function LinkSelect({ item, goals, onChange }: { item: DraftItem; goals: GoalOption[]; onChange: (patch: Partial<DraftItem>) => void }) {
  return (
    <select
      className="input py-1.5"
      value={linkValue(item)}
      onChange={(e) => {
        const [kind, id] = e.target.value.split(':')
        if (kind === 'task') {
          const goal = goals.find((g) => g.tasks.some((t) => t.id === Number(id)))
          onChange({ task_id: Number(id), goal_id: goal?.id ?? null, create_task: false, is_unplanned: !goal?.id })
        } else if (kind === 'goal') {
          onChange({ task_id: null, goal_id: Number(id), create_task: true, is_unplanned: false })
        } else {
          onChange({ task_id: null, goal_id: null, create_task: true, is_unplanned: true })
        }
      }}
    >
      {goals.map((g) => (
        <optgroup key={g.id ?? 'extra'} label={g.code ? `${g.code} ${g.title}` : g.title}>
          {g.id && <option value={`goal:${g.id}`}>+ New task under {g.code}</option>}
          {g.tasks.map((t) => (
            <option key={t.id} value={`task:${t.id}`}>
              {t.code} {t.title} {t.status === 'completed' ? '(done)' : ''}
            </option>
          ))}
        </optgroup>
      ))}
      <option value="none">Additional work (not in my goals)</option>
    </select>
  )
}

function ItemCard({
  item,
  goals,
  onChange,
  onRemove,
}: {
  item: DraftItem
  goals: GoalOption[]
  onChange: (patch: Partial<DraftItem>) => void
  onRemove: () => void
}) {
  const update = (patch: Partial<DraftItem>) => onChange({ ...patch, requires_confirmation: false, match_method: 'manual' })
  return (
    <div className={clsx('rounded-lg border p-3', item.requires_confirmation ? 'border-amber-300 bg-amber-50/40' : 'border-slate-200 bg-white')}>
      <div className="flex items-start gap-2">
        <input
          className="input flex-1 py-1.5 font-medium"
          value={item.task_title}
          onChange={(e) => onChange({ task_title: e.target.value })}
          aria-label="Work item title"
        />
        <button onClick={onRemove} className="rounded p-2 text-slate-400 hover:bg-slate-100 hover:text-rose-600" title="Remove item">
          <Trash2 className="h-4 w-4" />
        </button>
      </div>
      <div className="mt-2 grid gap-2 sm:grid-cols-[1fr_auto_auto_auto]">
        <LinkSelect item={item} goals={goals} onChange={update} />
        <select className="input py-1.5" value={item.status} onChange={(e) => onChange({ status: e.target.value as DraftItem['status'] })} aria-label="Status">
          <option value="in_progress">In progress</option>
          <option value="completed">Completed</option>
          <option value="blocked">Blocked</option>
        </select>
        <select className="input py-1.5" value={item.kind} onChange={(e) => onChange({ kind: e.target.value as DraftItem['kind'] })} aria-label="Type">
          <option value="activity">Activity</option>
          <option value="outcome">Outcome</option>
        </select>
        <input
          className="input w-24 py-1.5"
          type="number"
          min={0}
          max={24}
          step={0.25}
          placeholder="Hours"
          value={item.hours ?? ''}
          onChange={(e) => onChange({ hours: e.target.value === '' ? null : Number(e.target.value) })}
          aria-label="Hours"
        />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
        {item.evidence && <span className="italic">“{item.evidence}”</span>}
        {item.match_note && <span className={clsx(item.requires_confirmation && 'text-amber-700')}>{item.match_note}</span>}
        {item.match_method && item.match_method !== 'none' && item.match_method !== 'manual' && item.confidence !== null && (
          <Badge>
            {item.match_method} match · {Math.round((item.confidence ?? 0) * 100)}%
          </Badge>
        )}
        {item.status === 'completed' && item.task_id && <span className="text-emerald-700">Saving will mark this task completed.</span>}
        {item.requires_confirmation && (
          <button className="ml-auto rounded-md bg-amber-100 px-2 py-1 font-medium text-amber-800 hover:bg-amber-200" onClick={() => onChange({ requires_confirmation: false })}>
            Looks right
          </button>
        )}
      </div>
    </div>
  )
}

function LinesEditor({ label, values, onChange, placeholder }: { label: string; values: string[]; onChange: (v: string[]) => void; placeholder: string }) {
  return (
    <Field label={label} hint="One per line">
      <textarea
        className="input min-h-16"
        placeholder={placeholder}
        value={values.join('\n')}
        onChange={(e) => onChange(e.target.value.split('\n'))}
      />
    </Field>
  )
}

// ---------------------------------------------------------------- review screen

function ReviewUpdate({ logId }: { logId: number }) {
  const qc = useQueryClient()
  const navigate = useNavigate()
  const { data, isLoading, error } = useQuery({ queryKey: ['draft', logId], queryFn: () => api<DraftOut>(`/daily-updates/${logId}/draft`) })
  const [draft, setDraft] = useState<Draft | null>(null)
  const [message, setMessage] = useState('')
  const [saved, setSaved] = useState<DailyLog | null>(null)
  const chatEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (data) setDraft(data.draft)
  }, [data])
  useEffect(() => chatEnd.current?.scrollIntoView({ behavior: 'smooth' }), [data?.chat_messages.length])

  const clean = (d: Draft): Draft => ({
    ...d,
    blockers: d.blockers.map((s) => s.trim()).filter(Boolean),
    next_steps: d.next_steps.map((s) => s.trim()).filter(Boolean),
  })

  const chat = useMutation({
    mutationFn: async () => {
      if (draft) await api(`/daily-updates/${logId}/draft`, { method: 'PUT', json: { draft: clean(draft) } })
      return api<DraftOut>(`/daily-updates/${logId}/chat`, { method: 'POST', json: { message } })
    },
    onSuccess: (d) => {
      qc.setQueryData(['draft', logId], d)
      setMessage('')
    },
  })
  const confirm = useMutation({
    mutationFn: () => api<DailyLog>(`/daily-updates/${logId}/confirm`, { method: 'POST', json: { draft: clean(draft!) } }),
    onSuccess: (log) => {
      setSaved(log)
      qc.invalidateQueries()
    },
  })
  const discard = useMutation({
    mutationFn: () => api(`/daily-updates/${logId}/discard`, { method: 'POST' }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['drafts'] })
      navigate('/update')
    },
  })

  const pending = useMemo(() => draft?.items.filter((i) => i.requires_confirmation).length ?? 0, [draft])

  if (isLoading || (!draft && !error)) return <Spinner />
  if (error || !data || !draft) return <ErrorText error={error ?? 'Draft not found'} />

  if (saved || data.status !== 'draft') {
    const items = saved?.items ?? []
    return (
      <div className="mx-auto max-w-xl py-10 text-center">
        <CheckCircle2 className="mx-auto h-12 w-12 text-emerald-500" />
        <h1 className="mt-3 text-xl font-semibold">Update saved</h1>
        {saved && (
          <p className="mt-1 text-sm text-slate-500">
            {items.length} work item{items.length !== 1 && 's'} recorded for {fmtDay(saved.report_date)}
            {saved.total_hours !== null ? ` · ${saved.total_hours} h` : ' · hours not reported'}
          </p>
        )}
        <div className="mt-6 flex justify-center gap-2">
          <Button variant="secondary" onClick={() => navigate('/history')}>View history</Button>
          <Button variant="secondary" onClick={() => navigate('/goals')}>See goal progress</Button>
          <Button onClick={() => navigate('/update')}>Add another update</Button>
        </div>
      </div>
    )
  }

  const set = (patch: Partial<Draft>) => setDraft({ ...draft, ...patch })
  const setItem = (idx: number, patch: Partial<DraftItem>) => set({ items: draft.items.map((it, i) => (i === idx ? { ...it, ...patch } : it)) })

  return (
    <>
      <PageHeader
        title="Review your update"
        subtitle={
          <>
            Nothing is saved until you click <b>Save update</b>.{' '}
            {data.parse_mode === 'ai' ? 'Parsed by AI.' : 'Parsed by the basic (non-AI) parser.'}
          </>
        }
        actions={<Button variant="ghost" onClick={() => discard.mutate()} loading={discard.isPending}>Discard</Button>}
      />
      <div className="grid gap-5 lg:grid-cols-5">
        {/* original text + chat */}
        <Card className="flex flex-col lg:col-span-2" title="Your update">
          <div className="max-h-[60vh] flex-1 space-y-3 overflow-y-auto p-4">
            <div className="flex gap-2">
              <UserIcon className="mt-1 h-4 w-4 shrink-0 text-slate-400" />
              <p className="whitespace-pre-wrap rounded-lg bg-slate-100 px-3 py-2 text-sm text-slate-700">{data.raw_text}</p>
            </div>
            {data.chat_messages.map((m, i) => (
              <div key={i} className="flex gap-2">
                {m.role === 'assistant' ? <Bot className="mt-1 h-4 w-4 shrink-0 text-brand-500" /> : <UserIcon className="mt-1 h-4 w-4 shrink-0 text-slate-400" />}
                <p className={clsx('whitespace-pre-wrap rounded-lg px-3 py-2 text-sm', m.role === 'assistant' ? 'bg-brand-50 text-brand-800' : 'bg-slate-100 text-slate-700')}>
                  {m.content}
                </p>
              </div>
            ))}
            {chat.isPending && <Loader2 className="ml-6 h-4 w-4 animate-spin text-brand-500" />}
            <div ref={chatEnd} />
          </div>
          <div className="border-t border-slate-100 p-3">
            <ErrorText error={chat.error} />
            <form
              className="flex gap-2"
              onSubmit={(e) => {
                e.preventDefault()
                if (message.trim()) chat.mutate()
              }}
            >
              <input
                className="input"
                placeholder={draft.clarification_question ? 'Answer the question...' : 'Add details or corrections...'}
                value={message}
                onChange={(e) => setMessage(e.target.value)}
              />
              <Button type="submit" disabled={!message.trim()} loading={chat.isPending} aria-label="Send">
                <Send className="h-4 w-4" />
              </Button>
            </form>
            <p className="mt-1.5 text-xs text-slate-400">The assistant re-reads your update with your message and refreshes the items.</p>
          </div>
        </Card>

        {/* structured preview */}
        <div className="space-y-4 lg:col-span-3">
          {draft.warnings.map((w) => <Alert key={w} tone="warning">{w}</Alert>)}
          {draft.clarification_question && <Alert tone="info"><b>Question:</b> {draft.clarification_question}</Alert>}
          {data.other_updates_today > 0 && (
            <Alert tone="info">You already saved {data.other_updates_today} update(s) for this date. This one will be added alongside.</Alert>
          )}
          <Card
            title={`Work items (${draft.items.length})`}
            actions={
              <input
                type="date"
                className="input w-auto py-1"
                value={draft.report_date}
                max={todayIso()}
                onChange={(e) => set({ report_date: e.target.value })}
                aria-label="Report date"
              />
            }
          >
            <div className="space-y-2.5 p-4">
              {draft.items.map((it, idx) => (
                <ItemCard
                  key={idx}
                  item={it}
                  goals={data.goals}
                  onChange={(p) => setItem(idx, p)}
                  onRemove={() => set({ items: draft.items.filter((_, i) => i !== idx) })}
                />
              ))}
              <Button
                variant="secondary"
                size="sm"
                onClick={() =>
                  set({
                    items: [
                      ...draft.items,
                      {
                        task_title: 'New item', description: null, project: null, goal_id: null, task_id: null, create_task: true,
                        is_unplanned: true, status: 'in_progress', kind: 'activity', evidence: null, hours: null, confidence: null,
                        match_method: 'manual', match_note: null, requires_confirmation: false, duplicate_of_item_id: null,
                      },
                    ],
                  })
                }
              >
                <Plus className="h-4 w-4" /> Add item
              </Button>
            </div>
          </Card>
          <Card>
            <div className="grid gap-4 p-4 sm:grid-cols-3">
              <Field label="Total hours" hint="Leave empty if not tracked">
                <input
                  className="input"
                  type="number"
                  min={0}
                  max={24}
                  step={0.25}
                  value={draft.total_hours ?? ''}
                  onChange={(e) => set({ total_hours: e.target.value === '' ? null : Number(e.target.value) })}
                />
              </Field>
              <LinesEditor label="Blockers" values={draft.blockers} onChange={(v) => set({ blockers: v })} placeholder="Anything stopping you?" />
              <LinesEditor label="Next steps" values={draft.next_steps} onChange={(v) => set({ next_steps: v })} placeholder="What's next?" />
            </div>
          </Card>
          <ErrorText error={confirm.error} />
          <div className="flex flex-wrap items-center justify-end gap-3">
            {pending > 0 && (
              <span className="text-sm text-amber-700">
                Check {pending} highlighted item{pending > 1 && 's'} first
                <button className="ml-2 underline" onClick={() => set({ items: draft.items.map((i) => ({ ...i, requires_confirmation: false })) })}>
                  all look right
                </button>
              </span>
            )}
            <Button variant="success" onClick={() => confirm.mutate()} loading={confirm.isPending} disabled={pending > 0 || draft.items.length === 0}>
              <CheckCircle2 className="h-4 w-4" /> Save update
            </Button>
          </div>
        </div>
      </div>
    </>
  )
}

export default function DailyUpdate() {
  const { logId } = useParams()
  return logId ? <ReviewUpdate key={logId} logId={Number(logId)} /> : <StartUpdate />
}
