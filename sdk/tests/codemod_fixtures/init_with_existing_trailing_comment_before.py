"""Fixture 13: vera.init() with a pre-existing trailing comment.

The user's own ``# TODO: rotate this key in Q3`` comment must survive
the codemod. The codemod TODO is emitted on a NEW line ABOVE the
``vera.init()`` call instead of clobbering the trailing comment.
"""

import vera

vera.init(api_key="k")  # TODO: rotate this key in Q3
