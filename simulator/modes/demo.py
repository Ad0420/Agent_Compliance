"""Mode A — sales-grade scripted demo.

Runs a single mock customer's canonical workflow against Vera production
with real LLMs and prints a narrated trace suitable for screenshare.

Usage:
    python -m simulator.modes.demo scribemd
    python -m simulator.modes.demo scribemd --encounter pancreatitis
    python -m simulator.modes.demo scribemd --reject     # show blocked path
    python -m simulator.modes.demo scribemd --verify     # also run chain verify
"""

from __future__ import annotations

import argparse
import os
import sys
import textwrap
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from simulator.customers.scribemd.agents.note_drafter import NoteDrafterAgent
from simulator.customers.scribemd.agents.orders_extractor import OrdersExtractorAgent
from simulator.customers.scribemd.fixtures.encounters import ALL_ENCOUNTERS
from simulator.customers.scribemd.workflows.encounter import (
    EncounterResult,
    always_reject_callback,
    auto_approve_callback,
    run_encounter,
)
from simulator.shared.llm import get_provider
from simulator.shared.vera_setup import _load_env, _vera_url, get_client


console = Console()


# ── Narration ───────────────────────────────────────────────────────────────


def _hr(title: str | None = None) -> None:
    if title:
        console.rule(f"[bold cyan]{title}[/bold cyan]")
    else:
        console.rule()


def _step(label: str, color: str = "cyan") -> None:
    console.print(f"[bold {color}]▸[/bold {color}] {label}")


def _kv(key: str, value: str) -> None:
    console.print(f"    [dim]{key}[/dim]  {value}")


def _make_step_handler(verbose: bool):
    """Return an `on_step` callback that narrates each milestone."""

    def on_step(name: str, payload: dict) -> None:
        if name == "draft_started":
            _step("Note drafter: starting", color="yellow")
            patient = payload.get("patient", {})
            _kv("encounter", payload.get("encounter_id", ""))
            _kv("patient", f"{patient.get('name')} (subject_id={patient.get('subject_id')})")
            _kv("dob / sex", f"{patient.get('dob')} / {patient.get('sex')}")
            if patient.get("allergies"):
                _kv("allergies", ", ".join(patient["allergies"]))

        elif name == "draft_complete":
            _step("Note drafter: complete", color="green")
            _kv(
                "model",
                f"{payload['model']}  ({payload['tokens']['input']} in / {payload['tokens']['output']} out, {payload['duration_ms']}ms)",
            )
            _kv("vera record", f"seq={payload['sequence_number']}  id={payload['record_id'][:8]}…")
            if verbose:
                console.print(
                    Panel(
                        payload["note"],
                        title="[bold]SOAP Note (drafted)[/bold]",
                        border_style="dim",
                        padding=(1, 2),
                    )
                )

        elif name == "orders_extracted":
            _step("Orders extractor: complete", color="green")
            _kv(
                "model",
                f"{payload['model']}  ({payload['tokens']['input']} in / {payload['tokens']['output']} out)",
            )
            _kv("vera record", f"seq={payload['sequence_number']}  id={payload['record_id'][:8]}…")
            _kv("diagnoses", ", ".join(payload["diagnoses"]) or "(none)")
            _kv("med orders", ", ".join(payload["medication_orders"]) or "(none)")
            _kv("lab/imaging", ", ".join(payload["lab_or_imaging_orders"]) or "(none)")

        elif name == "approval_requested":
            _step("Vera HITL gate: APPROVAL REQUESTED", color="magenta")
            _kv("approval id", payload["approval_id"])
            _kv("risk tier", payload["risk_tier"].upper())
            _kv("status", "waiting on physician sign-off…")

        elif name == "approval_decided":
            color = "green" if payload["decision"] == "approve" else "red"
            verb = "APPROVED" if payload["decision"] == "approve" else "REJECTED"
            _step(f"Physician decision: {verb}", color=color)
            _kv("approver", payload["approver"])

        elif name == "chart_committed":
            _step("Chart commit: SUCCESS", color="green")
            _kv("vera record", payload["record_id"][:8] + "…")
            _kv("auto-committed", str(payload.get("auto", False)))

        elif name == "chart_blocked":
            _step("Chart commit: BLOCKED", color="red")
            _kv("approval status", payload["approval_status"])
            _kv("vera record", payload["record_id"][:8] + "…")

    return on_step


# ── Wrap-up ─────────────────────────────────────────────────────────────────


