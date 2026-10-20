from core import eyes


def test_parse_order_normalises():
    assert eyes.parse_order(" grbw ") == "GRBW"
    assert eyes.parse_order("GRB") == "GRB"


def test_parse_order_falls_back_to_grbw():
    assert eyes.parse_order("RGBX") == "GRBW"
    assert eyes.parse_order("") == "GRBW"


def test_pixel_bytes_grbw_keeps_white_dark():
    assert eyes.pixel_bytes((255, 10, 20), "GRBW") == bytes([10, 255, 20, 0])


def test_pixel_bytes_grb():
    assert eyes.pixel_bytes((255, 10, 20), "GRB") == bytes([10, 255, 20])


def test_pixel_bytes_carries_white():
    assert eyes.pixel_bytes((1, 2, 3, 4), "GRBW") == bytes([2, 1, 3, 4])


def test_activity_follows_main_loop_calls():
    eyes.wake()
    f = eyes.frame()
    assert f.activity == "" and f.now - f.wake_at < 1.0
    eyes.think()
    assert eyes.frame().activity == "thinking"
    eyes.set_amplitude(0.05)
    f = eyes.frame()
    assert f.activity == "speaking" and abs(f.amplitude - 0.4) < 1e-9
    eyes.off()
    assert eyes.frame().activity == ""


def test_confirming_runs_out():
    import time
    eyes.set_confirming(time.time() + 30)
    assert eyes.frame().confirming
    eyes.set_confirming(None)
    assert not eyes.frame().confirming
