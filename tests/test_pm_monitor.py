import pytest
from src.pm_monitor import detect_exit_triggers, _classify_event


def _make_event(etype: str, team: str, minute: int = 34) -> dict:
    return {"type": etype, "team": {"name": team}, "minute": minute}


def test_red_card_our_team_triggers_exit():
    events = [_make_event("YELLOW_RED_CARD", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result == "RED_CARD"


def test_red_card_opponent_no_exit():
    events = [_make_event("YELLOW_RED_CARD", "Argentina")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result is None


def test_goal_against_must_win_triggers():
    events = [_make_event("GOAL", "Argentina")]
    result = detect_exit_triggers(events, our_team="Switzerland", must_win=True, score=(0, 1))
    assert result == "GOAL_AGAINST_MUST_WIN"


def test_goal_for_triggers_lock_profit():
    events = [_make_event("GOAL", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland", score=(1, 0))
    assert result == "LOCK_PROFIT"


def test_no_event_no_trigger():
    events = [_make_event("YELLOW_CARD", "Switzerland")]
    result = detect_exit_triggers(events, our_team="Switzerland")
    assert result is None
