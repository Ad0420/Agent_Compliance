"""Fixture 13: vera.init() with a pre-existing trailing comment.

The user's own ``# TODO: rotate this key in Q3`` comment must survive
the codemod. The codemod TODO is emitted on a NEW line ABOVE the
``vera.init()`` call instead of clobbering the trailing comment.
"""

import vera

# TODO(audit-to-gate codemod): set agent_type= for new_agent_type_detected event (see MIGRATION.md)
vera.init(api_key="k")  # TODO: rotate this key in Q3
