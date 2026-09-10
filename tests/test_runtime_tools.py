"""Runtime tools. `docs/0025`.

One test here matters more than the rest: no Observation subclass may define a
field named `content`. The base declares it as list[TextContent | ImageContent],
so a str shadow validates at construction and fails several components later,
during message assembly, with no reference to the field that caused it. It has
now bitten this project twice (docs/0018 §4, docs/0025).
"""
import pytest

pytest.importorskip("openhands.sdk", reason="SDK not installed")

from agentctl.runtime.tools import (
    BashObservation, ReadObservation, WriteObservation, TOOLS,
)

RESERVED = {"content"}


@pytest.mark.parametrize("obs", [BashObservation, ReadObservation, WriteObservation])
def test_no_observation_shadows_a_reserved_base_field(obs):
    own = set(obs.model_fields) - set(obs.__bases__[0].model_fields)
    clash = own & RESERVED
    assert not clash, (
        f"{obs.__name__} shadows {clash}; see the module docstring")


@pytest.mark.parametrize("obs,args", [
    (BashObservation, (0, "hello")),
    (ReadObservation, ("file body",)),
    (WriteObservation, ("written", 12)),
])
def test_the_model_actually_sees_the_output(obs, args):
    """The SDK reads `content` via `to_llm_content`, nothing else.

    An observation that stores its text in a custom field and exposes it via
    some other property renders as "[no text content]", and the agent concludes
    the tool returned nothing. That happened (docs/0025).
    """
    o = obs.make(*args)
    rendered = list(o.to_llm_content)
    assert rendered, f"{obs.__name__} renders empty -- the model sees nothing"
    text = "".join(getattr(b, "text", "") for b in rendered)
    assert text.strip(), f"{obs.__name__} produced no text"


def test_a_failing_command_is_marked_as_an_error():
    assert BashObservation.make(1, "boom").is_error
    assert not BashObservation.make(0, "fine").is_error


def test_the_three_tools_match_the_capability_matrix():
    """The tool names must be ones the classifier already knows."""
    from agentctl.kernel.classify import Classifier
    from agentctl.kernel.ledger.models import EffectClass, ToolCall

    clf = Classifier()
    assert clf.classify(ToolCall("t", "c", "t", "read_file", {})) is EffectClass.PURE_READ
    assert clf.classify(ToolCall("t", "c", "t", "write_file", {})) is EffectClass.IDEMPOTENT_WRITE
    assert clf.classify(ToolCall("t", "c", "t", "execute_bash",
                                 {"command": "rm -rf /"})) is EffectClass.DESTRUCTIVE
    assert set(TOOLS) == {"execute_bash", "read_file", "write_file"}
