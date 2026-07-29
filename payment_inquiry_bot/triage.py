"""
Carrier Payment-Status Inquiry Bot — reference implementation
=============================================================
Reproduces the decision logic of an n8n workflow I built at Charger Logistics.
In production the workflow watched a shared Outlook inbox, used an AI (Claude)
node to read each email, looked payment status up in Postgres, and drafted a
reply — routing exceptions to the right team.

Here that same logic runs as plain Python over sample emails and a mock database,
so a reviewer can see exactly how each message is classified and routed. No real
emails or company data are included.

Flow per email:
    1. Classify — is this a payment-status inquiry?  (production: AI node)
    2. Extract the contract number from the body.
    3. Look it up in the payments database.
       - not found in email      -> tag Accounts Payable
       - not found in database    -> tag Accounts Payable
       - contract flagged w/ error -> tag Carrier IT Support
       - otherwise                 -> draft a reply with the status
Usage:
    python triage.py
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
CONTRACT_RE = re.compile(r"\bCON[-\s]?(\d{6})\b", re.IGNORECASE)
INQUIRY_HINTS = ("payment", "paid", "remittance", "invoice status",
                 "when will", "status of", "outstanding", "settled")


def load_db(path: Path) -> dict[str, dict]:
    db = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            db[row["contract_number"].upper()] = row
    return db


def is_payment_inquiry(email: dict) -> bool:
    """Stand-in for the AI classification node."""
    text = f"{email['subject']} {email['body']}".lower()
    return any(h in text for h in INQUIRY_HINTS)


def extract_contract(email: dict) -> str | None:
    m = CONTRACT_RE.search(f"{email['subject']} {email['body']}")
    return f"CON-{m.group(1)}" if m else None


def draft_reply(email: dict, rec: dict) -> str:
    return (
        f"To: {email['from']}\n"
        f"Subject: Re: {email['subject']}\n\n"
        f"Hi,\n\n"
        f"Thanks for reaching out. For contract {rec['contract_number']} "
        f"({rec['carrier']}), the current payment status is "
        f"\"{rec['status']}\". "
        + (
            f"Payment of ${float(rec['amount']):,.2f} is scheduled for "
            f"{rec['expected_pay_date']}.\n\n"
            if rec["status"].lower() != "paid"
            else f"Payment of ${float(rec['amount']):,.2f} was released on "
                 f"{rec['expected_pay_date']}.\n\n"
        )
        + "Please let us know if you have any questions.\n\n"
        "Best regards,\nAccounts Payable — Charger Logistics"
    )


def triage(email: dict, db: dict) -> dict:
    if not is_payment_inquiry(email):
        return {"action": "SKIP", "reason": "Not a payment-status inquiry"}

    contract = extract_contract(email)
    if contract is None:
        return {"action": "ROUTE", "team": "Accounts Payable",
                "reason": "No contract number found in email"}

    rec = db.get(contract.upper())
    if rec is None:
        return {"action": "ROUTE", "team": "Accounts Payable",
                "reason": f"Contract {contract} not found in database"}

    if str(rec.get("has_error", "")).strip().lower() in ("1", "true", "yes"):
        return {"action": "ROUTE", "team": "Carrier IT Support",
                "reason": f"Contract {contract} has a data error",
                "contract": contract}

    return {"action": "REPLY", "contract": contract,
            "status": rec["status"], "reply": draft_reply(email, rec)}


def main() -> None:
    db = load_db(HERE / "contracts.csv")
    emails = json.loads((HERE / "sample_emails.json").read_text(encoding="utf-8"))

    out = HERE / "output"
    out.mkdir(exist_ok=True)
    log_rows = []
    counts = {"REPLY": 0, "ROUTE": 0, "SKIP": 0}

    print(f"Processing {len(emails)} inbound emails...\n")
    for i, email in enumerate(emails, 1):
        result = triage(email, db)
        counts[result["action"]] += 1
        summary = result.get("team") or result.get("status") or result["reason"]
        print(f"[{i:02d}] {email['subject'][:44]:44s} -> "
              f"{result['action']:6s} | {summary}")

        if result["action"] == "REPLY":
            (out / f"reply_{result['contract']}.txt").write_text(
                result["reply"], encoding="utf-8")
        log_rows.append({
            "from": email["from"], "subject": email["subject"],
            "action": result["action"],
            "detail": result.get("team", "") or result.get("reason", ""),
            "contract": result.get("contract", ""),
        })

    with open(out / "routing_log.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(log_rows[0].keys()))
        w.writeheader()
        w.writerows(log_rows)

    print(f"\nDone. Replied: {counts['REPLY']}  Routed: {counts['ROUTE']}  "
          f"Skipped: {counts['SKIP']}")
    print(f"Drafted replies + routing_log.csv written to {out}/")


if __name__ == "__main__":
    main()
