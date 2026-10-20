import pytest

from core import notices


@pytest.fixture(autouse=True)
def fresh():
    notices.acknowledge_all()
    notices._clear_hooks.clear()
    notices.set_presence(lambda: None)
    yield
    notices.acknowledge_all()


def test_add_holds_once_and_keeps_its_age():
    notices.add(notices.PRINT_DONE, "done")
    first = notices.pending()[0].at
    notices.add(notices.PRINT_DONE, "done again")
    held = notices.pending()
    assert len(held) == 1 and held[0].at == first and held[0].text == "done again"


def test_delivered_clears_only_when_someone_is_there():
    notices.add(notices.PRINT_DONE, "done")
    notices.set_presence(lambda: False)
    assert not notices.delivered(notices.PRINT_DONE) and notices.has(notices.PRINT_DONE)
    notices.set_presence(lambda: None)          # no sensor: wait for acknowledgement
    assert not notices.delivered(notices.PRINT_DONE)
    notices.set_presence(lambda: True)
    assert notices.delivered(notices.PRINT_DONE) and not notices.has(notices.PRINT_DONE)


def test_clear_runs_hooks():
    calls = []
    notices.on_clear(notices.PRINT_ERROR, lambda: calls.append(1))
    notices.add(notices.PRINT_ERROR, "jam")
    assert notices.clear(notices.PRINT_ERROR) and calls == [1]
    assert not notices.clear(notices.PRINT_ERROR) and calls == [1]


def test_acknowledge_returns_what_was_missed():
    notices.add_missed("good morning")
    notices.add_missed("a hymn")
    notices.add(notices.PRINT_DONE, "done")
    held, missed = notices.acknowledge_all()
    assert {n.kind for n in held} == {notices.PRINT_DONE, notices.MISSED}
    assert missed == ["good morning", "a hymn"]
    assert notices.pending() == []
