#!/usr/bin/env python3
"""Friend Forest iMessage helper (Mac only, runs offline).

Counts who you text and when — names via your local Contacts, message COUNTS
only (never message content) — and writes one summary JSON you drop into the
Friend Forest onboarding. Nothing is uploaded anywhere.

Usage:
    python3 extract_messages.py [out.json]        # default: ~/Desktop/friend-forest-messages.json

If you see an "unable to open database" error, grant your terminal Full Disk
Access (System Settings → Privacy & Security → Full Disk Access), then re-run.
"""
import glob
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
CHAT_DB = f"{HOME}/Library/Messages/chat.db"
APPLE_EPOCH = 978307200


def norm_phone(p):
    digits = re.sub(r"\D", "", p or "")
    return digits[-10:] if len(digits) >= 10 else digits


def load_contacts():
    """phone/email -> name from all AddressBook sources."""
    m = {}
    dbs = glob.glob(f"{HOME}/Library/Application Support/AddressBook/Sources/*/AddressBook-v22.abcddb")
    dbs += glob.glob(f"{HOME}/Library/Application Support/AddressBook/AddressBook-v22.abcddb")
    for db in dbs:
        try:
            c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = c.execute("""
                SELECT r.ZFIRSTNAME, r.ZLASTNAME, p.ZFULLNUMBER, e.ZADDRESS
                FROM ZABCDRECORD r
                LEFT JOIN ZABCDPHONENUMBER p ON p.ZOWNER = r.Z_PK
                LEFT JOIN ZABCDEMAILADDRESS e ON e.ZOWNER = r.Z_PK
            """).fetchall()
            for first, last, phone, email in rows:
                name = " ".join(x for x in (first, last) if x).strip()
                if not name:
                    continue
                if phone:
                    m.setdefault(norm_phone(phone), name)
                if email:
                    m.setdefault(email.lower().strip(), name)
            c.close()
        except sqlite3.Error as e:
            print(f"  (skip contacts db {db}: {e})", file=sys.stderr)
    return m


def name_for(handle, contacts):
    if "@" in handle:
        return contacts.get(handle.lower().strip())
    return contacts.get(norm_phone(handle))


def to_date(apple):
    if not apple:
        return None
    secs = apple / 1e9 if abs(apple) > 1e11 else apple
    return datetime.fromtimestamp(secs + APPLE_EPOCH, timezone.utc).strftime("%Y-%m-%d")


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else f"{HOME}/Desktop/friend-forest-messages.json"

    contacts = load_contacts()
    print(f"Loaded {len(contacts)} contact identifiers", file=sys.stderr)

    try:
        c = sqlite3.connect(f"file:{CHAT_DB}?mode=ro", uri=True)
        rows = c.execute("""
            SELECT h.id, m.date
            FROM message m JOIN handle h ON m.handle_id = h.ROWID
            WHERE h.id IS NOT NULL
        """).fetchall()
        c.close()
    except sqlite3.Error as e:
        print(f"Couldn't open Messages database: {e}", file=sys.stderr)
        print("Grant your terminal Full Disk Access and re-run.", file=sys.stderr)
        sys.exit(1)

    # merge handles that resolve to the same contact name
    people = {}
    for handle, date in rows:
        name = name_for(handle, contacts)
        key = name or handle
        p = people.setdefault(key, {"name": name, "handle": handle,
                                    "messages": 0, "first": None, "last": None})
        p["messages"] += 1
        day = to_date(date)
        if day:
            if not p["first"] or day < p["first"]:
                p["first"] = day
            if not p["last"] or day > p["last"]:
                p["last"] = day

    result = {"people": sorted(
        [p for p in people.values() if p["name"] or p["messages"] >= 20],
        key=lambda p: -p["messages"])}
    with open(out, "w") as f:
        json.dump(result, f, indent=1)
    print(f"Wrote {out}: {len(result['people'])} texting relationships "
          f"(counts + dates only — no message content)")


if __name__ == "__main__":
    main()
