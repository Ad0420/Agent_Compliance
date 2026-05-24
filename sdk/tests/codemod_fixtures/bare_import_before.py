"""Fixture 04: ``from vera import audit`` + bare @audit call."""

from vera import audit


@audit("chart_note_finalize")
def finalize(note):
    return note
