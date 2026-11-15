import type {
  AllowedActions,
  ApiErrorBody,
  AuthSession,
  ClockState,
  DemoAccount,
  ListResult,
  Role,
  SessionContext,
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
  reservations: () => request<ListResult<Record<string, unknown>>>('/reservations'),
  buildingTonight: (buildingId: string) =>
    request<ListResult<Record<string, unknown>>>(`/buildings/${buildingId}/tonight`),
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
