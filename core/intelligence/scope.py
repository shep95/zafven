"""Scope — the mandatory isolation dimension for every learned item.

A learned item (memory or pattern) is never scope-less. Its scope decides who it
applies to and where it may travel. The spec's hard rule (§9) is that one scope is
NEVER silently converted into another: a USER preference does not become a PROJECT
fact, a PROJECT fact does not become GLOBAL knowledge. Promotion across scopes only
happens through an explicit, gated process (see memory.promote / globals).

zafven runs as a Discord bot, so the abstract scopes map to concrete Discord things:

    TASK          one command / one request (most ephemeral)
    CONVERSATION  one channel (or thread) of chat
    PROJECT       one guild (server)
    USER          one Discord user, across guilds
    DOMAIN        a topic/knowledge domain (a brain), independent of who/where
    GLOBAL        cross-guild, privacy-abstracted, validated knowledge (most durable)
"""
from __future__ import annotations

import enum


class Scope(enum.Enum):
    TASK = "task"
    CONVERSATION = "conversation"
    PROJECT = "project"
    USER = "user"
    DOMAIN = "domain"
    GLOBAL = "global"

    def __str__(self) -> str:  # so f-strings and JSON keys read as the value
        return self.value


# Ordered from most ephemeral / most local to most durable / most shared. Promotion
# moves UP this ladder (never down implicitly), and every step up is a gate.
LADDER: list[Scope] = [
    Scope.TASK,
    Scope.CONVERSATION,
    Scope.PROJECT,
    Scope.USER,
    Scope.DOMAIN,
    Scope.GLOBAL,
]


def rank(scope: Scope) -> int:
    """Position on the ladder (0 = most local). Higher = more durable/shared."""
    return LADDER.index(scope)


def parse(value: str | Scope | None, default: Scope = Scope.CONVERSATION) -> Scope:
    """Coerce a stored string / loose input into a Scope, never raising."""
    if isinstance(value, Scope):
        return value
    if not value:
        return default
    try:
        return Scope((value or "").strip().lower())
    except ValueError:
        return default


def is_promotion(from_scope: Scope, to_scope: Scope) -> bool:
    """True when moving from one scope to a strictly more durable/shared one."""
    return rank(to_scope) > rank(from_scope)


def crosses_privacy_boundary(from_scope: Scope, to_scope: Scope) -> bool:
    """True when a move would carry information toward GLOBAL — the point at which
    privacy abstraction is MANDATORY (§27). Anything landing at GLOBAL from a
    person- or guild-specific scope must be abstracted first, never copied raw."""
    return to_scope is Scope.GLOBAL and from_scope in {
        Scope.TASK, Scope.CONVERSATION, Scope.PROJECT, Scope.USER,
    }
