"""Defensive fixture: ``vera.init(**config)`` gets the agent_type TODO.

The codemod cannot inspect a ``**kwargs`` dict to know whether
``agent_type=`` will be present at runtime, so it conservatively adds
the TODO comment. If you're sure your config dict carries
``agent_type``, delete the TODO line — the codemod won't re-add it
on a second run.
"""

import vera

config = {"api_key": "k"}
vera.init(**config)
