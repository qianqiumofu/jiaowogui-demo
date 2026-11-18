"""申请弹窗的正文（A 主责）：服务端渲染，客户端只显示结果。

三条措辞边界：
- R16：只陈述规则事实并说明阈值是演示配置，正式值待学校确认。
- R15：不出现催办、超时或处置口径。
- R06、R07：明说本夜预约照常自动通过、改期不限次数，避免学生把提示读成审批意见。
"""

from __future__ import annotations

from app.modules.risk.rules import CONSECUTIVE, Evaluation

NOTICE_TITLE = "本夜预约已通过，另有一条统计提示"
CALIBER_NOTE = "统计口径是预约晚归的业务夜数，实际是否晚归以门禁通行记录为准。"
DEMO_NOTE = "这条提示的阈值来自演示配置，不是校规，正式取值待学校确认。"
NO_EFFECT_NOTE = "本夜预约照常自动通过，改期不限次数。"


def _nights_phrase(evaluation: Evaluation) -> str:
    if not evaluation.nights:
        return ""
    joined = "、".join(day.isoformat() for day in evaluation.nights)
    return f"（{joined}）"


def render_notice(evaluation: Evaluation) -> tuple[str, str]:
    if evaluation.crossed_by == CONSECUTIVE:
        head = (
            f"你已经连续 {evaluation.consecutive_nights} 个业务夜预约晚归"
            f"{_nights_phrase(evaluation)}。"
        )
    else:
        head = (
            f"最近 {evaluation.window_nights} 个业务夜里你已第 {evaluation.times} 次预约晚归"
            f"{_nights_phrase(evaluation)}，其中连续 {evaluation.consecutive_nights} 夜。"
        )
    return NOTICE_TITLE, " ".join((head, CALIBER_NOTE, DEMO_NOTE, NO_EFFECT_NOTE))
