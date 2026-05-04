from src.logic.admin.broadcast_service import safe_send_interval_seconds


def test_safe_send_interval_respects_floor_and_ceiling():
    slow = safe_send_interval_seconds(5)
    fast_cap = safe_send_interval_seconds(100)

    assert slow == max(1.0 / min(5.0, 30.0), 1.0 / 35.0)
    assert slow >= 1.0 / 30.0
    assert fast_cap >= 1.0 / 35.0
