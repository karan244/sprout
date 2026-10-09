#!/usr/bin/env python3
"""
Sprout - what can I plant right now?

A planting calendar that works out what belongs in the ground this week from
frost dates, and then explains itself in plain language using an open-weight
model running on your own machine.

    python3 sprout.py                 # today's plan for your region
    python3 sprout.py --ask "why spinach?"
    python3 sprout.py --chat

Design note - the same lesson LingoBuddy taught, applied to gardening:
frost dates and sowing windows are rules, so they live in Python and are always
right. Only the explanation is sent to the model, because explaining is the part
that benefits from language ability rather than arithmetic.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import date, datetime

DEFAULT_HOST = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5:3b"
_HOST = None

# ---------------------------------------------------------------- regions
# First frost dates are the anchor for cool-season planting: most vegetables are
# timed backwards from the day you can expect frost, not from the calendar.
# These are deliberately rough averages for a whole region, not a forecast.
# Override them with --first-frost if you know better for your garden.

REGIONS = {
    "north-india": {
        "label": "North India - Delhi, Punjab, Haryana",
        "first_frost": (11, 20),
        "note": "Winter greens are the whole season here from about now.",
    },
    "south-india": {
        "label": "South India - Bangalore, Kerala",
        "first_frost": (12, 31),
        "note": "Almost frost-free. Treat these dates as a rough cool-season marker.",
    },
    "uk": {
        "label": "UK and Ireland",
        "first_frost": (10, 25),
        "note": "Get garlic in before the ground gets cold and wet.",
    },
    "us-northeast": {
        "label": "US Northeast - New York, Boston, Pennsylvania",
        "first_frost": (10, 15),
        "note": "Frost is close. Sow the cold-hardy stuff, start the tender stuff inside.",
    },
    "us-california": {
        "label": "US California - Sacramento, Bay Area inland",
        "first_frost": (11, 15),
        "note": "Mild winters, so a long cool-season sowing window.",
    },
    "australia-melbourne": {
        "label": "Australia - Melbourne, Victoria",
        "first_frost": (4, 25),
        "note": "Southern hemisphere: this is the start of autumn, so plant now.",
    },
    "new-zealand": {
        "label": "New Zealand",
        "first_frost": (5, 1),
        "note": "Southern hemisphere: broad beans and brassicas suit this month.",
    },
}

# ---------------------------------------------------------------- crops
# window  = (earliest, latest) days relative to the first frost date.
#           -60 means "sow 60 days before the first expected frost".
# hardy   = lowest temperature in Celsius it survives once established.
# direct  = can be sown straight into the ground (False means start in trays).

CROPS = [
    {"name": "Broad beans",  "window": (-75, -40), "hardy": -4, "direct": True,  "days": 90,
     "tip": "Inoculated seeds fix their own nitrogen, so they feed the soil behind them."},
    {"name": "Peas",         "window": (-70, -35), "hardy": -3, "direct": True,  "days": 70,
     "tip": "Inoculated too, and they fix nitrogen for whatever you plant after them."},
    {"name": "Spinach",      "window": (-60, -5),  "hardy": -6, "direct": True,  "days": 45,
     "tip": "One of the hardiest things you can sow. It bolts early in spring, so sow it late."},
    {"name": "Kale",         "window": (-55, 0),   "hardy": -10, "direct": True, "days": 60,
     "tip": "Survives hard frost and gets sweeter after it. Grows right through winter."},
    {"name": "Carrots",      "window": (-60, -20), "hardy": -5, "direct": True,  "days": 70,
     "tip": "Slow to germinate. Keep the seedbed damp or nothing will come up."},
    {"name": "Lettuce",      "window": (-55, -10), "hardy": -4, "direct": True,  "days": 50,
     "tip": "Sow little and often, every two weeks, or it all bolts at once."},
    {"name": "Coriander",    "window": (-50, -10), "hardy": -3, "direct": True,  "days": 40,
     "tip": "Bolt at the first sign of heat. Sow in the coolest part of the season."},
    {"name": "Radish",       "window": (-45, -10), "hardy": -5, "direct": True,  "days": 25,
     "tip": "Fastest crop here. Good for keeping a beginner motivated."},
    {"name": "Onions",       "window": (-60, -30), "hardy": -5, "direct": False, "days": 110,
     "tip": "Start in trays weeks before sowing outside, or the bulbs will not form."},
    {"name": "Cabbage",      "window": (-40, 0),   "hardy": -8, "direct": False, "days": 80,
     "tip": "Start in trays. Plant out once the seedlings have a few true leaves."},
    {"name": "Cauliflower",  "window": (-35, 0),   "hardy": -3, "direct": False, "days": 90,
     "tip": "The fussiest of these. It needs a cold spell to head up properly."},
    {"name": "Garlic",       "window": (-12, 14),  "hardy": -12, "direct": True, "days": 240,
     "tip": "Planted close to the first frost and left alone for eight months."},
]


# ---------------------------------------------------------------- plumbing
# Identical to LingoBuddy: find Ollama, talk to it, tidy up its answers.

def bridge_host():
    """Windows host address as seen from inside WSL, read from the routing table."""
    try:
        out = subprocess.run(
            ["ip", "route", "show", "default"], capture_output=True, text=True, timeout=4
        ).stdout
        m = re.search(r"default via (\d+\.\d+\.\d+\.\d+)", out)
        if m:
            return "http://" + m.group(1) + ":11434"
    except Exception:
        pass
    return None


def resolve_host():
    """First host that answers, else the first candidate for error messages."""
    global _HOST
    if _HOST is not None:
        return _HOST
    candidates = [
        h
        for h in [os.environ.get("OLLAMA_HOST", "").rstrip("/"), DEFAULT_HOST, bridge_host()]
        if h
    ] or [DEFAULT_HOST]
    for host in candidates:
        try:
            urllib.request.urlopen(host + "/api/version", timeout=3)
            _HOST = host
            return host
        except Exception:
            continue
    _HOST = candidates[0]
    return _HOST


def die(msg):
    print("\n[!] " + msg, file=sys.stderr)
    sys.exit(1)


def models_available():
    try:
        with urllib.request.urlopen(resolve_host() + "/api/tags", timeout=10) as r:
            return [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return []


def check_model(model):
    if not models_available():
        die(
            "Cannot reach Ollama, or it has no models.\n"
            "    On Windows start it and pull a model:\n"
            "      ollama pull " + model
        )
    names = models_available()
    if not any(n == model or n.split(":")[0] == model.split(":")[0] for n in names):
        die(
            "Model '" + model + "' is not pulled.\n"
            "    Available: " + ", ".join(names) + "\n"
            "    Or run:  ollama pull " + model
        )


def ask(prompt, model, temperature=0.7, history=None):
    """One round trip to the model."""
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": prompt}] + (history or []),
        "stream": False,
        "options": {"temperature": temperature, "num_ctx": 2048},
    }
    req = urllib.request.Request(
        resolve_host() + "/api/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=900) as resp:
            text = json.loads(resp.read().decode("utf-8"))["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        die("Ollama returned HTTP " + str(e.code) + ":\n" + e.read().decode("utf-8", "replace"))
    except KeyboardInterrupt:
        raise
    except Exception as e:
        die("Request failed: " + str(e))
    return tidy(text)


def tidy(text):
    """Strip the scaffolding models wrap around answers."""
    t = text.strip()
    t = re.sub(r"^(sure[,!.]?|certainly[,!.]?|of course[,!.]?)\s+", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^(here(?:'s| is)[^:\n]{0,60}:)\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^```[a-z]*\n|\n```$", "", t)
    t = re.sub(r"^(?:answer|response|summary)\s*:\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^[\-\*\s]+", "", t, flags=re.MULTILINE)
    return t.strip().strip('"').strip()


# ---------------------------------------------------------------- the actual gardening

def md_to_date(month, day, today):
    """First frost, rolled forward to next year if this year's date has passed.

    Needed for the southern hemisphere, where an April frost date is in the
    future when it is October.
    """
    this_year = date(today.year, month, day)
    if this_year < today:
        return date(today.year + 1, month, day)
    return this_year


def days_between(a, b):
    return (b - a).days


def sow_window(crop, frost_date):
    """Inclusive date range for sowing this crop, from its frost offsets."""
    early, late = crop["window"]
    return (
        date.fromordinal(frost_date.toordinal() + early),
        date.fromordinal(frost_date.toordinal() + late),
    )


def plan_for(today, first_frost, crops=CROPS):
    """Work out what to sow now. Pure arithmetic - no model involved."""
    rows = []
    for crop in crops:
        start, end = sow_window(crop, first_frost)
        if start <= today <= end:
            status = "SOW NOW"
        elif today < start:
            status = "WAIT"
        else:
            status = "DONE"
        rows.append({
            "crop": crop,
            "start": start,
            "end": end,
            "status": status,
            "days_wait": (start - today).days if status == "WAIT" else 0,
        })
    return rows


def show_plan(rows, first_frost, today, region, ai_note=None):
    print()
    print("=" * 66)
    print("  Sprout - " + today.strftime("%A %d %B %Y"))
    print("  " + region["label"])
    print("  first frost expected " + first_frost.strftime("%d %B")
          + "  (" + str(days_between(today, first_frost)) + " days away)")
    print("=" * 66)

    for status, title in [
        ("SOW NOW", "Sow now"),
        ("WAIT", "Not yet - sow on these dates"),
        ("DONE", "Window has closed, next season"),
    ]:
        group = [r for r in rows if r["status"] == status]
        if not group:
            continue
        print()
        print(title)
        for r in group:
            c = r["crop"]
            how = "direct" if c["direct"] else "start in trays"
            extra = ""
            if status == "WAIT":
                extra = "   (in " + str(r["days_wait"]) + " days, from " + r["start"].strftime("%d %b") + ")"
            elif status == "DONE":
                extra = "   (was " + r["start"].strftime("%d %b") + " to " + r["end"].strftime("%d %b") + ")"
            else:
                extra = "   (window closes " + r["end"].strftime("%d %b") + ")"
            print("  " + c["name"].ljust(14) + how.ljust(16)
                  + "to " + str(c["hardy"]) + "C".ljust(7) + extra)

    if region.get("note"):
        print()
        print("  note: " + region["note"])

    if ai_note:
        print()
        print("-" * 66)
        print(ai_note)
    print("-" * 66)


P_EXPLAIN = """You are a gardener's assistant. Someone asked what they can plant this week.

