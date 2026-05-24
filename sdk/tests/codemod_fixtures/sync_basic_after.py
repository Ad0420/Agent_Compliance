"""Fixture 01: most common case — @vera.audit on a sync fn."""

import vera


@vera.gate("process_data")
def process_data(x, y):
    return x + y
