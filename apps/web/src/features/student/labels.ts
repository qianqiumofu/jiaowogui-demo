// 学生端共用文案：状态与核验时段的说法只有一份，预约页和历史页保持一致。
export const STATUS_TEXT: Record<string, string> = {
  ACTIVE: '预约生效中',
  CANCELLED: '已取消',
  FULFILLED: '已返宿',
  CLOSED: '业务夜已结束',
}

export const SOURCE_TEXT: Record<string, string> = {
  CREATE: '创建',
  RESCHEDULE: '改期',
  CANCEL: '取消',
  RESTORE: '恢复',
  CLOSE: '系统关闭',
}

// 三态全部来自服务端 verification.state，前端不比较时刻。
export const VERIFICATION_TEXT: Record<string, string> = {
  NOT_OPEN: '还未到核验时段',
  OPEN: '现在可现场核验',
  ENDED: '核验时段已过',
}

export const VERIFICATION_HINT: Record<string, string> = {
  NOT_OPEN: '到点后由宿管或终端发起现场核验，核验通过才出码。',
  OPEN: '核验通过即签发二维码，有效期见下方秒数，过期须重新核验。',
  ENDED: '想让核验窗口跟着挪，改一次预约时间即可，不限次数。',
}
