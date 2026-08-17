#!/usr/bin/env python3
"""Friend Forest Telegram bot — your forest, in your pocket.

Self-hosted, zero dependencies (Python 3.9+ stdlib only). It:

  * sends a morning digest: upcoming birthdays, friends worth reaching out to,
    and (optionally) calendar events in the next 48h that mention a friend
  * answers free-form questions about your friends via Claude, any time
    ("when did I last talk to Priya?", "who should I invite to the cabin trip?")

Setup:
  1. Make a bot with @BotFather on Telegram → copy the token
  2. Export your forest: forest → Settings (gear) → "Export forest data"
  3. Run:
       export TELEGRAM_BOT_TOKEN=123:abc
       export ANTHROPIC_API_KEY=sk-ant-...
       python3 forest_bot.py /path/to/friend-forest.json
  4. Message your bot /start once — done. Keep it running (tmux, systemd,
     launchd, a Raspberry Pi... anywhere).

Optional env:
  ICS_URL      — a calendar feed (Google Calendar → settings → "secret address
                 in iCal format"); events mentioning friends get reminders
  DIGEST_HOUR  — local hour for the morning digest (default 9)

Everything runs on your machine. The only network calls are Telegram (your
bot) and Anthropic (your key).
"""
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY")
ICS_URL = os.environ.get("ICS_URL")
DIGEST_HOUR = int(os.environ.get("DIGEST_HOUR", "9"))
FOREST_JSON = sys.argv[1] if len(sys.argv) > 1 else "friend-forest.json"
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".forest_bot_state.json")
MODEL = "claude-opus-5"

if not TOKEN:
    sys.exit("Set TELEGRAM_BOT_TOKEN (make a bot with @BotFather).")


