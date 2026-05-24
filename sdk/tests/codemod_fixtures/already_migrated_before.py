"""Fixture 11: already on @vera.gate — codemod produces zero changes."""

import vera


@vera.gate("already_migrated")
def already_migrated(x):
    return x


vera.init(api_key="k", agent_type="scribe")
