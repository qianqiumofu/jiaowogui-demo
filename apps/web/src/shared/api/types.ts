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

export interface ApiErrorBody {
  code: string
  message: string
  request_id: string
  details: Record<string, unknown>
}