# ---------- tiny http ----------
def http_json(url, payload=None, headers=None, timeout=120):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
        headers={"content-type": "application/json", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def tg(method, **params):
    return http_json(f"https://api.telegram.org/bot{TOKEN}/{method}", payload=params)


def send(chat_id, text):
    # telegram caps messages at 4096 chars
    for chunk in [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]:
        tg("sendMessage", chat_id=chat_id, text=chunk)


# ---------- state + forest ----------
def load_state():
    try:
        return json.load(open(STATE_PATH))
    except (OSError, ValueError):
        return {}


def save_state(s):
    json.dump(s, open(STATE_PATH, "w"))


def load_forest():
    with open(FOREST_JSON) as f:
        return json.load(f)


def forest_context(data, cap=400):
    rows = []
    for p in sorted(data["people"], key=lambda p: -(p.get("volume") or 0))[:cap]:
        bits = [p["name"]]
        if p.get("occupation"):
            bits.append("does: " + p["occupation"])
        if p.get("city"):
            bits.append("city: " + p["city"])
        if p.get("tags"):
            bits.append("groups: " + "/".join(p["tags"]))
        if p.get("last_interaction"):
            bits.append("last talked: " + p["last_interaction"])
        if p.get("birthday"):
            bits.append("birthday: " + p["birthday"])
        if p.get("reconnect") == "priority":
            bits.append("needs reaching out")
        if p.get("intro"):
            bits.append(p["intro"][:140])
        for s in p.get("sections") or []:
            bits.append(s["title"] + ": " + s["body"][:160])
        for t in (p.get("timeline") or [])[-3:]:
            bits.append(t["date"] + ": " + t["text"][:100])
        rows.append(" | ".join(bits))
    return "\n".join(rows)


# ---------- claude ----------
def ask_claude(data, question):
    if not ANTHROPIC_KEY:
        return "No ANTHROPIC_API_KEY set — I can only send digests. Add a key to chat!"
    who = (data.get("gardener") or {}).get("name") or "the user"
    prompt = (f"You are the friendly spirit of {who}'s friend forest — a personal "
              "friendship CRM. One line per friend below. Answer warmly and briefly, "
              "grounded ONLY in this data; say so if it can't answer.\n\n"
              f"{forest_context(data)}\n\nQuestion: {question}")
    try:
        msg = http_json("https://api.anthropic.com/v1/messages",
            payload={"model": MODEL, "max_tokens": 4096,
                     "messages": [{"role": "user", "content": prompt}]},
            headers={"x-api-key": ANTHROPIC_KEY, "anthropic-version": "2023-06-01"})
    except Exception as e:  # noqa: BLE001 — surface anything to the chat
        return f"Claude call failed: {e}"
    if msg.get("stop_reason") == "refusal":
        return "Claude declined that question."
    return "".join(b.get("text", "") for b in msg.get("content", [])
                   if b.get("type") == "text") or "(no answer)"


# ---------- calendar (.ics) ----------
def fetch_events():
    """[(start_datetime_local_naive, summary)] for the next 14 days."""
    if not ICS_URL:
        return []
    try:
        with urllib.request.urlopen(ICS_URL, timeout=30) as r:
            raw = r.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        print(f"calendar fetch failed: {e}", file=sys.stderr)
        return []
    # unfold wrapped lines
    raw = raw.replace("\r\n ", "").replace("\r\n\t", "")
    events, cur = [], None
    for line in raw.splitlines():
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if "start" in cur and "summary" in cur:
                events.append((cur["start"], cur["summary"]))
            cur = None
        elif cur is not None:
            if line.startswith("DTSTART"):
                val = line.split(":", 1)[-1].strip()
                m = re.match(r"(\d{8})(T(\d{6}))?", val)
                if m:
                    d = datetime.strptime(m.group(1), "%Y%m%d")
                    if m.group(3):
                        t = datetime.strptime(m.group(3), "%H%M%S").time()
                        d = datetime.combine(d.date(), t)
                        if val.endswith("Z"):  # utc → local
                            d = d + (datetime.now() - datetime.utcnow())
                    cur["start"] = d
            elif line.startswith("SUMMARY"):
                cur["summary"] = line.split(":", 1)[-1].strip()
    horizon = datetime.now() + timedelta(days=14)
    return [(s, t) for s, t in events if datetime.now() - timedelta(hours=6) <= s <= horizon]


def friend_events(data, hours=48):
    """calendar events soon that mention a friend by name."""
    hits = []
    names = [(p["name"], p["name"].split()[0]) for p in data["people"]]
    for start, summary in fetch_events():
        if start > datetime.now() + timedelta(hours=hours):
            continue
        low = summary.lower()
        for full, first in names:
            if full.lower() in low or re.search(r"\b" + re.escape(first.lower()) + r"\b", low):
                hits.append((start, summary, full))
                break
    return sorted(hits)


# ---------- digest ----------
def days_to_birthday(bday):
    try:
        m, d = int(bday[5:7]), int(bday[8:10])
    except (TypeError, ValueError):
        return None
    today = date.today()
    for year in (today.year, today.year + 1):
        try:
            nxt = date(year, m, d)
        except ValueError:  # feb 29
            nxt = date(year, 3, 1)
        if nxt >= today:
            return (nxt - today).days
    return None


def build_digest(data):
    lines = []
    bdays = [(days_to_birthday(p.get("birthday")), p) for p in data["people"]]
    bdays = sorted((d, p) for d, p in bdays if d is not None and d <= 7)
    if bdays:
        lines.append("🎂 Birthdays this week:")
        lines += [f"  • {p['name']} — {'today!!' if d == 0 else f'in {d}d'}" for d, p in bdays]
    for start, summary, name in friend_events(data):
        lines.append(f"📅 {start.strftime('%a %H:%M') if start.time() != datetime.min.time() else start.strftime('%a')}: "
                     f"{summary} (with {name.split()[0]})")
    quiet = [p for p in data["people"] if p.get("reconnect") == "priority"]
    quiet.sort(key=lambda p: p.get("last_interaction") or "")
    if quiet:
        lines.append("💧 Worth watering (close friends gone quiet):")
        lines += [f"  • {p['name']} — quiet since {p.get('last_interaction', '?')}"
                  for p in quiet[:5]]
    if not lines:
        return "🌳 Forest report: all quiet — no birthdays, events, or thirsty trees this week."
    return "🌳 Morning forest report\n\n" + "\n".join(lines)


# ---------- main loop ----------
def main():
    state = load_state()
    offset = state.get("offset", 0)
    print(f"forest bot up — reading {FOREST_JSON}"
          + (f", calendar connected" if ICS_URL else ""))
    while True:
        # digest due?
        now = datetime.now()
        if (state.get("chat_id") and now.hour >= DIGEST_HOUR
                and state.get("last_digest") != str(date.today())):
            try:
                send(state["chat_id"], build_digest(load_forest()))
                state["last_digest"] = str(date.today())
                save_state(state)
            except Exception as e:  # noqa: BLE001
                print(f"digest failed: {e}", file=sys.stderr)

        # poll telegram
        try:
            updates = tg("getUpdates", offset=offset, timeout=50)["result"]
        except Exception as e:  # noqa: BLE001
            print(f"poll failed: {e}", file=sys.stderr)
            time.sleep(10)
            continue
        for u in updates:
            offset = u["update_id"] + 1
            state["offset"] = offset
            m = u.get("message") or {}
            text = (m.get("text") or "").strip()
            chat = m.get("chat", {}).get("id")
            if not text or not chat:
                continue
            if state.get("chat_id") not in (None, chat):
                continue  # single-user bot: first /start wins
            if text == "/start":
                state["chat_id"] = chat
                save_state(state)
                send(chat, "🌳 Your forest is connected! I'll send a morning report "
                           f"around {DIGEST_HOUR}:00, and you can ask me anything about "
                           "your friends any time.\n\nTry: \"who should I reach out to?\"")
            elif text == "/digest":
                send(chat, build_digest(load_forest()))
            elif text in ("/help", "/help@"):
                send(chat, "/digest — forest report now\nanything else — I'll ask Claude "
                           "about your friends")
            else:
                send(chat, ask_claude(load_forest(), text))
        save_state(state)


if __name__ == "__main__":
    main()
