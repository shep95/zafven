"""Personal safety companion — check-ins, SOS, and trusted contacts.

This is the LEGAL, consent-based core of a "walking somewhere sketchy" safety tool:
it does not record anyone or profile anyone. It lets a person start a timed
check-in; if they don't mark themselves safe in time, the bot alerts the trusted
contacts they chose (who agreed to be contacts). An SOS sends that alert now.

Pure logic + persistence live here (store-backed, testable without Discord); the
cog owns the Discord surface and the timers.
"""
from __future__ import annotations

import time

NS_CONTACTS = "safety_contacts"    # {user_id: [contact_user_id, ...]}
NS_CHECKINS = "safety_checkins"    # {user_id: {due, started, note, channel_id, minutes}}
NS_PROFILE = "safety_profile"      # {user_id: {"note": str}}

MAX_CONTACTS = 10
MIN_MINUTES = 1
MAX_MINUTES = 24 * 60
MAX_NOTE = 300


def _clamp_minutes(minutes: int) -> int:
    return max(MIN_MINUTES, min(int(minutes), MAX_MINUTES))


# ── contacts ───────────────────────────────────────────────────────────────
def get_contacts(store, user_id: int) -> list[int]:
    table = store.get(NS_CONTACTS, {}) or {}
    return list(table.get(str(user_id), []))


async def add_contact(store, user_id: int, contact_id: int) -> tuple[bool, str]:
    if contact_id == user_id:
        return False, "you can't add yourself as your own emergency contact."
    table = dict(store.get(NS_CONTACTS, {}) or {})
    contacts = list(table.get(str(user_id), []))
    if contact_id in contacts:
        return False, "they're already one of your contacts."
    if len(contacts) >= MAX_CONTACTS:
        return False, f"you can have at most {MAX_CONTACTS} contacts."
    contacts.append(contact_id)
    table[str(user_id)] = contacts
    await store.set(NS_CONTACTS, table)
    return True, "added."


async def remove_contact(store, user_id: int, contact_id: int) -> bool:
    table = dict(store.get(NS_CONTACTS, {}) or {})
    contacts = list(table.get(str(user_id), []))
    if contact_id not in contacts:
        return False
    contacts = [c for c in contacts if c != contact_id]
    table[str(user_id)] = contacts
    await store.set(NS_CONTACTS, table)
    return True


# ── check-ins ────────────────────────────────────────────────────────────────
def get_checkin(store, user_id: int) -> dict | None:
    table = store.get(NS_CHECKINS, {}) or {}
    return table.get(str(user_id))


def all_checkins(store) -> dict:
    return dict(store.get(NS_CHECKINS, {}) or {})


async def start_checkin(store, user_id: int, minutes: int, note: str = "",
                        channel_id: int = 0) -> dict:
    minutes = _clamp_minutes(minutes)
    now = int(time.time())
    entry = {
        "due": now + minutes * 60,
        "started": now,
        "minutes": minutes,
        "note": (note or "").strip()[:MAX_NOTE],
        "channel_id": channel_id,
    }
    table = dict(store.get(NS_CHECKINS, {}) or {})
    table[str(user_id)] = entry
    await store.set(NS_CHECKINS, table)
    return entry


async def clear_checkin(store, user_id: int) -> bool:
    table = dict(store.get(NS_CHECKINS, {}) or {})
    if str(user_id) not in table:
        return False
    table.pop(str(user_id), None)
    await store.set(NS_CHECKINS, table)
    return True


def remaining_seconds(entry: dict) -> int:
    return int(entry.get("due", 0)) - int(time.time())


# ── profile (optional context included in alerts) ────────────────────────────
def get_profile(store, user_id: int) -> dict:
    table = store.get(NS_PROFILE, {}) or {}
    return dict(table.get(str(user_id), {}))


async def set_profile(store, user_id: int, note: str) -> None:
    table = dict(store.get(NS_PROFILE, {}) or {})
    table[str(user_id)] = {"note": (note or "").strip()[:MAX_NOTE]}
    await store.set(NS_PROFILE, table)


# ── alert text ───────────────────────────────────────────────────────────────
def alert_text(display_name: str, *, kind: str, note: str = "", minutes: int = 0,
               profile_note: str = "") -> str:
    """Compose the message sent to a trusted contact. `kind` is 'overdue' or 'sos'."""
    if kind == "sos":
        head = f"🚨 **SOS from {display_name}** — they triggered an emergency alert just now."
    else:
        head = (f"⚠️ **Safety alert about {display_name}** — they started a {minutes}-minute "
                f"safety check-in and did not mark themselves safe in time.")
    lines = [head, "", f"{display_name} added you as a trusted safety contact. they may need help — "
             "consider reaching out to them directly, and contact local emergency services if you "
             "believe they're in danger."]
    if note:
        lines.append(f"\ntheir note: {note}")
    if profile_note:
        lines.append(f"context they saved: {profile_note}")
    return "\n".join(lines)
