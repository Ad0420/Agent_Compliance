"""Fixture 10: multiple decorators + init() + unrelated function."""

import vera
from vera import audit

vera.init(api_key="k")


@vera.audit("a_one")
def a_one(x):
    return x


@audit(action_name="a_two")
def a_two(y):
    return y


def unrelated(z):
    """Should be untouched."""
    return z * 2


result_one = a_one(1)
result_two = a_two(2)
result_unrelated = unrelated(3)
