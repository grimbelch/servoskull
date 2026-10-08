"""Walking a player through Battlefield Set-Up.

The stages feed each other -- the Crew table decides how crews are picked and
whether anyone gets Reinforcements, the Deployment table decides the zones --
so what is pinned here is that the walkthrough carries the earlier rolls
forward and reads out only the rule the scenario actually called for.
"""

import pytest

from games.necromunda import setup


# ── reading the Crew table's result ───────────────────────────────────────────

@pytest.mark.parametrize("result,method,value", [
    ("Escalating Engagement: Both gangs use the Hybrid (3+D3) method to "
     "determine their starting crew.", "hybrid", "(3+D3)"),
    ("Hold Nothing Back!: Both gangs use the Custom (10) method to determine "
     "their starting crew.", "custom", "(10)"),
    ("Scouting Force: Both gangs use the Hybrid (D3+5) method.", "hybrid", "(D3+5)"),
])
def test_the_crew_table_names_the_selection_method(result, method, value):
    """Only one of the three methods is read out: the one that was rolled."""
    match = setup._METHOD.search(result)
    assert match is not None
    assert match.group(1).lower() == method
    assert match.group(2) == value
    assert setup._METHODS[method]


@pytest.mark.parametrize("result,expected", [
    ("Both gangs use the Reinforcements (5) rule with D3 Reinforcements "
     "arriving each round starting from the first.", "5"),
    ("The defender uses the Reinforcements (7) rule.", "7"),
    ("Patrol: Both gangs use the Hybrid (3+4) method.", None),
])
def test_reinforcements_are_only_offered_when_the_table_grants_them(result, expected):
    match = setup._REINFORCEMENTS.search(result)
    assert (match.group(1) if match else None) == expected


def test_a_results_headline_is_the_name_before_the_colon():
    assert setup._headline(
        "Face Off: The winner of a roll-off chooses a battlefield edge") == "Face Off"
    assert setup._headline("Stand Off: anything at all") == "Stand Off"


# ── the order of the stages ───────────────────────────────────────────────────

def test_pitch_black_is_rolled_after_the_terrain_and_before_deployment():
    """The book is explicit, and the order is easy to get wrong.

    "roll on the table below, after setting up the battlefield but before
    choosing deployment zones or deploying any models". Rolled at the end, the
    battlefield has already been built under the wrong visibility.
    """
    order = [stage["key"] for stage in setup.STAGES]
    assert order.index("battlefield") < order.index("pitch_black")
    assert order.index("pitch_black") < order.index("deployment")


def test_the_scenario_is_generated_before_anything_it_decides():
    order = [stage["key"] for stage in setup.STAGES]
    assert order[0] == "scenario"
    for later in ("crew", "reinforcements", "deployment"):
        assert order.index("scenario") < order.index(later)


def test_the_side_job_is_the_only_table_rolled_by_each_player():
    """"each player rolls a D6" -- the two gangs chase different payouts."""
    per_player = {name for name, _who, each in setup._SCENARIO_TABLES if each}
    assert per_player == {"SIDE JOB TABLE"}
    who = {name: w for name, w, _each in setup._SCENARIO_TABLES}
    assert who["CREW TABLE"] == "the challenged player"
    assert who["DEPLOYMENT TABLE"] == "the challenger"
    assert who["OBJECTIVE TABLE"] == "the challenger"


# ── holding the player's place ────────────────────────────────────────────────

@pytest.fixture
def state_file(tmp_path, monkeypatch):
    monkeypatch.setattr(setup, "_state_path", lambda: tmp_path / "setup.json")
    yield


def test_nothing_in_progress_is_said_plainly(state_file):
    assert "No set-up is in progress" in setup.advance()
    assert "No set-up is in progress" in setup.current()
    assert "No set-up is in progress" in setup.status()
    assert "No set-up is in progress" in setup.abandon()


def test_a_stage_can_be_gone_back_over(state_file):
    setup._save({"stage": 4, "rolls": {}, "attacker": "", "defender": "",
                 "visibility": "", "done": []})
    setup.go_to("battlefield")
    assert setup._load()["stage"] == setup._INDEX["battlefield"]
    # A name the book does not use is refused rather than guessed at.
    assert "no set-up stage called" in setup.go_to("teleportarium").lower()


def test_abandoning_clears_the_place(state_file):
    setup._save({"stage": 2, "rolls": {}, "attacker": "", "defender": "",
                 "visibility": "", "done": []})
    assert "discarded" in setup.abandon()
    assert setup._load() is None
