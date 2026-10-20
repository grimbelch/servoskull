from core import eye_states as es
from core import eye_watch, notices, proximity
from core.eye_watch import Facts, compose


def names(lights):
    return [x.name for x in lights]


def test_idle_world_shows_nothing():
    links, tasks, health, scale, calm = compose(Facts())
    assert links == [] and tasks == [] and health is None and scale == 1.0 and not calm


def test_links_best_first():
    links = compose(Facts(offline=True, bt_connected=True, casting=True))[0]
    assert names(links) == ["offline", "bt speaker", "casting"]


def test_reconnecting_only_while_not_connected():
    assert names(compose(Facts(bt_reconnecting=True))[0]) == ["bt reconnecting"]
    assert names(compose(Facts(bt_reconnecting=True, bt_connected=True))[0]) == ["bt speaker"]


def test_tasks_reminder_first_then_notices_then_printing():
    tasks = compose(Facts(reminder_due=True, printer_state="RUNNING",
                          notices=[notices.PRINT_DONE, notices.MISSED]))[1]
    assert names(tasks) == ["reminder", "print done", "missed", "printing"]
    assert tasks[0].white


def test_paused_print_is_steady():
    t = compose(Facts(printer_state="PAUSE"))[1][0]
    assert t.name == "print paused" and t.pattern == "steady"


def test_overheating_is_health():
    assert compose(Facts(hot=True))[2].colour == es.ORANGE


def test_brightness_modifiers():
    assert compose(Facts(sleep=True, silent=True))[3:] == (0.25, True)
    assert compose(Facts(silent=True))[3:] == (0.5, False)
    assert compose(Facts(room_empty=True))[3:] == (0.5, False)


def test_movement_rule():
    assert proximity.moved(None, 120.0) and proximity.moved(120.0, None)
    assert not proximity.moved(120.0, 130.0)
    assert proximity.moved(120.0, 140.0)
    assert not proximity.moved(None, None)


def test_present_without_sensor_is_unknown(monkeypatch):
    monkeypatch.setattr(proximity, "_available", False)
    assert eye_watch.present() is None


def test_offline_waits_out_a_slow_boot():
    assert not eye_watch.offline_after(1, True, 999)
    assert not eye_watch.offline_after(2, False, 40)        # Wi-Fi still coming up
    assert eye_watch.offline_after(2, False, 200)           # never came up
    assert eye_watch.offline_after(2, True, 40)             # was up, now gone
