from datetime import datetime, timezone
from uuid import uuid4

from .models import AgentTrace, ExperimentPlan, PlanRequest, TraceEvent


class AgentTraceStore:
    def __init__(self) -> None:
        self._traces: dict[str, AgentTrace] = {}

    def create(self, request: PlanRequest, plan: ExperimentPlan, owner_user_id: int) -> AgentTrace:
        trace_id = str(uuid4())
        trace = AgentTrace(
            trace_id=trace_id,
            owner_user_id=owner_user_id,
            request=request,
            plan=plan,
        )
        self._traces[trace_id] = trace
        return trace

    def get(self, trace_id: str) -> AgentTrace | None:
        return self._traces.get(trace_id)

    def append(self, trace_id: str, event_type: str, payload: dict) -> TraceEvent:
        trace = self._traces[trace_id]
        event = TraceEvent(
            event_id=str(uuid4()),
            trace_id=trace_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        trace.events.append(event)
        return event

    def update(self, trace_id: str, **changes) -> AgentTrace:
        trace = self._traces[trace_id]
        for key, value in changes.items():
            setattr(trace, key, value)
        return trace


trace_store = AgentTraceStore()
