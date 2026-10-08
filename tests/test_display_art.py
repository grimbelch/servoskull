"""Choosing, fetching and reporting a piece of artwork.

Three faults this covers. The ranking fetched the largest file on offer in order
to throw away better than 99% of its pixels on a 240 px circle. The download had
no size cap at all. And it announced "successfully projected" whether or not the
panel had taken the image (run on the Pi: python -m pytest tests).
"""
import io

import pytest

from PIL import Image

brain = pytest.importorskip("core.brain")

FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <item><title>Tiny</title>
      <media:content url="http://x/tiny.jpg" width="80" height="60"/></item>
    <item><title>Just Right</title>
      <media:content url="http://x/mid.jpg" width="600" height="500"/></item>
    <item><title>Enormous</title>
      <media:content url="http://x/huge.jpg" width="7000" height="6000"/></item>
    <item><title>Unstated</title>
      <media:content url="http://x/unknown.jpg"/></item>
    <item><title>No media at all</title></item>
  </channel>
</rss>"""


# ── reading the feed ──────────────────────────────────────────────────────────

def test_the_feed_yields_every_item_that_has_an_image():
    got = brain._art_parse_feed(FEED)
    assert [c["title"] for c in got] == ["Tiny", "Just Right", "Enormous", "Unstated"]
    assert got[1]["min_side"] == 500
    assert got[3]["min_side"] == 0      # width/height absent


def test_a_feed_with_nothing_in_it_is_empty_not_an_error():
    assert brain._art_parse_feed(b"<rss><channel></channel></rss>") == []


# ── choosing among them ───────────────────────────────────────────────────────

def test_the_best_fit_beats_the_biggest():
    ranked = sorted(brain._art_parse_feed(FEED), key=brain._art_fitness)
    assert ranked[0]["title"] == "Just Right"


def test_too_small_to_fill_the_panel_ranks_below_anything_that_fits():
    ranked = [c["title"] for c in sorted(brain._art_parse_feed(FEED), key=brain._art_fitness)]
    assert ranked.index("Enormous") < ranked.index("Tiny")


def test_an_unstated_size_is_a_last_resort():
    ranked = [c["title"] for c in sorted(brain._art_parse_feed(FEED), key=brain._art_fitness)]
    assert ranked[-1] == "Unstated"


# ── fetching one ──────────────────────────────────────────────────────────────

class _FakeResponse:
    """Serves both shapes the art path uses: `.content` for the search feed, and
    `iter_content` under a context manager for the streamed image download."""

    def __init__(self, status=200, ctype="image/png", chunks=()):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        self._chunks = list(chunks)

    @property
    def content(self):
        return b"".join(self._chunks)

    def iter_content(self, n):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _png_bytes(size=(300, 300)):
    buf = io.BytesIO()
    Image.new("RGB", size, (1, 2, 3)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def http(monkeypatch):
    """Replace requests.get with a scripted response and report what it was asked."""
    requests = pytest.importorskip("requests")  # run on the Pi
    seen = {"calls": 0}

    def serve(response):
        def get(url, **kw):
            seen["calls"] += 1
            seen["url"] = url
            seen["headers"] = kw.get("headers") or {}
            seen["stream"] = kw.get("stream")
            return response() if callable(response) else response
        monkeypatch.setattr(requests, "get", get)
        return seen

    seen["serve"] = serve
    return seen


@pytest.fixture
def panel(monkeypatch):
    """A display that accepts or refuses an image, and remembers which."""
    from core import display
    monkeypatch.setattr(display, "start_image_retrieval", lambda: None)
    monkeypatch.setattr(display, "stop_image_retrieval", lambda: None)
    monkeypatch.setattr(brain, "_art_feed_cache", {})
    state = {"shown": []}

    def accepts(ok: bool):
        def show(img, duration=10.0):
            state["shown"].append(img)
            return ok
        monkeypatch.setattr(display, "display_pil_image", show)
    state["accepts"] = accepts
    return state


def test_an_image_under_the_cap_comes_back_decoded(http):
    http["serve"](_FakeResponse(chunks=[_png_bytes()]))
    img, why = brain._art_fetch_image("http://x/ok.png")
    assert why is None and img.size == (300, 300)


def test_the_download_stops_at_the_cap(http):
    # Previously unbounded: a 40-megapixel piece was buffered and decoded whole.
    http["serve"](_FakeResponse(chunks=[b"\x00" * (1024 * 1024)] * 16))
    img, why = brain._art_fetch_image("http://x/huge.png")
    assert img is None and "larger than" in why


def test_a_non_image_link_is_refused_without_decoding(http):
    http["serve"](_FakeResponse(ctype="text/html", chunks=[b"<html>"]))
    img, why = brain._art_fetch_image("http://x/page.html")
    assert img is None and "not an image" in why


def test_a_dead_link_reports_its_status(http):
    http["serve"](_FakeResponse(status=404))
    img, why = brain._art_fetch_image("http://x/gone.png")
    assert img is None and "404" in why


def test_the_request_identifies_itself_and_streams(http):
    http["serve"](_FakeResponse(chunks=[_png_bytes()]))
    brain._art_fetch_image("http://x/ok.png")
    assert "Omega-7" in http["headers"].get("User-Agent", "")
    assert http["stream"] is True


# ── saying what happened ──────────────────────────────────────────────────────

def test_a_panel_that_refuses_the_image_is_not_a_success(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image",
                        lambda url: (Image.new("RGB", (300, 300)), None))
    panel["accepts"](False)
    out = brain._execute_display_art("anything")
    assert "could not show it" in out and "Successfully projected" not in out


def test_a_shown_image_is_reported_as_shown(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image",
                        lambda url: (Image.new("RGB", (300, 300)), None))
    panel["accepts"](True)
    assert "Successfully projected" in brain._execute_display_art("anything")


def test_one_bad_link_does_not_end_the_attempt(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    tries = {"n": 0}

    def flaky(url):
        tries["n"] += 1
        if tries["n"] == 1:
            return None, "the image server answered 404"
        return Image.new("RGB", (300, 300)), None
    monkeypatch.setattr(brain, "_art_fetch_image", flaky)
    panel["accepts"](True)
    assert "Successfully projected" in brain._execute_display_art("anything")
    assert tries["n"] == 2


def test_every_candidate_failing_is_reported_with_the_reason(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image", lambda url: (None, "the image is larger than 6 MB"))
    panel["accepts"](True)
    out = brain._execute_display_art("anything")
    assert "Could not display artwork" in out and "larger than 6 MB" in out
    assert panel["shown"] == []


def test_the_feed_is_cached_so_asking_twice_downloads_once(http, panel, monkeypatch):
    http["serve"](lambda: _FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image",
                        lambda url: (Image.new("RGB", (300, 300)), None))
    panel["accepts"](True)
    brain._execute_display_art("space marine")
    brain._execute_display_art("space marine")
    assert http["calls"] == 1


def test_a_search_that_finds_nothing_says_so(http, panel):
    http["serve"](_FakeResponse(chunks=[b"<rss><channel></channel></rss>"]))
    assert "No artwork found" in brain._execute_display_art("qwertyuiop")
