import json
from pathlib import Path

from hush.decider_policy import DROP_BELOW, PAGE_AT, QUESTIONS, policy, render_state


def answers(wake, kind="outage", conf=0.9):
    return {
        "wake": {"type": "noul", "noul": wake},
        "kind": {"type": "choice", "choice": kind, "probabilities": {}, "confidence": conf},
    }


def test_low_wake_is_dropped_whatever_the_kind():
    assert policy(answers(0.3, "outage")).action == "drop"


def test_confident_noise_below_page_line_is_dropped():
    assert policy(answers(0.7, "noise", 0.8)).action == "drop"


def test_unsure_noise_is_reviewed_not_dropped():
    assert policy(answers(0.7, "noise", 0.2)).action == "review"


def test_high_wake_outage_pages():
    v = policy(answers(0.9, "outage"))
    assert v.action == "page" and v.wake == 0.9


def test_confident_noise_vetoes_a_page():
    assert policy(answers(0.9, "informational", 0.8)).action == "review"


def test_middle_band_is_reviewed():
    assert policy(answers(0.6, "degradation")).action == "review"


def test_thresholds_at_the_boundary():
    assert policy(answers(PAGE_AT, "outage")).action == "page"
    assert policy(answers(DROP_BELOW, "degradation")).action == "review"


def test_questions_are_well_formed():
    assert set(QUESTIONS) == {"wake", "kind"}
    assert QUESTIONS["wake"]["type"] == "noul" and set(QUESTIONS["wake"]["criteria"]) == {"true", "false"}
    assert QUESTIONS["kind"]["type"] == "choice" and len(QUESTIONS["kind"]["criteria"]) == 5


def test_render_state_reads_fixture_fields():
    alerts = json.loads(Path(__file__).parents[1].joinpath("fixtures/alerts.json").read_text())
    state = render_state(alerts[0])
    assert "status: firing" in state and "alert: Web service down" in state
    assert "immich.mol.la" in state and "severity label: critical" in state
