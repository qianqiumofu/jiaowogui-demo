"""四类通知的正文模板（A 主责）。

措辞受三条规则约束：
- R12：23:30 只是汇总时点，不是申请截止；之后的改期与返宿会刷新名单。
- R15：未确认返宿是查询派生状态，正文不得出现催办、超时提醒或升级处置。
- R16：风险跟进提示只面向负责辅导员与当班宿管，且必须说明阈值是演示配置。

时间判定、收件人资格与取数都在 `service.py`；本模块只把已经算好的事实写成文字。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from app.core.clock import business_iso
from app.modules.identity.schemas import AccountSource, Person, Role

DAILY_CLOSING_EMAIL = "本邮件由系统自动生成，请勿回复。"
DAILY_CLOSING_INBOX = "本条为站内待办，无需回复。"
# R15 的固定口径说明：任何提到「未确认返宿」的正文都必须带上这一句。
UNCONFIRMED_NOTE = "未确认返宿只表示当晚没有匹配到通行记录，不代表已经证明未归，系统不据此提醒、催办或升级。"

STATUS_LABELS = {
    "ACTIVE": "未确认返宿",
    "FULFILLED": "已确认返宿",
    "CANCELLED": "已取消",
    "CLOSED": "业务夜已结束，未确认返宿",
}


@dataclass(frozen=True)
class ReservationRow:
    """一行预约事实；由 service 从预约领域服务取好后传入。"""

    student_id: str
    school_id: str
    display_name: str
    planned_return_at: datetime
    status: str

    @property
    def planned_label(self) -> str:
        return business_iso(self.planned_return_at)[11:16]

    @property
    def status_label(self) -> str:
        return STATUS_LABELS.get(self.status, self.status)

    def line(self, index: int) -> str:
        return (
            f"{index}. {self.school_id} {self.display_name}｜"
            f"计划返宿 {self.planned_label}｜{self.status_label}"
        )


@dataclass(frozen=True)
class NightCount:
    service_date: date
    total: int
    unconfirmed: int


@dataclass(frozen=True)
class RiskFacts:
    """单个学生的触发事实；阈值数值来自配置，不写死在措辞里。"""

    row: ReservationRow
    window_nights: int
    times: int
    consecutive: int
    nights: list[date] = field(default_factory=list)


@dataclass(frozen=True)
class RenderInput:
    template: str
    person: Person
    service_date: date
    rows: list[ReservationRow] = field(default_factory=list)
    nights: list[NightCount] = field(default_factory=list)
    risk: RiskFacts | None = None
    week_start: date | None = None
    demo_manual: bool = False


def greeting(person: Person) -> str:
    return f"{person.display_name.split('（')[0]}："


def closing(person: Person) -> str:
    """统一身份账户是邮件预览，工号账号只有站内待办（R18、R19）。"""
    return DAILY_CLOSING_INBOX if person.account_source is AccountSource.STAFF_LOCAL else DAILY_CLOSING_EMAIL


def demo_scope_note(person: Person) -> str:
    """演示投递的收件人是手选的，正式版按关系派生——措辞要贴合收件人自己的口径。"""
    roles = set(person.roles)
    if Role.COUNSELOR in roles:
        return "本条由园区在演示中手动投递：正式版按你负责的学生关系自动生成。"
    if Role.DORM_MANAGER in roles:
        return "本条由园区在演示中手动投递：正式版按你的固定管理楼栋与当日代班范围自动生成。"
    return "本条由园区在演示中手动投递：正式版按系统内有效的负责与值班关系自动生成。"


def _join(*blocks: list[str]) -> str:
    """块内单行相接，块之间空一行；空块直接丢掉，避免出现连续空行。"""
    return "\n\n".join("\n".join(block) for block in blocks if block)


def _body_head(person: Person, subject_line: str) -> list[str]:
    return [greeting(person), "", subject_line]


def _tail(item: RenderInput) -> list[str]:
    lines = []
    if item.demo_manual:
        lines += [demo_scope_note(item.person), ""]
    lines.append(closing(item.person))
    return lines


def _rows_block(rows: list[ReservationRow]) -> list[str]:
    if not rows:
        return ["今晚没有需要留门的晚归预约。"]
    return [row.line(index) for index, row in enumerate(rows, start=1)]


def render_night_roster(item: RenderInput) -> tuple[str, str]:
    buildings = "、".join(item.person.home_building_ids) or "当前授权范围"
    subject = f"今晚返宿名单 · {item.service_date.isoformat()} 业务夜 · {buildings}"
    head = _body_head(
        item.person,
        f"{item.service_date.isoformat()} 业务夜（06:00 至次日 06:00）23:30 汇总的晚归预约共 {len(item.rows)} 条。",
    )
    body = _join(
        head,
        _rows_block(item.rows),
        [
            "23:30 之后学生仍可改期，名单会随改期与实际返宿更新；23:30 不是申请截止时间。",
            "学生实际到达后，按门铃或刷卡记录照常登记即可。",
        ],
        _tail(item),
    )
    return subject, body


def render_daily_report(item: RenderInput) -> tuple[str, str]:
    subject = f"晚归日报 · {item.service_date.isoformat()} 业务夜"
    head = _body_head(
        item.person,
        f"{item.service_date.isoformat()} 业务夜共提交晚归预约 {len(item.rows)} 条。",
    )
    body = _join(
        head,
        _rows_block(item.rows),
        [UNCONFIRMED_NOTE, "需要跟进时，请在系统内查询该生近期记录。"],
        _tail(item),
    )
    return subject, body


def render_weekly_report(item: RenderInput) -> tuple[str, str]:
    week_start = item.week_start or item.service_date
    subject = f"晚归周报 · {week_start.isoformat()} 至 {item.service_date.isoformat()} 七个业务夜"
    total = sum(night.total for night in item.nights)
    unconfirmed = sum(night.unconfirmed for night in item.nights)
    head = _body_head(
        item.person,
        f"{week_start.isoformat()} 至 {item.service_date.isoformat()} 共提交晚归预约 {total} 条，"
        f"其中未确认返宿 {unconfirmed} 条。",
    )
    nights = [
        f"{night.service_date.isoformat()}｜预约 {night.total} 条｜未确认 {night.unconfirmed} 条"
        for night in item.nights
    ]
    body = _join(
        head,
        ["按业务夜："] if nights else ["这七个业务夜没有晚归预约。"],
        nights,
        [
            UNCONFIRMED_NOTE,
            "周报按你的订阅发送，与风险跟进提示互不影响。",
        ],
        _tail(item),
    )
    return subject, body


def render_risk_alert(item: RenderInput) -> tuple[str, str]:
    risk = item.risk
    if risk is None or risk.row is None:
        raise ValueError("风险跟进提示必须带触发事实")
    row = risk.row
    nights = "、".join(day.isoformat() for day in risk.nights) or row_student_day(row)
    subject = f"跟进提示 · {row.school_id} {row.display_name} 近 {risk.window_nights} 夜第 {risk.times} 次预约晚归"
    head = _body_head(
        item.person,
        f"学生 {row.school_id} {row.display_name} 在最近 {risk.window_nights} 个业务夜里第 {risk.times} 次预约晚归"
        f"（{nights}），其中连续 {risk.consecutive} 夜。",
    )
    body = _join(
        head,
        [
            "该提示依据演示配置的阈值生成，不是校规，正式阈值与周期待学校确认。",
            "统计口径是晚归预约次数；实际是否晚归以门禁通行记录为准。",
            UNCONFIRMED_NOTE,
            "园区不接收本提示；需要协同请由你与当班宿管线下沟通。",
        ],
        _tail(item),
    )
    return subject, body


def row_student_day(row: ReservationRow) -> str:
    return business_iso(row.planned_return_at)[:10]


RENDERERS = {
    "NIGHT_ROSTER": render_night_roster,
    "DAILY_REPORT": render_daily_report,
    "WEEKLY_REPORT": render_weekly_report,
    "RISK_ALERT": render_risk_alert,
}


def render(item: RenderInput) -> tuple[str, str]:
    renderer = RENDERERS.get(item.template)
    if renderer is None:
        raise ValueError(f"未知的通知模板：{item.template}")
    return renderer(item)
