"""Conversation state + the context resolver.

Every conversation (a Discord channel) has its own isolated intelligence state
(§6). This state is EPHEMERAL by design: it improves the current conversation but
does NOT automatically become user memory, project memory, or global knowledge —
that only happens through the learning gate + promotion gate. So conversation
state lives in memory, keyed by channel id, and is pruned when idle. Nothing here
writes to the durable store.

The ContextResolver assembles the runtime context for a model call by pulling only
the RELEVANT slices of each layer and ranking them (§46 — relevant intelligence,
not maximum volume).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class ConversationContext:
    """Per-channel working state (spec's conversation_context, §6)."""
    conversation_id: int                 # channel id
    project_id: int = 0                  # guild id
    goal: str = ""
    active_topic: str = ""
    decisions: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    preferences_observed: list[str] = field(default_factory=list)
    patterns_used: list[str] = field(default_factory=list)
    patterns_created: list[str] = field(default_factory=list)
    patterns_rejected: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    confidence: float = 0.5
    updated_at: float = field(default_factory=time.time)

    def note_decision(self, text: str) -> None:
        text = text.strip()
        if text and text not in self.decisions:
            self.decisions.append(text)
            self.decisions = self.decisions[-15:]
        self.updated_at = time.time()

    def note_preference(self, text: str) -> None:
        text = text.strip()
        if text and text not in self.preferences_observed:
            self.preferences_observed.append(text)
            self.preferences_observed = self.preferences_observed[-15:]
        self.updated_at = time.time()

    def used_pattern(self, pattern_id: str) -> None:
        if pattern_id and pattern_id not in self.patterns_used:
            self.patterns_used.append(pattern_id)
            self.patterns_used = self.patterns_used[-25:]
        self.updated_at = time.time()

    def as_prompt_block(self) -> str:
        """A compact summary for injection — only non-empty slices."""
        lines: list[str] = []
        if self.goal:
            lines.append(f"goal: {self.goal}")
        if self.active_topic:
            lines.append(f"active topic: {self.active_topic}")
        if self.decisions:
            lines.append("decisions so far: " + "; ".join(self.decisions[-5:]))
        if self.constraints:
            lines.append("constraints: " + "; ".join(self.constraints[-5:]))
        if self.preferences_observed:
            lines.append("preferences noticed this convo: " + "; ".join(self.preferences_observed[-5:]))
        if self.unresolved_questions:
            lines.append("open questions: " + "; ".join(self.unresolved_questions[-3:]))
        return "\n".join(lines)


class ConversationStore:
    """In-memory registry of conversation contexts, pruned when idle. Ephemeral on
    purpose — conversation learning is not persisted here (§6)."""

    def __init__(self, ttl_seconds: int = 3600, max_conversations: int = 500) -> None:
        self._ttl = ttl_seconds
        self._max = max_conversations
        self._contexts: dict[int, ConversationContext] = {}

    def get(self, conversation_id: int, project_id: int = 0) -> ConversationContext:
        self._prune()
        ctx = self._contexts.get(conversation_id)
        if ctx is None:
            ctx = ConversationContext(conversation_id=conversation_id, project_id=project_id)
            self._contexts[conversation_id] = ctx
        elif project_id and not ctx.project_id:
            ctx.project_id = project_id
        return ctx

    def _prune(self) -> None:
        now = time.time()
        stale = [cid for cid, c in self._contexts.items() if now - c.updated_at > self._ttl]
        for cid in stale:
            self._contexts.pop(cid, None)
        if len(self._contexts) > self._max:
            # drop the oldest beyond the cap
            for cid, _c in sorted(self._contexts.items(), key=lambda kv: kv[1].updated_at)[:-self._max]:
                self._contexts.pop(cid, None)


@dataclass
class ResolvedContext:
    """What the resolver hands the orchestrator: the relevant slices, already ranked
    and size-bounded, plus the patterns it retrieved (so outcomes can be recorded)."""
    conversation_block: str = ""
    user_memory: list[str] = field(default_factory=list)
    project_memory: list[str] = field(default_factory=list)
    patterns: list = field(default_factory=list)          # list[Pattern]
    global_patterns: list = field(default_factory=list)   # list[Pattern]

    def to_prompt(self) -> str:
        """Render the resolved context as a compact prompt block (only non-empty
        parts). Patterns are rendered as their mechanism, flagged by status so the
        model treats a candidate as a hypothesis, not a rule (§13)."""
        from core.intelligence.pattern import PatternStatus  # local import avoids cycle

        blocks: list[str] = []
        if self.conversation_block:
            blocks.append("CONVERSATION STATE:\n" + self.conversation_block)
        if self.user_memory:
            blocks.append("WHAT YOU REMEMBER ABOUT THIS PERSON:\n"
                          + "\n".join(f"- {m}" for m in self.user_memory))
        if self.project_memory:
            blocks.append("WHAT YOU KNOW ABOUT THIS SERVER:\n"
                          + "\n".join(f"- {m}" for m in self.project_memory))
        applied = self.patterns + self.global_patterns
        if applied:
            rendered = []
            for p in applied:
                tag = "PROVEN" if p.status in {PatternStatus.ACTIVE, PatternStatus.REFINED} else \
                      "VALIDATED" if p.status is PatternStatus.VALIDATED else "HYPOTHESIS (unproven)"
                scope = f"[{p.scope}]"
                rendered.append(f"- {scope} {tag}: {p.name} — {p.mechanism}")
            blocks.append(
                "PROBLEM-SOLVING PATTERNS THAT MAY APPLY (use PROVEN ones; treat "
                "HYPOTHESIS ones as tentative, and prefer local context if they conflict):\n"
                + "\n".join(rendered))
        return "\n\n".join(blocks)
