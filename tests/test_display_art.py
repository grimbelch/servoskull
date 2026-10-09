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

RELEVANCE_FEED = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <item><title>Warhammer 40K - Ork Warboss</title>
      <media:content url="http://x/0.jpg" width="724" height="900"/></item>
    <item><title>Great Warlord Ghazghkull</title>
      <media:content url="http://x/1.jpg" width="800" height="800"/></item>
    <item><title>Ezekiel, Keeper of the Book of Salvation</title>
      <media:content url="http://x/2.jpg" width="670" height="670"/></item>
    <item><title>Ork Warboss 40k</title>
      <media:content url="http://x/3.jpg" width="600" height="600"/></item>
    <item><title>Assault on black reach Ork warboss</title>
      <media:content url="http://x/4.jpg" width="517" height="517"/></item>
    <item><title>Tiny Ork Warboss 40k Sketch</title>
      <media:content url="http://x/5.jpg" width="80" height="60"/></item>
  </channel>
</rss>"""


def test_the_words_that_matter_are_pulled_out_of_the_query():
    assert brain._art_terms("show me a picture of a 40k Ork Warboss") == ["40k", "ork", "warboss"]
    assert brain._art_terms("an Ork fighting a Space Marine") == ["ork", "space", "marine"]


def test_what_was_asked_for_comes_first():
    # "40k ork warboss" used to return "Ezekiel, Keeper of the Book of Salvation",
    # because the ranking sorted on pixel size and discarded the feed's relevance.
    ranked = brain._art_ranked(brain._art_parse_feed(RELEVANCE_FEED), "40k ork warboss")
    assert all("warboss" in c["title"].lower() for c in ranked[:3])


def test_a_title_about_something_else_is_demoted():
    ranked = [c["title"] for c in
              brain._art_ranked(brain._art_parse_feed(RELEVANCE_FEED), "40k ork warboss")]
    for off_topic in ("Ezekiel, Keeper of the Book of Salvation", "Great Warlord Ghazghkull"):
        assert ranked.index(off_topic) >= 3, off_topic


def test_being_the_wrong_subject_costs_more_than_being_small():
    ranked = [c["title"] for c in
              brain._art_ranked(brain._art_parse_feed(RELEVANCE_FEED), "40k ork warboss")]
    # A small picture of the right thing beats a large one of the wrong thing.
    assert ranked.index("Tiny Ork Warboss 40k Sketch") < ranked.index("Ezekiel, Keeper of the Book of Salvation")


def test_a_small_picture_still_ranks_below_a_usable_one_of_the_same_subject():
    ranked = [c["title"] for c in
              brain._art_ranked(brain._art_parse_feed(RELEVANCE_FEED), "40k ork warboss")]
    assert ranked.index("Ork Warboss 40k") < ranked.index("Tiny Ork Warboss 40k Sketch")


def test_asking_twice_varies_the_picture_but_not_the_subject():
    cands = brain._art_parse_feed(RELEVANCE_FEED)
    firsts = {brain._art_ranked(cands, "40k ork warboss")[0]["title"] for _ in range(30)}
    assert len(firsts) > 1                                   # it is not always the same one
    assert all("warboss" in t.lower() for t in firsts)       # and never the wrong subject


def test_a_query_nothing_matches_falls_back_to_the_feed_order():
    ranked = brain._art_ranked(brain._art_parse_feed(RELEVANCE_FEED), "zzzz qqqq")
    assert ranked[0]["title"] == "Warhammer 40K - Ork Warboss"   # the feed's own first


def test_ranking_an_empty_feed_is_empty():
    assert brain._art_ranked([], "anything") == []


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
        def show(img, duration=10.0, **kw):
            state["shown"].append(img)
            state["kwargs"] = kw
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
                        lambda url: (Image.new("RGB", (300, 300), (90, 90, 90)), None))
    panel["accepts"](False)
    out = brain._execute_display_art("anything")
    assert "could not show it" in out and "Successfully projected" not in out


def test_a_shown_image_is_reported_as_shown(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image",
                        lambda url: (Image.new("RGB", (300, 300), (90, 90, 90)), None))
    panel["accepts"](True)
    assert "Successfully projected" in brain._execute_display_art("anything")


def test_one_bad_link_does_not_end_the_attempt(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    tries = {"n": 0}

    def flaky(url):
        tries["n"] += 1
        if tries["n"] == 1:
            return None, "the image server answered 404"
        return Image.new("RGB", (300, 300), (90, 90, 90)), None
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
                        lambda url: (Image.new("RGB", (300, 300), (90, 90, 90)), None))
    panel["accepts"](True)
    brain._execute_display_art("space marine")
    brain._execute_display_art("space marine")
    assert http["calls"] == 1


def test_a_search_that_finds_nothing_says_so(http, panel):
    http["serve"](_FakeResponse(chunks=[b"<rss><channel></channel></rss>"]))
    assert "No artwork found" in brain._execute_display_art("qwertyuiop")


# ── pictures that read as a dead panel ────────────────────────────────────────

def _flat(value, size=(600, 600)):
    return Image.new("RGB", size, (value, value, value))


def test_a_near_white_picture_is_judged_blank():
    # What "an Ork fighting a Space Marine" actually showed: a candidate with 79%
    # of the shown crop brighter than 200, which reads as a white screen.
    assert brain._art_looks_blank(_flat(245)) is True


def test_a_near_black_picture_is_judged_blank():
    assert brain._art_looks_blank(_flat(5)) is True


def test_an_ordinary_picture_is_not():
    import numpy as np
    noise = (np.random.default_rng(0).integers(0, 256, (600, 600, 3))).astype("uint8")
    assert brain._art_looks_blank(Image.fromarray(noise)) is False


def test_it_judges_the_crop_the_panel_shows_not_the_whole_picture():
    # Busy at the edges, empty in the middle: the panel would show the empty part.
    img = Image.new("RGB", (1800, 600), (30, 90, 160))
    img.paste(_flat(250, (600, 600)), (600, 0))
    assert brain._art_looks_blank(img) is True


def test_a_blank_candidate_is_skipped_for_the_next_one(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    served = {"n": 0}

    def two_candidates(url):
        served["n"] += 1
        return (_flat(250) if served["n"] == 1 else _flat(90)), None
    monkeypatch.setattr(brain, "_art_fetch_image", two_candidates)
    panel["accepts"](True)
    assert "Successfully projected" in brain._execute_display_art("anything")
    assert served["n"] == 2
    # The one that reached the panel is the second, not the blank first.
    import numpy as np
    assert np.asarray(panel["shown"][0]).mean() < 200


def test_all_candidates_blank_says_so_rather_than_showing_one(http, panel, monkeypatch):
    http["serve"](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, "_art_fetch_image", lambda url: (_flat(250), None))
    panel["accepts"](True)
    out = brain._execute_display_art("anything")
    assert "nearly blank" in out
    assert panel["shown"] == []


def test_artwork_is_shown_as_a_reveal(http, panel, monkeypatch):
    # The whole picture first, then a zoom in: a centre crop alone keeps only
    # about half of the wide pieces this search returns.
    http['serve'](_FakeResponse(chunks=[FEED]))
    monkeypatch.setattr(brain, '_art_fetch_image',
                        lambda url: (Image.new('RGB', (1258, 635), (80, 90, 100)), None))
    panel['accepts'](True)
    assert 'Successfully projected' in brain._execute_display_art('anything')
    assert panel['kwargs'].get('reveal') is True


# ── the model skipping the tool entirely ──────────────────────────────────────

def test_a_picture_request_the_model_ignored_still_gets_fetched(monkeypatch):
    """The fallback, mirroring the one play_ambient_hymn already had.

    At 20:12:53 the model answered "Omega-7's sacred eye-display now renders
    blessed imagery upon the screen" and never called display_art.
    """
    called = {}
    monkeypatch.setattr(brain, "_execute_tool",
                        lambda name, i: called.setdefault(name, i) or "ok")
    from core import intents
    pic = intents.show_picture("show me a picture of a 40k ork", intents.Context())
    assert pic is not None
    # What the fallback would hand the tool.
    assert pic.args["subject"] == "40k ork"


def test_the_matcher_and_the_fallback_agree_on_the_subject():
    from core import intents
    for said, subject in (("Show me a picture of a 40k Ork.", "40k ork"),
                          ("display an image of a space marine", "space marine")):
        got = intents.show_picture(said.lower(), intents.Context())
        assert got.args["subject"] == subject
