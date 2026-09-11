"""AURIX Central Brain Dispatcher.

Phase 1:
Natural Language -> Agent Router -> Tool Executor -> Permission Layer
"""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from ai_brain.agent_router import AgentRouter
from ai_brain.tool_executor import ToolExecutor

logger = logging.getLogger(
    "aurix.ai_brain.dispatcher"
)


class BrainDispatcher:

    _WAKE_PHRASES = {
        "luna",
        "hey luna",
        "aurix",
        "hey aurix",
        "hello luna",
        "hello aurix",
        "wake up",
    }

    def __init__(
        self,
        model_runner=None,
    ) -> None:

        self.executor = ToolExecutor()

        self.router = AgentRouter(
            executor=self.executor,
            model_runner=model_runner,
        )

        logger.info(
            "AURIX intelligent BrainDispatcher initialized."
        )

    def dispatch(
        self,
        text: str,
    ) -> Tuple[str, bool]:

        if not text or not text.strip():
            return "", False

        clean = text.strip()

        lower = clean.lower().rstrip(
            ".,!?"
        )

        # Wake phrases are deterministic because
        # calling an LLM here would be unnecessary.
        if lower in self._WAKE_PHRASES:

            return (
                "AURIX Executive online. I'm listening.",
                True,
            )

        return self.router.route(
            clean
        )

    def execute_trust_token(
        self,
        request: str,
    ) -> str:
        """Called by frontend after user approval."""

        return self.executor.confirm_pending(
            request
        )