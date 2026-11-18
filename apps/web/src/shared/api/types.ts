// 手写占位类型：SDK 生成方案见 docs/12-契约与接口同步.md。

export type Role = 'STUDENT' | 'DORM_MANAGER' | 'COUNSELOR' | 'CAMPUS'

export interface Scope {
  student_id?: string | null
  counselor_user_id?: string
  student_ids?: string[]
  building_ids?: string[]
  scope?: string
  resolved_by: string
  granted_building_ids?: string[]
  pending_sync?: boolean
}

export interface SessionContext {
  session_id: string
  user_id: string
  school_id: string
  display_name: string
  roles: Role[]
  active_role: Role
  scope: Scope
  expires_at: string
}

export interface AuthSession {
  token: string
  session: SessionContext
}

export interface DemoAccount {
  login_name: string
  display_name: string
  roles: Role[]
  password: string
}

export interface ListResult<T> {
  items: T[]
  next_cursor: string | null
}

export interface AllowedActions {
  role: Role
  allowed_actions: string[]
}

export interface ClockState {
  now: string
  offset_minutes: number
}

export type ChangeFlag = 'RESCHEDULED' | 'CANCELLED' | 'ADDED_AFTER_SUMMARY'

export type ReturnStatus = 'PENDING' | 'ENTERED' | 'MANUAL_ENTERED'

export interface TonightItem {
  student_id: string
  school_id: string
  display_name: string
  room_no: string
  college_name?: string
  grade?: string
  planned_return_at: string
  reservation_status: 'ACTIVE' | 'CANCELLED' | 'FULFILLED' | 'CLOSED' | 'NONE'
  reservation_version?: number
  updated_at?: string
  change_flag?: ChangeFlag | null
  return_status: ReturnStatus
  entered_at?: string | null
  gate_id?: string | null
  return_source?: 'QR' | 'MANUAL' | null
}

export interface BuildingTonight {
  building_id: string
  service_date: string
  summary_generated_at?: string | null
  counters: { total: number; entered: number }
  items: TonightItem[]
  next_cursor: string | null
}

export type PassStatus = 'ISSUED' | 'CONSUMED' | 'EXPIRED' | 'REVOKED'

export interface ReturnRecordItem {
  pass_id: string | null
  student_id: string
  school_id: string
  display_name: string
  reservation_id: string | null
  building_id: string
  gate_id: string | null
  reservation_version?: number | null
  service_date: string
  window_start?: string | null
  window_end?: string | null
  issued_at?: string | null
  expires_at?: string | null
  used_at?: string | null
  pass_status: PassStatus | null
  return_id: string | null
  return_source: 'QR' | 'MANUAL' | null
  returned_at?: string | null
}

export interface ReturnRecords {
  service_date: string
  building_id: string | null
  counters: { issued: number; consumed: number; expired: number; revoked: number; returned: number }
  items: ReturnRecordItem[]
  next_cursor: string | null
}

export interface ReturnRecord {
  return_id: string
  student_id: string
  service_date: string
  source: 'QR' | 'MANUAL'
  pass_id: string | null
  gate_id: string | null
  gate_name: string | null
  reservation_id: string | null
  occurred_at: string
  recorded_at: string
  evidence: Record<string, unknown>
  idempotency_key: string
}

export interface ScanResult {
  attempt_status: string
  pass_id?: string
  duplicate?: boolean
  return_id?: string
  return_source?: string
  occurred_at?: string
  [key: string]: unknown
}

export interface StudentContact {
  student_id: string
  school_id?: string
  display_name?: string
  building_id: string
  room_no: string
  gender?: 'MALE' | 'FEMALE'
  phone?: string | null
}

export interface BuildingResident {
  student_id: string
  school_id: string
  display_name: string
  building_id: string
  room_no: string
  college_name?: string
  grade?: string | null
  gender?: 'MALE' | 'FEMALE'
}

export interface ResidentList {
  building_id: string
  items: BuildingResident[]
  next_cursor: string | null
}

export interface ApiErrorBody {
  code: string
  message: string
  request_id: string
  details: Record<string, unknown>
}

export interface StatisticsDimension {
  org_id?: string
  building_id?: string
  name: string
  code?: string
  park_org_id?: string
  building_count?: number
}

export interface StatisticsFilters {
  colleges: Array<{ org_id: string; name: string }>
  parks: StatisticsDimension[]
  buildings: StatisticsDimension[]
  grades: string[]
  genders: Array<'MALE' | 'FEMALE'>
  return_sources: Array<'QR' | 'MANUAL'>
}

// 三值分列（R14）：人数、晚归夜数、返宿次数各自独立，预约两列在来源落地前恒为 null。
export interface StatisticsMetrics {
  people: number
  nights: number
  returns: number
  qr_returns: number
  manual_returns: number
  enrolled: number
  reservations: number | null
  unconfirmed: number | null
}

export interface StatisticsRow extends StatisticsMetrics {
  value: string | null
  label: string
}

export interface StatisticsDay extends StatisticsMetrics {
  service_date: string
}

export interface StatisticsResult {
  group_by: string
  attribution: string
  range: { date_from: string; date_to: string }
  filters: Record<string, string>
  totals: StatisticsMetrics
  rows: StatisticsRow[]
  by_day: StatisticsDay[]
  data_gaps: string[]
}

export type ExportStatus = 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED'

export interface ExportJob {
  export_id: string
  report: string
  status: ExportStatus
  requested_by: string
  params: Record<string, unknown>
  file_name: string | null
  row_count: number | null
  error: string | null
  idempotency_key: string | null
  created_at: string
  updated_at: string
  done_at: string | null
  expires_at: string | null
  downloadable: boolean
}
