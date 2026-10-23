from types import SimpleNamespace

from strands.interventions import Deny, Guide, Proceed

from hush.agent import PageGuard


class FakeGate:
    def __init__(self, faithful, warranted):
        self.answers = {"faithful": {"noul": faithful}, "warranted": {"noul": warranted}}
        self.states = []

    def ask(self, state, questions):
        self.states.append(state)
        return self.answers, 12.0


def event(tool="page_oncall", **args):
    return SimpleNamespace(tool_use={"name": tool, "input": args})


def test_other_tools_pass_without_a_decider_call():
    gate = FakeGate(0.1, 0.1)
    assert isinstance(PageGuard(gate).before_tool_call(event("file_morning_note")), Proceed)
    assert gate.states == []


def test_unwarranted_page_is_denied():
    g = PageGuard(FakeGate(faithful=0.9, warranted=0.2))
    assert isinstance(g.before_tool_call(event(title="t", message="m")), Deny)
    assert g.log[-1]["action"] == "deny"


def test_unfaithful_page_is_guided_then_let_through():
    g = PageGuard(FakeGate(faithful=0.2, warranted=0.9))
    assert isinstance(g.before_tool_call(event(title="t", message="m")), Guide)
    assert isinstance(g.before_tool_call(event(title="t", message="m")), Guide)
    assert isinstance(g.before_tool_call(event(title="t", message="m")), Proceed)  # no endless loop


def test_good_page_proceeds_and_state_holds_the_message():
    gate = FakeGate(0.95, 0.95)
    g = PageGuard(gate)
    g.alert_state = "alert: db down"
    assert isinstance(g.before_tool_call(event(title="DB down", message="postgres on db1 is down")), Proceed)
    assert "alert: db down" in gate.states[0] and "postgres on db1" in gate.states[0]
