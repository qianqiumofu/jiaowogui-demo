import type { components } from './schema'
import type {
  AllowedActions,
  ApiErrorBody,
  AuthSession,
  BuildingTonight,
  ClockState,
  DailyReport,
  DemoAccount,
  ExportJob,
  ListResult,
  Notification,
  NotificationDispatchResult,
  NotificationJob,
  NotificationTemplate,
  Reservation,
  ReservationRevision,
  ResidentList,
  ReturnRecord,
  Role,
  ReturnRecords,
  ScanResult,
  SessionContext,
  StaffAccount,
  StaffAccountSecret,
  WeeklyReport,
  StatisticsFilters,
  StatisticsResult,
  StudentContact,
} from './types'

const BASE = '/api/v1'
const TOKEN_KEY = 'jwg_token'

export class ApiRequestError extends Error {
  constructor(
    readonly code: string,
    message: string,
    readonly requestId: string,
    readonly details: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = 'ApiRequestError'
  }
}

export function readToken(): string | null {
  return localStorage.getItem(TOKEN_KEY)
}

export function writeToken(token: string | null): void {
  if (token) localStorage.setItem(TOKEN_KEY, token)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('Accept', 'application/json')
  const token = readToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (init.body !== undefined) headers.set('Content-Type', 'application/json')

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { ...init, headers })
  } catch {
    throw new ApiRequestError(
      'NETWORK_UNAVAILABLE',
      '连不上后端，请确认 API 已在 8000 端口启动。',
      '',
    )
  }

  const text = await response.text()
  const payload: unknown = text ? JSON.parse(text) : null
  if (!response.ok) {
    const body = (payload ?? {}) as Partial<ApiErrorBody>
    throw new ApiRequestError(
      body.code ?? `HTTP_${response.status}`,
      body.message ?? '请求未成功。',
      body.request_id ?? '',
      body.details ?? {},
    )
  }
  return payload as T
}

function queryString(params: Record<string, string | undefined>): string {
  const query = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) if (value) query.set(key, value)
  return query.toString() ? `?${query.toString()}` : ''
}

// CSV 不是 JSON，走同一条鉴权但单独解析；失败时后端仍按契约返回错误信封。
async function downloadCsv(path: string): Promise<{ fileName: string; text: string }> {
  const headers = new Headers({ Accept: 'text/csv' })
  const token = readToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)

  let response: Response
  try {
    response = await fetch(`${BASE}${path}`, { headers })
  } catch {
    throw new ApiRequestError('NETWORK_UNAVAILABLE', '连不上后端，请确认 API 已在 8000 端口启动。', '')
  }

  const text = await response.text()
  if (!response.ok) {
    let body: Partial<ApiErrorBody> = {}
    try {
      body = JSON.parse(text) as Partial<ApiErrorBody>
    } catch {
      /* 非 JSON 的错误体只保留 HTTP 状态码 */
    }
    throw new ApiRequestError(
      body.code ?? `HTTP_${response.status}`,
      body.message ?? '请求未成功。',
      body.request_id ?? '',
      body.details ?? {},
    )
  }
  const match = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')
  return { fileName: match?.[1] ?? 'export.csv', text }
}

