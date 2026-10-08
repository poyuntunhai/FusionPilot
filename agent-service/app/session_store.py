"""
In-memory index of live agent sessions, with the Java store as the durable copy.

Sessions are saved after every turn, so this cache only holds conversations that are being worked
on right now. Anything evicted or lost on restart is rehydrated from storage on demand, which is
why eviction here is not a data-loss event.
"""

from __future__ import annotations

from uuid import uuid4

from .conversation import now_iso
from .domain_tools import CONFIG_SUMMARY_KEYS
from .models import AgentSession, AgentSessionSummary


MAX_LIVE_SESSIONS = 100
TITLE_LIMIT = 80


class AgentSessionStore:
    def __init__(self) -> None:
        self._sessions: dict[str, AgentSession] = {}

    def create(
        self,
        owner_user_id: int,
        default_config: dict,
        auto_approve: bool = False,
        provider: str = "rule",
        model: str | None = None,
        memory: str = "",
    ) -> AgentSession:
        session_id = str(uuid4())
        now = now_iso()
        session = AgentSession(
            session_id=session_id,
            owner_user_id=owner_user_id,
            title="New conversation",
            provider=provider,
            model=model,
            auto_approve=auto_approve,
            memory=memory,
            working_config=dict(default_config),
            default_config=dict(default_config),
            created_at=now,
            updated_at=now,
        )
        self._sessions[session_id] = session
        self._evict_if_needed()
        return session

    def get(self, session_id: str) -> AgentSession | None:
        return self._sessions.get(session_id)

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def drop_for_user(self, owner_user_id: int) -> None:
        """Used by tests to start from a clean slate without reaching into the dict."""
        for session_id in [
            item.session_id
            for item in self._sessions.values()
            if item.owner_user_id == owner_user_id
        ]:
            self._sessions.pop(session_id, None)

    def restore(self, session: AgentSession) -> AgentSession:
        self._sessions[session.session_id] = session
        return session

    def list_for_user(self, owner_user_id: int) -> list[AgentSessionSummary]:
        matching = [
            session for session in self._sessions.values() if session.owner_user_id == owner_user_id
        ]
        matching.sort(key=lambda item: item.updated_at, reverse=True)
        return [summarize(session) for session in matching]

    def update(
        self,
        session_id: str,
        default_config: dict,
        auto_approve: bool,
        provider: str | None = None,
        model: str | None = None,
    ) -> AgentSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        session.auto_approve = auto_approve
        if provider:
            session.provider = provider
        if model:
            session.model = model
        if not session.default_config:
            session.default_config = dict(default_config)
        session.updated_at = now_iso()
        return session

    def _evict_if_needed(self) -> None:
        if len(self._sessions) <= MAX_LIVE_SESSIONS:
            return
        for session in sorted(self._sessions.values(), key=lambda item: item.updated_at)[
            : len(self._sessions) - MAX_LIVE_SESSIONS
        ]:
            if session.pending is None:
                self._sessions.pop(session.session_id, None)


def set_title_from(session: AgentSession, text: str) -> None:
    """Name a conversation after its opening question, once."""
    if session.title != "New conversation":
        return
    flat = " ".join(text.split())
    if not flat:
        return
    session.title = flat[:TITLE_LIMIT] if len(flat) > TITLE_LIMIT else flat


def summarize(session: AgentSession) -> AgentSessionSummary:
    config = session.working_config
    parts: list[str] = []
    if "targetCount" in config:
        parts.append(f"{config['targetCount']} targets")
    if "simulationSteps" in config:
        parts.append(f"{config['simulationSteps']} steps")
    if config.get("schedulingPolicy"):
        parts.append(str(config["schedulingPolicy"]))
    if config.get("fusionMethod"):
        parts.append(str(config["fusionMethod"]))
    model_label = f"{session.provider}:{session.model}" if session.model else session.provider
    return AgentSessionSummary(
        session_id=session.session_id,
        title=session.title,
        status=session.status,
        provider=model_label,
        model=session.model,
        message_count=len(session.messages),
        tool_call_count=session.tool_call_count,
        working_summary=" \u00b7 ".join(parts),
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


session_store = AgentSessionStore()
