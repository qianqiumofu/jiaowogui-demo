import type {
  AllowedActions,
  ApiErrorBody,
  AuthSession,
  BuildingTonight,
  ClockState,
  DemoAccount,
  ExportJob,
  ListResult,
  ResidentList,
  ReturnRecord,
  Role,
  ReturnRecords,
  ScanResult,
  SessionContext,
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
  reservations: () => request<ListResult<Record<string, unknown>>>('/reservations'),
  buildingTonight: (buildingId: string) =>
    request<BuildingTonight>(`/buildings/${buildingId}/tonight`),
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
  deviceScan: (deviceId: string, deviceToken: string, code: string) =>
    request<ScanResult>('/device/scan', {
      method: 'POST',
      headers: { 'x-device-id': deviceId, 'x-device-token': deviceToken },
      body: JSON.stringify({ code }),
    }),
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
