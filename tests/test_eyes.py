from core import eyes


def test_parse_order_normalises():
    assert eyes.parse_order(" grbw ") == "GRBW"
    assert eyes.parse_order("GRB") == "GRB"


def test_parse_order_falls_back_to_grbw():
    assert eyes.parse_order("RGBX") == "GRBW"
    assert eyes.parse_order("") == "GRBW"
