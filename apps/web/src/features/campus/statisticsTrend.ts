// 只解释服务端返回的完整逐夜序列，不在前端决定业务夜边界。
export function recentTrend(days: Array<{ service_date: string; nights: number }>, range?: { date_from: string; date_to: string }) {
  let ordered = [...days].sort((a, b) => a.service_date.localeCompare(b.service_date)).slice(-14)
  if (range) {
    const end = Date.parse(`${range.date_to}T00:00:00Z`)
    const start = Date.parse(`${range.date_from}T00:00:00Z`)
    if (!Number.isFinite(end) || !Number.isFinite(start) || end - start < 13 * 86400000) return null
    const counts = new Map(days.map(day => [day.service_date, day.nights]))
    // 当前接口只列有事实的夜；范围已由服务端确认，缺行表示该夜正式返宿为零。
    ordered = Array.from({ length: 14 }, (_, i) => {
      const night = new Date(end - (13 - i) * 86400000).toISOString().slice(0, 10)
      return { service_date: night, nights: counts.get(night) ?? 0 }
    })
  }
  if (ordered.length < 14) return null
  for (let i = 1; i < ordered.length; i++) {
    if (Date.parse(`${ordered[i]!.service_date}T00:00:00Z`) - Date.parse(`${ordered[i - 1]!.service_date}T00:00:00Z`) !== 86400000) return null
  }
  const prior = ordered.slice(0, 7).reduce((sum, day) => sum + day.nights, 0)
  const recent = ordered.slice(7).reduce((sum, day) => sum + day.nights, 0)
  return { prior, recent, delta: recent - prior, percent: prior ? Math.round((recent - prior) / prior * 100) : null }
}
