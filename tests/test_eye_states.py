from core import eye_states as es


def frame(**kw):
    kw.setdefault("now", 100.0)
    return es.Frame(**kw)


def test_idle_is_ember_on_both_eyes():
    left, right = es.resolve(frame())
    assert left == right == (*es.EMBER, 0)


def test_status_goes_to_its_own_eye():
    blue = es.Light(es.BT_BLUE, name="bt")
    green = es.Light(es.GREEN, name="done")
    left, right = es.resolve(frame(links=[blue], tasks=[green]))
    assert left == (*es.BT_BLUE, 0)
    assert right == (*es.GREEN, 0)


def test_tasks_take_turns():
    a, b = es.Light(es.GREEN), es.Light(es.AMBER)
    seen = {es.resolve(frame(now=t, tasks=[a, b]))[1] for t in (0.5, 0.5 + es.TASK_TURN_SECS)}
    assert seen == {(*es.GREEN, 0), (*es.AMBER, 0)}


def test_wake_flash_uses_white_then_ends():
    f = frame(now=10.0, wake_at=10.0, mood_rgb=(255, 0, 0))
    left, right = es.resolve(f)
    assert left == right and left[3] == 255 and left[0] == 255
    f.now = 10.0 + es.WAKE_FLASH_SECS
    assert es.resolve(f)[0] == (*es.EMBER, 0)


def test_thinking_ping_pongs_between_the_eyes():
    f = frame(now=0.0, activity="thinking", activity_since=0.0, mood_rgb=(200, 0, 0))
    left, right = es.resolve(f)
    assert left[0] > right[0]
    f.now = 0.8                               # half a swing later
    left, right = es.resolve(f)
    assert right[0] > left[0]


def test_speaking_follows_amplitude_and_beats_status():
    green = es.Light(es.GREEN)
    quiet = es.resolve(frame(activity="speaking", amplitude=0.2, mood_rgb=(250, 0, 0), tasks=[green]))
    loud = es.resolve(frame(activity="speaking", amplitude=1.0, mood_rgb=(250, 0, 0), tasks=[green]))
    assert quiet[1][0] == 50 and loud[1][0] == 250 and loud[1][1] == 0


def test_health_overrides_activity():
    hot = es.Light(es.ORANGE, name="hot")
    left, right = es.resolve(frame(activity="speaking", health=hot))
    assert left == right == (*es.ORANGE, 0)


def test_blip_wins_its_eye_until_it_ends():
    blip = es.Blip(es.Light(es.BT_BLUE), "left", until=101.0)
    left, right = es.resolve(frame(now=100.5, blips=[blip]))
    assert left == (*es.BT_BLUE, 0) and right == (*es.EMBER, 0)
    assert es.resolve(frame(now=101.5, blips=[blip]))[0] == (*es.EMBER, 0)


def test_calm_holds_blinkers_steady():
    blink = es.Light(es.WHITE, "blink", white=True, period=1.0)
    off_phase = 0.75
    assert es.resolve(frame(now=off_phase, tasks=[blink]))[1][3] == 0
    assert es.resolve(frame(now=off_phase, tasks=[blink], calm=True))[1][3] > 0


def test_scale_and_fade_dim_the_status_layers():
    full = es.resolve(frame())[0]
    dim = es.resolve(frame(scale=0.5))[0]
    dark = es.resolve(frame(fade=0.0))[0]
    assert dim[0] == full[0] // 2 and dark == (0, 0, 0, 0)


def test_patterns_stay_in_range():
    for p in es.PATTERNS:
        for i in range(200):
            assert 0.0 <= es.pattern_level(p, i * 0.037) <= 1.0
