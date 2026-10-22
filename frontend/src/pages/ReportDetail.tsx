import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ArrowLeft, CheckCircle2, Download, Pencil, RotateCcw, Send, Sparkles, Undo2 } from 'lucide-react'
import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { Link, useParams } from 'react-router-dom'
import remarkGfm from 'remark-gfm'
import { api, download } from '../api'
import { useUser } from '../auth'
import { Alert, Badge, Button, Card, ErrorText, Field, Modal, PageHeader, Spinner } from '../components/ui'
import { fmtDateTime, weekLabel } from '../lib/format'
import type { Report } from '../types'

export default function ReportDetail() {
  const { id } = useParams()
  const user = useUser()
  const qc = useQueryClient()
  const { data: r, isLoading, error } = useQuery({ queryKey: ['report', id], queryFn: () => api<Report>(`/reports/${id}`) })
  const [editing, setEditing] = useState<string | null>(null)
  const [action, setAction] = useState<'submit' | 'approve' | 'return' | null>(null)
  const [comment, setComment] = useState('')
  const [exportError, setExportError] = useState<unknown>(null)

  const onDone = (data: Report) => {
    qc.setQueryData(['report', id], data)
    qc.invalidateQueries({ queryKey: ['reports'] })
    qc.invalidateQueries({ queryKey: ['notifications'] })
    setAction(null)
    setComment('')
    setEditing(null)
  }
  const act = useMutation({
    mutationFn: (a: 'submit' | 'approve' | 'return') => api<Report>(`/reports/${id}/${a}`, { method: 'POST', json: { comment: comment || null } }),
    onSuccess: onDone,
  })
  const save = useMutation({
    mutationFn: () => api<Report>(`/reports/${id}/content`, { method: 'PUT', json: { content_markdown: editing } }),
    onSuccess: onDone,
  })
  const regenerate = useMutation({
    mutationFn: () =>
      api<Report>('/reports/generate', {
        method: 'POST',
        json: { week_start: r!.week_start, ...(r!.report_type === 'employee' ? { employee_id: r!.employee_id } : { team_id: r!.team_id }) },
      }),
    onSuccess: onDone,
  })

  if (isLoading) return <Spinner />
  if (error || !r) return <ErrorText error={error ?? 'Not found'} />

  const isSubject = r.report_type === 'employee' && r.employee_id === user.id
  const canReview = user.role !== 'employee' && !isSubject
  const open = r.status === 'draft' || r.status === 'returned'
  const canEdit = r.status !== 'approved' && (canReview || (isSubject && open))
  const canSubmit = r.report_type === 'employee' && open && (isSubject || canReview)
  const canApprove = canReview && (r.status === 'draft' || r.status === 'submitted')
  const canReturn = canReview && r.status === 'submitted'
  const lastReturn = [...r.reviews].reverse().find((x) => x.action === 'return')

  const exportAs = async (format: string) => {
    setExportError(null)
    try {
      await download(`/reports/${r.id}/export?format=${format}`)
    } catch (e) {
      setExportError(e)
    }
  }

  return (
    <>
      <Link to="/reports" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-500 hover:text-slate-700">
        <ArrowLeft className="h-4 w-4" /> Reports
      </Link>
      <PageHeader
        title={r.report_type === 'employee' ? `Weekly report: ${r.employee?.full_name}` : `Team report: ${r.team_name}`}
        subtitle={
          <span className="flex flex-wrap items-center gap-2">
            {weekLabel(r.week_start)} <Badge value={r.status} /> <span>v{r.version}</span>
            <span className="inline-flex items-center gap-1 text-xs">
              <Sparkles className="h-3 w-3" /> {r.generation_mode === 'ai' ? 'AI summary + records' : 'Records only'}
            </span>
            {r.edited_by_human && <span className="text-xs">· edited by a person</span>}
          </span>
        }
        actions={
          <>
            {open && (canReview || isSubject) && (
              <Button variant="ghost" onClick={() => regenerate.mutate()} loading={regenerate.isPending} title="Rebuild from the latest records">
                <RotateCcw className="h-4 w-4" /> Regenerate
              </Button>
            )}
            {canEdit && editing === null && <Button variant="secondary" onClick={() => setEditing(r.content_markdown)}><Pencil className="h-4 w-4" /> Edit</Button>}
            {canSubmit && <Button onClick={() => setAction('submit')}><Send className="h-4 w-4" /> Submit for review</Button>}
            {canReturn && <Button variant="secondary" onClick={() => setAction('return')}><Undo2 className="h-4 w-4" /> Return</Button>}
            {canApprove && <Button variant="success" onClick={() => setAction('approve')}><CheckCircle2 className="h-4 w-4" /> Approve</Button>}
            {r.status === 'approved' && (
              <>
                <Button variant="secondary" onClick={() => exportAs('pdf')}><Download className="h-4 w-4" /> PDF</Button>
                <Button variant="secondary" onClick={() => exportAs('xlsx')}><Download className="h-4 w-4" /> Excel</Button>
                <Button variant="secondary" onClick={() => exportAs('md')}><Download className="h-4 w-4" /> Markdown</Button>
              </>
            )}
          </>
        }
      />
      <div className="space-y-3">
        <ErrorText error={regenerate.error ?? exportError} />
        {r.status === 'returned' && lastReturn && (
          <Alert tone="warning">
            <b>Returned for correction by {lastReturn.reviewer.full_name}:</b> {lastReturn.comment}
          </Alert>
        )}
        {r.validation_warnings.length > 0 && (
          <Alert tone="warning">
            <p className="font-medium">Check before approving ({r.validation_warnings.length})</p>
            <ul className="mt-1 list-disc pl-4 text-xs">{r.validation_warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
          </Alert>
        )}
      </div>

      <div className="mt-4 grid gap-5 lg:grid-cols-4">
        <Card className="lg:col-span-3">
          {editing !== null ? (
            <div className="p-4">
              <textarea className="input min-h-[60vh] font-mono text-xs" value={editing} onChange={(e) => setEditing(e.target.value)} />
              <ErrorText error={save.error} />
              <div className="mt-3 flex justify-end gap-2">
                <Button variant="secondary" onClick={() => setEditing(null)}>Cancel</Button>
                <Button onClick={() => save.mutate()} loading={save.isPending}>Save changes</Button>
              </div>
            </div>
          ) : (
            <article className="prose prose-sm prose-slate max-w-none p-6 prose-headings:font-semibold prose-h1:text-xl prose-h3:mt-6 prose-h3:text-base prose-table:text-xs prose-code:rounded prose-code:bg-slate-100 prose-code:px-1 prose-code:text-[10px] prose-code:font-normal prose-code:text-slate-500 prose-code:before:content-none prose-code:after:content-none">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{r.content_markdown}</ReactMarkdown>
            </article>
          )}
        </Card>
        <Card title="Review trail" className="h-fit">
          <ol className="space-y-3 p-4">
            {r.reviews.map((rv) => (
              <li key={rv.id} className="border-l-2 border-slate-100 pl-3 text-sm">
                <p className="font-medium capitalize text-slate-700">{rv.action}</p>
                <p className="text-xs text-slate-500">{rv.reviewer.full_name} · {fmtDateTime(rv.created_at)}</p>
                {rv.comment && <p className="mt-0.5 text-xs text-slate-600">“{rv.comment}”</p>}
              </li>
            ))}
            {r.reviews.length === 0 && <p className="text-sm text-slate-400">Generated automatically.</p>}
          </ol>
        </Card>
      </div>

      <Modal open={action !== null} onClose={() => setAction(null)} title={action === 'submit' ? 'Submit report' : action === 'approve' ? 'Approve report' : 'Return for correction'}>
        <Field label={action === 'return' ? 'What needs to change? (required)' : 'Comment (optional)'}>
          <textarea className="input" value={comment} onChange={(e) => setComment(e.target.value)} autoFocus />
        </Field>
        {action === 'approve' && r.validation_warnings.length > 0 && (
          <Alert tone="warning" className="mt-3">This report has {r.validation_warnings.length} validation warning(s). Make sure you have checked them.</Alert>
        )}
        <ErrorText error={act.error} />
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setAction(null)}>Cancel</Button>
          <Button
            variant={action === 'approve' ? 'success' : 'primary'}
            onClick={() => action && act.mutate(action)}
            loading={act.isPending}
            disabled={action === 'return' && !comment.trim()}
          >
            Confirm
          </Button>
        </div>
      </Modal>
    </>
  )
}
