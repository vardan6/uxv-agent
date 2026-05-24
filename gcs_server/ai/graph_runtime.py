from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

try:
    from gcs_server.ai.context_service import AIContextService
    from gcs_server.ai.intent_service import IntentService
    from gcs_server.ai.mission_draft_service import MissionDraftService
    from gcs_server.ai.session_store import AISessionStore
    from gcs_server.ai.tool_registry import ToolRegistry
except ModuleNotFoundError:
    from ai.context_service import AIContextService
    from ai.intent_service import IntentService
    from ai.mission_draft_service import MissionDraftService
    from ai.session_store import AISessionStore
    from ai.tool_registry import ToolRegistry


@dataclass(frozen=True)
class PlanningShellGraphRuntime:
    """Immutable service container passed via LangGraph config['configurable'].

    Service handles and database connections are kept outside graph state so
    they are never serialized into checkpoints. Optional fields remain None
    until the corresponding phase is implemented.
    """

    app_runtime: Any
    tool_registry: ToolRegistry
    context_service: AIContextService
    intent_service: IntentService
    draft_service: MissionDraftService
    ai_session_store: AISessionStore
    secret_resolver: Callable[[str], str]

    # Phase 2+ — None falls back to REST-only approval (no interrupt/resume)
    checkpointer: Any | None = None
    trace_store: Any | None = None

    # Phase 4+ — None until RAG and settings-reader are implemented
    rag_service: Any | None = None
    settings_reader: Any | None = None

    # Phase 6+ — None until perception/video-frame understanding exists
    perception_service: Any | None = None