A program worked out the answer from frost dates. These are the facts:

Region: {region}
Today: {today}
First frost expected: {frost}, which is {days} days from now.

Most urgent, sowing in the ground right now:
{urgent}

Each has a note from a planting guide:
{notes}

Write 2 or 3 sentences of warm, practical advice, as if talking to a friend.

- Lead with the one thing to do first.
- Pick at most two of the notes above and share them in your own words. Ignore the rest.
- Do not list the crops. Do not use bullet points, headings or lists of any kind.
- Plain sentences only.
- Do not repeat that a program worked this out.

Then, on a new line, write exactly:
NEXT: <one short question this gardener would plausibly ask next>
"""


def build_prompt(rows, region, today, first_frost):
    """Feed the model only what it could not know on its own: the guide notes."""
    urgent = []
    notes = []
    for r in rows:
        if r["status"] != "SOW NOW":
            continue
        c = r["crop"]
        how = "straight into the ground" if c["direct"] else "in trays first"
        urgent.append("- " + c["name"] + " (sow " + how + ", ready in about "
                      + str(c["days"]) + " days)")
        notes.append("- " + c["name"] + ": " + c["tip"])

    return P_EXPLAIN.format(
        region=region["label"],
        today=today.strftime("%d %B %Y"),
        frost=first_frost.strftime("%d %B"),
        days=days_between(today, first_frost),
        urgent="\n".join(urgent) if urgent else "- nothing is open this week",
        notes="\n".join(notes) if notes else "- none",
    )


P_ASK = """You are a gardener's assistant helping someone in {region}.
Today is {today}. First frost is expected around {frost}.

