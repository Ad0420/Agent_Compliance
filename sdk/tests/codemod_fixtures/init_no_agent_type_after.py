"""Fixture 08: vera.init() without agent_type= gets the TODO comment."""

import vera

vera.init(api_key="k")  # TODO(audit-to-gate codemod): set agent_type= for new_agent_type_detected event (see MIGRATION.md)
