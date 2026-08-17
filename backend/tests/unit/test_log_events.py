import logging
from app.services.sessions.log_events import log_event


def test_log_event_emits_structured_line(caplog):
    caplog.set_level(logging.INFO, logger="app.services.sessions.log_events")
    log_event("session_started", session="abc12345XYZ", user="u1", template="pm-research")
    records = [r for r in caplog.records if r.name == "app.services.sessions.log_events"]
    assert len(records) == 1
    msg = records[0].getMessage()
    assert msg == "会话已开始 session=abc12345 user=u1 template=pm-research"


def test_log_event_truncates_ids():
    # 截断不抛异常；只截 id 字符串，不动 field 渲染
    log_event("session_deleted", session="x" * 32, user="y" * 32, status="deleted")
    # 不作断言；只是确保长 id 不崩