A program worked out which crops are open right now. These are the facts:

Open for sowing right now: {open_now}
Not open yet: {not_yet}
Already past their window this season: {closed}

They asked: {question}

Rules:
- Answer in 2 or 4 sentences, practical and specific to their region and season.
- Plain sentences. No bullet points, no headings.
- If they ask about a crop that is not in any of the three lists above, say plainly
  that it is not something you have information about this season, then suggest
  something from the lists that is.
- Never tell them to sow a crop that the lists show is not open. If they ask about
  something out of season, explain that instead.
- Do not invent dates, varieties or frost dates. If you are unsure, say so.
"""


def build_ask_prompt(rows, question, region, today, first_frost):
    """Ground the answer in the same computed facts the plan is built from."""

    def names(*statuses):
        return ", ".join(
            r["crop"]["name"] for r in rows if r["status"] in statuses
        ) or "none"

    return P_ASK.format(
        region=region["label"],
        today=today.strftime("%d %B %Y"),
        frost=first_frost.strftime("%d %B"),
        open_now=names("SOW NOW"),
        not_yet=names("WAIT"),
        closed=names("DONE"),
        question=question,
    )


def chat(model, region, today, first_frost, rows, history):
    print()
    print("  Ask Sprout anything about your garden.  /quit to leave.")
    print("-" * 66)
    while True:
        try:
            question = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye. Now go outside and plant something.")
            break
        if not question:
            continue
        if question in ("/quit", "/q", "/exit"):
            print("Bye. Now go outside and plant something.")
            break
        history.append({"role": "user", "content": question})
        reply = ask(
            build_ask_prompt(rows, question, region, today, first_frost),
            model,
            temperature=0.5,
            history=history,
        )
        print("\n" + reply)
        history.append({"role": "assistant", "content": reply})
        print("-" * 66)


def main():
    p = argparse.ArgumentParser(
        description="What can I plant right now, from frost dates, explained by a local AI.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
        "  python3 sprout.py\n"
        "  python3 sprout.py --region uk\n"
        "  python3 sprout.py --first-frost 11-05\n"
        "  python3 sprout.py --ask 'why not peas?'",
    )
    p.add_argument("--region", default="north-india", choices=sorted(REGIONS),
                   help="your region (default: north-india)")
    p.add_argument("--first-frost", default="",
                   help="override first frost date as MM-DD, e.g. 11-05")
    p.add_argument("--date", default="", help="pretend today is this, YYYY-MM-DD")
    p.add_argument("--ask", dest="question", default="", help="ask one question and exit")
    p.add_argument("--chat", action="store_true", help="interactive question mode")
    p.add_argument("--no-ai", action="store_true", help="skip the AI explanation, print facts only")
    p.add_argument("--model", default=DEFAULT_MODEL, help="Ollama model (default: " + DEFAULT_MODEL + ")")
    p.add_argument("--list", action="store_true", help="list regions and exit")
    cfg = p.parse_args()

    if cfg.list:
        for key, r in REGIONS.items():
            print(key.ljust(22) + r["label"] + "   first frost "
                  + "%02d-%02d" % r["first_frost"])
        return

    if cfg.first_frost:
        try:
            mm, dd = (int(x) for x in cfg.first_frost.split("-"))
            first_frost = md_to_date(mm, dd, date.today())
        except Exception:
            die("--first-frost must look like 11-05")
    else:
        mm, dd = REGIONS[cfg.region]["first_frost"]
        first_frost = md_to_date(mm, dd, date.today())

    today = date.today()
    if cfg.date:
        try:
            today = datetime.strptime(cfg.date, "%Y-%m-%d").date()
        except Exception:
            die("--date must look like 2026-10-12")

    region = dict(REGIONS[cfg.region])
    if cfg.first_frost:
        region["label"] = REGIONS[cfg.region]["label"] + " (custom frost date)"

    rows = plan_for(today, first_frost)

    if not cfg.question and not cfg.chat:
        note = None
        if not cfg.no_ai:
            check_model(cfg.model)
            note = ask(build_prompt(rows, region, today, first_frost), cfg.model, temperature=0.5)
        show_plan(rows, first_frost, today, region, note)
        return

    check_model(cfg.model)
    if cfg.question:
        print()
        print(ask(
            build_ask_prompt(rows, cfg.question, region, today, first_frost),
            cfg.model,
            temperature=0.5,
        ))
        print()
        return

    chat(cfg.model, region, today, first_frost, rows, [])


if __name__ == "__main__":
    main()