export const api = {
  demoAccounts: () => request<DemoAccount[]>('/auth/demo-accounts'),
  login: async (loginName: string, password: string) => {
    const session = await request<AuthSession>('/auth/mock-login', {
      method: 'POST',
      body: JSON.stringify({ login_name: loginName, password }),
    })
    writeToken(session.token)
    return session
  },
  me: () => request<SessionContext>('/me'),
  switchRole: async (role: Role) => {
    const session = await request<AuthSession>('/auth/role-switch', {
      method: 'POST',
      body: JSON.stringify({ role }),
    })
    writeToken(session.token)
    return session
  },
  logout: async () => {
    const result = await request<{ status: string }>('/auth/logout', { method: 'POST' })
    writeToken(null)
    return result
  },
  allowedActions: () => request<AllowedActions>('/authz/actions'),
  reservations: (serviceDate?: string) =>
    request<ListResult<Reservation>>(
      `/reservations${serviceDate ? `?service_date=${serviceDate}` : ''}`,
    ),
  tonightReservation: () => request<Reservation | null>('/reservations/tonight'),
  createReservation: (body: { planned_return_at: string; reason?: string }) =>
    request<Reservation>('/reservations', { method: 'POST', body: JSON.stringify(body) }),
  updateReservation: (
    id: string,
    body: { expected_version: number; planned_return_at?: string; reason?: string },
  ) =>
    request<Reservation>(`/reservations/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  cancelReservation: (id: string, expectedVersion: number) =>
    request<Reservation>(`/reservations/${id}/cancel`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  restoreReservation: (id: string, expectedVersion: number) =>
    request<Reservation>(`/reservations/${id}/restore`, {
      method: 'POST',
      body: JSON.stringify({ expected_version: expectedVersion }),
    }),
  reservationRevisions: (id: string) =>
    request<ListResult<ReservationRevision>>(`/reservations/${id}/revisions`),
  dailyReport: (serviceDate?: string) =>
    request<DailyReport>(`/reports/daily${serviceDate ? `?service_date=${serviceDate}` : ''}`),
  weeklyReport: (serviceDate?: string) =>
    request<WeeklyReport>(`/reports/weekly${serviceDate ? `?service_date=${serviceDate}` : ''}`),
  staffAccounts: () => request<ListResult<StaffAccount>>('/staff-accounts'),
  createStaffAccount: (body: {
    login_name: string
    display_name: string
    building_ids: string[]
  }) =>
    request<StaffAccountSecret>('/staff-accounts', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  updateStaffAccount: (
    id: string,
    body: { display_name?: string; building_ids?: string[] },
  ) =>
    request<StaffAccount>(`/staff-accounts/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(body),
    }),
  resetStaffPassword: (id: string) =>
    request<StaffAccountSecret>(`/staff-accounts/${id}/reset-password`, { method: 'POST' }),
  disableStaffAccount: (id: string) =>
    request<StaffAccount>(`/staff-accounts/${id}/disable`, { method: 'POST' }),
  buildingTonight: (buildingId: string) =>
    request<BuildingTonight>(`/buildings/${buildingId}/tonight`),
  inbox: (unreadOnly = false) =>
    request<ListResult<Notification>>(
      `/notifications${unreadOnly ? '?unread_only=true' : ''}`,
    ),
  markNotificationRead: (id: string) =>
    request<Notification>(`/notifications/${id}/read`, { method: 'POST' }),
  dispatchNotifications: (body: {
    template: NotificationTemplate
    recipient_user_ids: string[]
    service_date?: string
    student_ids?: string[]
    deliver_now?: boolean
  }) =>
    request<NotificationDispatchResult>('/notification-dispatch', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  notificationJobs: () => request<ListResult<NotificationJob>>('/notification-jobs'),
  studentContact: (studentId: string) =>
    request<StudentContact>(`/directory/students/${studentId}/contact`),
  buildingResidents: (buildingId: string, query?: string) => {
    const suffix = query ? `?q=${encodeURIComponent(query)}` : ''
    return request<ResidentList>(`/directory/buildings/${buildingId}/residents${suffix}`)
  },
  dutyAssignments: () => request<ListResult<Record<string, unknown>>>('/duty-assignments'),
  returnRecords: (params: { serviceDate?: string; buildingId?: string } = {}) => {
    const query = new URLSearchParams()
    if (params.serviceDate) query.set('service_date', params.serviceDate)
    if (params.buildingId) query.set('building_id', params.buildingId)
    const suffix = query.toString() ? `?${query.toString()}` : ''
    return request<ReturnRecords>(`/return-records${suffix}`)
  },
  manualReturn: (payload: Record<string, unknown>) =>
    request<ReturnRecord>('/return-records/manual', {
      method: 'POST',
      body: JSON.stringify(payload),
    }),
  // 门口终端用设备身份而非学生会话：凭据走请求头，码值走请求体。
  deviceScan: (deviceId: string, deviceToken: string, code: string, result = 'SUCCEEDED', reconcileResult = 'SUCCEEDED') =>
    request<ScanResult>('/device/scan', {
      method: 'POST',
      headers: { 'x-device-id': deviceId, 'x-device-token': deviceToken },
      body: JSON.stringify({ code, result, reconcile_result: reconcileResult }),
    }),
  verificationState: (id: string) => request<Record<string, unknown>>(`/verification-sessions/${id}`),
  profile: () => request<components['schemas']['UserProfile']>('/me/profile'),
  residence: () => request<Record<string, unknown>>('/me/residence'),
  managedUsers: (params: Record<string, string> = {}) => request<components['schemas']['ManagedUserList']>(`/management/users?${new URLSearchParams(params)}`),
  grants: () => request<components['schemas']['RoleGrantList']>('/management/grants'),
  grant: (body: components['schemas']['RoleGrantRequest']) => request<components['schemas']['RoleGrant']>('/management/grants', { method: 'POST', body: JSON.stringify(body) }),
  revokeGrant: (id: string) => request<Record<string, unknown>>(`/management/grants/${id}`, { method: 'DELETE' }),
  audit: () => request<ListResult<Record<string, unknown>>>('/management/audit'),
  directoryStudents: (params: Record<string, string> = {}) => request<components['schemas']['StudentDirectoryList']>(`/directory/students?${new URLSearchParams(params)}`),
  directoryOptions: () => request<Record<string, unknown>>('/directory/options'),
  verify: (body: components['schemas']['VerificationRequest']) => request<components['schemas']['VerificationResult']>('/verification-sessions', { method: 'POST', body: JSON.stringify(body) }),
  ownReturnRecords: (params: {serviceDate?: string} = {}) => request<ReturnRecords>(`/return-records/self${params.serviceDate ? `?service_date=${params.serviceDate}` : ''}`),
  returnEvidence: (id: string) => request<ListResult<Record<string, unknown>>>(`/return-records/${id}/evidence`),
  corrections: (id: string) => request<ListResult<Record<string, unknown>>>(`/return-records/${id}/corrections`),
  correctReturn: (id: string, body: components['schemas']['ReturnCorrectionRequest']) => request<Record<string, unknown>>(`/return-records/${id}/corrections`, { method: 'POST', body: JSON.stringify(body) }),
  subscription: () => request<components['schemas']['ReportSubscription']>('/reports/subscriptions'),
  saveSubscription: (body: components['schemas']['ReportSubscription']) => request<components['schemas']['ReportSubscription']>('/reports/subscriptions', { method: 'PUT', body: JSON.stringify(body) }),
  riskList: (status = '') => request<components['schemas']['RiskEventList']>(`/risk-events${status ? `?status=${status}` : ''}`),
  actRisk: (id: string, action: 'ack' | 'resolve', note: string) => request<components['schemas']['RiskEvent']>(`/risk-events/${id}/${action}`, {method: 'POST', body: JSON.stringify({note})}),
  riskPolicy: () => request<components['schemas']['RiskPolicy']>('/risk-policy'),
  saveRiskPolicy: (body: components['schemas']['RiskPolicy']) => request<components['schemas']['RiskPolicy']>('/risk-policy', {method: 'PUT', body: JSON.stringify(body)}),
  duties: () => request<components['schemas']['DutyAssignmentList']>('/duty-assignments'),
  assignDuty: (body: components['schemas']['DutyAssignmentRequest']) => request<Record<string, unknown>>('/duty-assignments', {method: 'POST', body: JSON.stringify(body)}),
  revokeDuty: (id: string) => request<Record<string, unknown>>(`/duty-assignments/${id}`, {method: 'DELETE'}),
  riskEvents: () => request<ListResult<Record<string, unknown>>>('/risk-events'),
  statistics: (params: Record<string, string | undefined> = {}) =>
    request<StatisticsResult>(`/statistics${queryString(params)}`),
  statisticsFilters: () => request<StatisticsFilters>('/statistics/filters'),
  createExport: (params: Record<string, string | undefined>, idempotencyKey?: string) =>
    request<ExportJob>('/exports', {
      method: 'POST',
      body: JSON.stringify({ report: 'STATISTICS', params, idempotency_key: idempotencyKey }),
    }),
  myExports: () => request<ListResult<ExportJob>>('/exports'),
  exportJob: (exportId: string) => request<ExportJob>(`/exports/${exportId}`),
  downloadExport: (exportId: string) => downloadCsv(`/exports/${exportId}/download`),
  clock: () => request<ClockState>('/demo/clock'),
  setClock: (offsetMinutes: number) =>
    request<ClockState>('/demo/clock', {
      method: 'POST',
      body: JSON.stringify({ offset_minutes: offsetMinutes }),
    }),
}
