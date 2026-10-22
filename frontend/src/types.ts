export type Role = 'admin' | 'manager' | 'employee'
export type GoalStatus = 'not_started' | 'in_progress' | 'blocked' | 'completed' | 'deferred' | 'cancelled'
export type TaskStatus = 'not_started' | 'in_progress' | 'blocked' | 'completed' | 'cancelled'
export type ItemStatus = 'in_progress' | 'completed' | 'blocked'
export type ItemKind = 'activity' | 'outcome'
export type Priority = 'low' | 'medium' | 'high' | 'critical'
export type TargetType = 'tasks' | 'number' | 'boolean'

export interface UserBrief {
  id: number
  full_name: string
  email: string
  role: Role
  department: string | null
}

export interface User extends UserBrief {
  job_title: string | null
  is_active: boolean
  notification_prefs: Record<string, boolean>
  team_ids: number[]
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface Team {
  id: number
  name: string
  department: string | null
  manager_id: number | null
  manager: UserBrief | null
  members: UserBrief[]
}

export interface Task {
  id: number
  code: string
  goal_id: number | null
  owner_id: number
  title: string
  description: string | null
  project: string | null
  status: TaskStatus
  priority: Priority
  weight: number
  due_date: string | null
  is_unplanned: boolean
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface Goal {
  id: number
  code: string
  title: string
  description: string | null
  owner_id: number
  owner: UserBrief
  team_id: number | null
  project: string | null
  week_start: string
  week_end: string
  expected_outcome: string | null
  success_criteria: string | null
  priority: Priority
  start_date: string | null
  deadline: string | null
  original_deadline: string | null
  status: GoalStatus
  target_type: TargetType
  target_value: number | null
  current_value: number | null
  unit: string | null
  dependencies: string | null
  blockers: string | null
  carried_from_goal_id: number | null
  carry_forward_reason: string | null
  reviewed_at: string | null
  created_at: string
  updated_at: string
  tasks: Task[]
  progress: number
  health: string
  last_activity: string | null
}

export interface DraftItem {
  task_title: string
  description: string | null
  project: string | null
  goal_id: number | null
  task_id: number | null
  create_task: boolean
  is_unplanned: boolean
  status: ItemStatus
  kind: ItemKind
  evidence: string | null
  hours: number | null
  confidence: number | null
  match_method: string | null
  match_note: string | null
  requires_confirmation: boolean
  duplicate_of_item_id: number | null
}

export interface Draft {
  report_date: string
  project: string | null
  items: DraftItem[]
  total_hours: number | null
  blockers: string[]
  next_steps: string[]
  needs_confirmation: boolean
  clarification_question: string | null
  warnings: string[]
}

export interface GoalOption {
  id: number | null
  code: string | null
  title: string
  project: string | null
  status: string | null
  tasks: { id: number; code: string; title: string; status: string }[]
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface DraftOut {
  log_id: number
  status: string
  parse_mode: string
  raw_text: string
  chat_messages: ChatMessage[]
  draft: Draft
  other_updates_today: number
  goals: GoalOption[]
}

export interface WorkLogItem {
  id: number
  report_date: string
  task_id: number | null
  goal_id: number | null
  is_unplanned: boolean
  project: string | null
  task_title: string
  description: string | null
  status: ItemStatus
  kind: ItemKind
  evidence: string | null
  hours: number | null
  confidence: number | null
  match_method: string | null
}

export interface DailyLog {
  id: number
  employee_id: number
  employee: UserBrief
  report_date: string
  input_method: string
  raw_text: string
  chat_messages: ChatMessage[]
  parse_mode: string
  status: string
  total_hours: number | null
  blockers: string[]
  next_steps: string[]
  confirmed_at: string | null
  created_at: string
  items: WorkLogItem[]
}

export interface ReportReview {
  id: number
  reviewer_id: number
  reviewer: UserBrief
  action: string
  comment: string | null
  created_at: string
}

export interface Report {
  id: number
  report_type: 'employee' | 'team'
  employee_id: number | null
  employee: UserBrief | null
  team_id: number | null
  team_name: string | null
  week_start: string
  week_end: string
  status: 'draft' | 'submitted' | 'returned' | 'approved'
  generation_mode: string
  content_markdown: string
  validation_warnings: string[]
  edited_by_human: boolean
  approved_by_id: number | null
  approved_at: string | null
  version: number
  created_at: string
  updated_at: string
  reviews: ReportReview[]
}

export type ReportListItem = Pick<
  Report,
  'id' | 'report_type' | 'employee_id' | 'employee' | 'team_id' | 'team_name' | 'week_start' | 'status' | 'generation_mode' | 'updated_at'
>

export interface OrgSettings {
  org_name: string
  timezone: string
  working_days: number[]
  daily_reminder_time: string
  report_generation_day: number
  report_generation_time: string
  min_daily_hours: number | null
  max_daily_hours: number | null
  managers_can_assign_goals: boolean
  reminders_enabled: boolean
  auto_generate_reports: boolean
  ai_mode: string
}

export interface Notification {
  id: number
  type: string
  title: string
  body: string | null
  link: string | null
  read_at: string | null
  created_at: string
}

export interface HistoryEntry {
  id: number
  from_status: string | null
  to_status: string
  changed_by_id: number | null
  reason: string | null
  created_at: string
  task_id?: number
}

export interface AuditEntry {
  id: number
  actor_id: number | null
  action: string
  entity_type: string
  entity_id: number | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  created_at: string
}

export interface TimeOff {
  id: number
  user_id: number | null
  day: string
  reason: string | null
}
