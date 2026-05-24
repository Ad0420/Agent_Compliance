"""Fixture 12: comments, docstrings, and # noqa above the decorator survive."""

import vera


# Above-the-decorator block comment.
# Two lines.
@vera.gate("preserved")  # noqa: E501
def preserved(x):
    """A docstring that the codemod must not eat."""
    # an internal comment
    return x
