"""
Maintenance Ticketing Agent — reference implementation
======================================================
Reproduces the logic of an n8n workflow I built at Charger Logistics that let
employees create maintenance jobs straight from Microsoft Teams. In production a
Teams message hit an Azure Bot, which triggered n8n, which validated the request
and created the job in the maintenance-management application.

Here the command parser + validation + payload builder run as plain Python, so
you can see how a free-text chat command becomes a structured maintenance job.

Example chat command:
    /maintenance create unit=TRK-4482 priority=high issue="brake light out"

Usage:
    python create_ticket.py            # runs the built-in sample commands
    python create_ticket.py '/maintenance create unit=TRL-2201 issue="tire wear"'
"""

from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone

VALID_PRIORITIES = {"low", "medium", "high", "urgent"}
UNIT_RE = re.compile(r"^(TRK|TRL|VAN)-\d{3,5}$", re.IGNORECASE)
# key=value with optional "quoted" value
PAIR_RE = re.compile(r'(\w+)=("([^"]*)"|\S+)')


class TicketError(ValueError):
    """Raised when a chat command can't be turned into a valid ticket."""


def parse_command(text: str) -> dict:
    text = text.strip()
    if not text.lower().startswith("/maintenance create"):
        raise TicketError("Command must start with '/maintenance create'")
    body = text[len("/maintenance create"):]
    fields = {k: (q if q else v) for k, v, q in PAIR_RE.findall(body)}

    unit = fields.get("unit", "").upper()
    if not UNIT_RE.match(unit):
        raise TicketError(f"Invalid or missing unit id: '{fields.get('unit','')}' "
                          "(expected e.g. TRK-4482)")
    issue = fields.get("issue", "").strip()
    if len(issue) < 4:
        raise TicketError("Issue description is missing or too short")

    priority = fields.get("priority", "medium").lower()
    if priority not in VALID_PRIORITIES:
        raise TicketError(f"Invalid priority '{priority}' "
                          f"(use one of {sorted(VALID_PRIORITIES)})")
    return {"unit": unit, "issue": issue, "priority": priority}


_counter = {"n": 4400}


def build_job_payload(parsed: dict, requested_by: str) -> dict:
    """The JSON that would be POSTed to the maintenance app's API."""
    _counter["n"] += 1
    return {
        "job_id": f"MJ-{_counter['n']}",
        "asset_unit": parsed["unit"],
        "description": parsed["issue"],
        "priority": parsed["priority"],
        "status": "Open",
        "source": "MS Teams / Azure Bot",
        "requested_by": requested_by,
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def handle(command: str, requested_by: str = "j.doe@charger.com") -> dict:
    """Full pipeline: returns either a Teams confirmation or an error message."""
    try:
        parsed = parse_command(command)
    except TicketError as e:
        return {"ok": False, "teams_reply": f"⚠️ Could not create job: {e}"}
    job = build_job_payload(parsed, requested_by)
    reply = (f"✅ Maintenance job **{job['job_id']}** created for "
             f"{job['asset_unit']} ({job['priority']} priority): "
             f"\"{job['description']}\".")
    return {"ok": True, "job": job, "teams_reply": reply}


SAMPLE_COMMANDS = [
    '/maintenance create unit=TRK-4482 priority=high issue="brake light out"',
    '/maintenance create unit=TRL-2201 issue="tire tread wear on rear axle"',
    '/maintenance create unit=VAN-118 priority=urgent issue="coolant leak"',
    '/maintenance create unit=BADUNIT issue="won\'t start"',      # invalid unit
    '/maintenance create unit=TRK-9001 priority=high',            # missing issue
]


def main() -> None:
    commands = sys.argv[1:] or SAMPLE_COMMANDS
    print(f"Handling {len(commands)} chat command(s)...\n")
    for cmd in commands:
        result = handle(cmd)
        print("> " + cmd)
        print("  " + result["teams_reply"])
        if result["ok"]:
            print("  payload: " + json.dumps(result["job"]))
        print()


if __name__ == "__main__":
    main()
