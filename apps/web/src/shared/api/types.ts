// 契约类型从 contracts/openapi.yaml 生成（npm run generate:api），不要手改。
// 这里只做稳定命名导出；改契约后先重新生成再改实现。
import type { components } from './schema'

export type Role = components['schemas']['Role']
export type Scope = components['schemas']['Scope']
export type SessionContext = components['schemas']['SessionContext']
export type AuthSession = components['schemas']['AuthSession']
export type DemoAccount = components['schemas']['DemoAccount']
export type AllowedActions = components['schemas']['AllowedActions']
export type ScopeCheck = components['schemas']['ScopeCheck']
export type ClockState = components['schemas']['ClockState']
export type Reservation = components['schemas']['Reservation']
export type ReservationRevision = components['schemas']['ReservationRevision']
export type ApiErrorBody = components['schemas']['Error']

export interface ListResult<T> {
  items: T[]
  next_cursor: string | null
}
