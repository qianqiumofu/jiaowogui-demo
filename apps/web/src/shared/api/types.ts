// 契约类型从 contracts/openapi.yaml 生成（npm run generate:api），不要手改。
// 这里只做稳定命名导出；改契约后先重新生成再改实现。
import type { components } from './schema'

export type Role = components['schemas']['Role']
export type AccountSource = components['schemas']['AccountSource']
export type Scope = components['schemas']['Scope']
export type SessionContext = components['schemas']['SessionContext']
export type AuthSession = components['schemas']['AuthSession']
export type DemoAccount = components['schemas']['DemoAccount']
export type AllowedActions = components['schemas']['AllowedActions']
export type ScopeCheck = components['schemas']['ScopeCheck']
export type ClockState = components['schemas']['ClockState']
export type Reservation = components['schemas']['Reservation']
export type RiskNotice = components['schemas']['RiskNotice']
export type ReservationRevision = components['schemas']['ReservationRevision']
export type ReservationVerification = components['schemas']['ReservationVerification']
export type StaffAccount = components['schemas']['StaffAccount']
export type StaffAccountSecret = components['schemas']['StaffAccountSecret']
export type Notification = components['schemas']['Notification']
export type NotificationTemplate = components['schemas']['NotificationTemplate']
export type NotificationChannel = components['schemas']['NotificationChannel']
export type NotificationStatus = components['schemas']['NotificationStatus']
export type NotificationJob = components['schemas']['NotificationJob']
export type NotificationDispatchResult = components['schemas']['NotificationDispatchResult']
export type DailyReport = components['schemas']['DailyReport']
export type WeeklyReport = components['schemas']['WeeklyReport']
export type ReportItem = components['schemas']['ReportItem']
export type ReportNight = components['schemas']['ReportNight']
export type ReportTotals = components['schemas']['ReportTotals']
export type ApiErrorBody = components['schemas']['Error']

export interface ListResult<T> {
  items: T[]
  next_cursor: string | null
}
