import type {
  AllowedActions,
  ApiErrorBody,
  AuthSession,
  ClockState,
  DemoAccount,
  ListResult,
  Notification,
  NotificationDispatchResult,
  NotificationJob,
  NotificationTemplate,
  Reservation,
  ReservationRevision,
  Role,
  SessionContext,
  StaffAccount,
  StaffAccountSecret,
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
    request<ListResult<Record<string, unknown>>>(`/buildings/${buildingId}/tonight`),
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
  dutyAssignments: () => request<ListResult<Record<string, unknown>>>('/duty-assignments'),
  returnRecords: () => request<ListResult<Record<string, unknown>>>('/return-records'),
  riskEvents: () => request<ListResult<Record<string, unknown>>>('/risk-events'),
  clock: () => request<ClockState>('/demo/clock'),
  setClock: (offsetMinutes: number) =>
    request<ClockState>('/demo/clock', {
      method: 'POST',
      body: JSON.stringify({ offset_minutes: offsetMinutes }),
    }),
}
