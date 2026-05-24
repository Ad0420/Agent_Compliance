"""Fixture 10: multiple decorators + init() + unrelated function."""

import vera
from vera import gate

vera.init(api_key="k")  # TODO(audit-to-gate codemod): set agent_type= for new_agent_type_detected event (see MIGRATION.md)


@vera.gate("a_one")
def a_one(x):
    return x


@gate(action_class="a_two")
def a_two(y):
    return y


def unrelated(z):
    """Should be untouched."""
    return z * 2


result_one = a_one(1)
result_two = a_two(2)
result_unrelated = unrelated(3)