def _summary_panel(result: EncounterResult, vera_url: str) -> Panel:
    table = Table(show_header=False, box=None, padding=(0, 1))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Encounter", result.encounter_id)
    table.add_row("Risk tier", result.risk_tier.upper())
    table.add_row("Approval status", result.approval_status)
    table.add_row("Chart committed", "yes" if result.chart_committed else "no")
    table.add_row("Records written", str(len(result.record_ids)))
    table.add_row("Vera dashboard", f"{vera_url.replace('api.', '')}/actions")
    return Panel(table, title="[bold]Encounter complete[/bold]", border_style="cyan")


def _verify_chain(client) -> None:
    _hr("Verifying chain integrity")
    result = client.verify_chain()
    valid = result.get("is_valid", False)
    icon = "[green]✓[/green]" if valid else "[red]✗[/red]"
    console.print(
        f"{icon} chain {('VALID' if valid else 'INVALID')} — {result.get('records_checked', '?')} records checked"
    )
    if not valid:
        console.print(f"[red]message:[/red] {result.get('message', '(no message)')}")


# ── Entry point ─────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mode A demo runner — screenshare-ready customer walkthroughs."
    )
    parser.add_argument(
        "customer",
        help="Customer slug to run. Currently supported: scribemd.",
    )
    parser.add_argument(
        "--encounter",
        choices=list(ALL_ENCOUNTERS.keys()),
        default="pancreatitis",
        help="Encounter fixture to run (scribemd only).",
    )
    parser.add_argument(
        "--reject",
        action="store_true",
        help="Have the physician reject the approval (demos the BLOCKED path).",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run a chain verification pass after the encounter.",
    )
    parser.add_argument(
        "--quiet-note",
        action="store_true",
        help="Suppress the full SOAP-note panel (less screen clutter).",
    )
    args = parser.parse_args()

    _load_env()

    if args.customer == "scribemd":
        return _run_scribemd(args)
    parser.error(
        f"Customer {args.customer!r} not yet implemented. "
        "Currently supported: scribemd. (TriageGuard, AuthAssist coming soon.)"
    )
    return 2


def _run_scribemd(args) -> int:
    encounter = ALL_ENCOUNTERS[args.encounter]()
    delay = float(os.environ.get("DEMO_APPROVAL_DELAY_SECONDS", "3"))
    physician = always_reject_callback() if args.reject else auto_approve_callback(delay)

    _hr("ScribeMD Health — Live Encounter Demo")
    console.print(
        Text.from_markup(
            "[dim]A mock AI scribe vendor (Abridge/Ambience-style) integrated with Vera.\n"
            "Vera intercepts every diagnosis + medication order before it lands in the EHR.[/dim]"
        )
    )
    console.print()

    # Build providers. NoteDrafter uses OpenAI; OrdersExtractor uses Anthropic.
    note_provider = get_provider("openai", mode="A")
    orders_provider = get_provider("anthropic", mode="A")

    # Each agent gets its own Vera client so agent_name is correct on every
    # record landed in the chain.
    note_vera = get_client(
        "scribemd",
        agent_name=NoteDrafterAgent.AGENT_NAME,
        model_id=note_provider.model,
        framework=NoteDrafterAgent.FRAMEWORK,
    )
    orders_vera = get_client(
        "scribemd",
        agent_name=OrdersExtractorAgent.AGENT_NAME,
        model_id=orders_provider.model,
        framework=OrdersExtractorAgent.FRAMEWORK,
    )
    chart_vera = get_client(
        "scribemd",
        agent_name="scribemd-chart-committer",
        framework="scribemd-pipeline",
    )

    drafter = NoteDrafterAgent(llm=note_provider, vera=note_vera)
    extractor = OrdersExtractorAgent(llm=orders_provider, vera=orders_vera)

    on_step = _make_step_handler(verbose=not args.quiet_note)

    try:
        result = run_encounter(
            encounter=encounter,
            drafter=drafter,
            extractor=extractor,
            chart_vera=chart_vera,
            physician_callback=physician,
            on_step=on_step,
        )
    except Exception as e:  # noqa: BLE001
        console.print(f"\n[red]Demo aborted:[/red] {e}")
        return 1
    finally:
        for c in (note_vera, orders_vera, chart_vera):
            c.close()

    console.print()
    console.print(_summary_panel(result, _vera_url()))

    if args.verify:
        with get_client("scribemd", agent_name="verifier") as v:
            _verify_chain(v)

    return 0


if __name__ == "__main__":
    sys.exit(main())
