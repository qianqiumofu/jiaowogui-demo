"""风险规则引擎的纯计算边界（M4 A 侧第一块）。不需要数据库。

锁住四件事：
- 阈值与版本只从配置读，改配置就改判定结果（未确认取值不许写死在分支里）。
- 统计窗口含当夜、下界为 `window_nights-1` 天前，端点包含。
- 两者同时越界时 triggered_by 取 TIMES；都不越界时 first_crossing 为假。
- 弹窗时机 first_crossing＝「去掉当夜后不再越界」，一晚最多一次。
"""

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.modules.risk import rules

REPO_ROOT = Path(__file__).resolve().parents[3]
TONIGHT = date(2026, 11, 18)


def late(*offsets: int) -> list[date]:
    """按「离当夜几个业务夜」构造夜晚，0 即当夜。"""
    return [TONIGHT - timedelta(days=offset) for offset in offsets]


@pytest.fixture()
def default_rules() -> rules.RuleSet:
    get_settings.cache_clear()
    return rules.current_rule_set()


def test_rule_set_defaults_match_config(default_rules: rules.RuleSet) -> None:
    settings = get_settings()
    assert default_rules == rules.RuleSet(
        version=settings.risk_rule_version,
        window_nights=7,
        times_threshold=3,
        consecutive_threshold=3,
    )


def test_thresholds_are_read_from_config(default_rules: rules.RuleSet, monkeypatch) -> None:
    """把次数阈值抬到 4 后同样 3 夜不再越界：证明取值没写死在判定里。"""
    assert rules.evaluate(late(6, 3, 0), tonight=TONIGHT, rules=default_rules).crossed_by == "TIMES"

    monkeypatch.setenv("RISK_TIMES_THRESHOLD", "4")
    monkeypatch.setenv("RISK_CONSECUTIVE_THRESHOLD", "9")
    get_settings.cache_clear()
    try:
        stricter = rules.current_rule_set()
        evaluation = rules.evaluate(late(6, 3, 0), tonight=TONIGHT, rules=stricter)
        assert evaluation.crossed is False and evaluation.first_crossing is False
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()
    assert rules.current_rule_set().times_threshold == 3


def test_window_covers_lower_bound_and_drops_older_nights(default_rules: rules.RuleSet) -> None:
    # 当夜-6 是 7 夜窗口的下界，算进来；当夜-7 在窗口外，不能凑数。
    evaluation = rules.evaluate(late(7, 6, 3, 0), tonight=TONIGHT, rules=default_rules)
    assert evaluation.times == 3
    assert evaluation.nights == tuple(sorted(late(6, 3, 0)))
    assert (TONIGHT - timedelta(days=6)) in evaluation.nights


def test_consecutive_only_crossing_is_labelled(default_rules: rules.RuleSet, monkeypatch) -> None:
    """连续口径单独越界时 triggered_by 取 CONSECUTIVE（把次数阈值抬到够不到）。"""
    monkeypatch.setenv("RISK_TIMES_THRESHOLD", "9")
    get_settings.cache_clear()
    try:
        evaluation = rules.evaluate(late(2, 1, 0), tonight=TONIGHT, rules=rules.current_rule_set())
        assert evaluation.crossed_by == "CONSECUTIVE" and evaluation.consecutive_nights == 3
    finally:
        get_settings.cache_clear()


def test_both_crossed_reports_times_first(default_rules: rules.RuleSet) -> None:
    evaluation = rules.evaluate(late(2, 1, 0), tonight=TONIGHT, rules=default_rules)
    assert evaluation.times == 3 and evaluation.consecutive_nights == 3
    assert evaluation.crossed_by == "TIMES"


def test_first_crossing_only_when_tonight_matters(default_rules: rules.RuleSet) -> None:
    third = rules.evaluate(late(6, 3, 0), tonight=TONIGHT, rules=default_rules)
    assert third.first_crossing is True

    # 当夜之前就已越界（去掉当夜仍有 3 夜）：同一夜不再重复弹窗。
    fourth = rules.evaluate(late(5, 3, 1, 0), tonight=TONIGHT, rules=default_rules)
    assert fourth.crossed_by == "TIMES" and fourth.first_crossing is False

    # 未越界谈不上首次越界。
    second = rules.evaluate(late(3, 0), tonight=TONIGHT, rules=default_rules)
    assert second.crossed is False and second.first_crossing is False


def test_repeated_nights_and_gaps(default_rules: rules.RuleSet) -> None:
    """同一夜重复只算一次；断一夜就把连续打断，但次数照样累加。"""
    evaluation = rules.evaluate(late(0, 0, 2, 4), tonight=TONIGHT, rules=default_rules)
    assert evaluation.times == 3 and evaluation.consecutive_nights == 1
    assert evaluation.crossed_by == "TIMES" and evaluation.first_crossing is True


def test_longest_run_edge_cases() -> None:
    assert rules.longest_run([]) == 0
    assert rules.longest_run(late(0)) == 1
    assert rules.longest_run(late(0, 1, 2, 4, 5)) == 3


def test_notice_text_states_caliber_and_demo_config(default_rules: rules.RuleSet) -> None:
    """弹窗正文必须自带口径与「演示配置」说明，且不含催办类口径（R15、R16、R17）。"""
    from app.modules.risk import templates

    evaluation = rules.evaluate(late(2, 1, 0), tonight=TONIGHT, rules=default_rules)
    title, message = templates.render_notice(evaluation)
    assert title == templates.NOTICE_TITLE
    for phrase in ("预约晚归", "门禁通行记录", "演示配置", "不是校规", "自动通过"):
        assert phrase in message
    forbidden = ("超时", "催办", "提醒学生", "已证明未归", "予以处置", "通知园区")
    assert not [word for word in forbidden if word in message], message
    # 日期是业务夜，正文按升序列出，客户端只原样显示。
    assert message.index(TONIGHT.isoformat()) > message.index((TONIGHT - timedelta(days=2)).isoformat())


def test_contract_example_matches_renderer() -> None:
    """样例里的 risk_notice 必须等于同一批事实的渲染结果，防止契约与实现各说一套。"""
    import json

    from app.modules.risk import templates

    sample_path = REPO_ROOT / "contracts" / "examples" / "reservation-create-risk-notice.json"
    notice = json.loads(sample_path.read_text(encoding="utf-8"))["risk_notice"]
    nights = [date.fromisoformat(day) for day in notice["nights"]]
    evaluation = rules.evaluate(
        nights,
        tonight=nights[-1],
        rules=rules.RuleSet(
            version=notice["rule_version"],
            window_nights=notice["window_nights"],
            times_threshold=3,
            consecutive_threshold=3,
        ),
    )
    assert evaluation.times == notice["times"]
    assert evaluation.consecutive_nights == notice["consecutive_nights"]
    assert evaluation.crossed_by == notice["triggered_by"]
    assert templates.render_notice(evaluation) == (notice["title"], notice["message"])
