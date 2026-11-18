// 辅导员端只看「这一夜有没有被确认返宿」，与学生端的「预约生效中」不是同一个视角。
// 接口返回大写枚举，措辞只在这里有一份；后端正文口径见 reports/summary.py。
export const RETURN_STATE_TEXT: Record<string, string> = {
  ACTIVE: '未确认返宿',
  CLOSED: '夜已结束，未确认返宿',
  FULFILLED: '已确认返宿',
  CANCELLED: '已取消，不计入统计',
}
