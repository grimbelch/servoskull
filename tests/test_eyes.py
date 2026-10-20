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
