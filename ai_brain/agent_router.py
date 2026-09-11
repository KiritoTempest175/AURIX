"""AURIX Intelligent Agent Router."""

from __future__ import annotations

import logging
from typing import Optional, Tuple

from ai_brain.tool_executor import ToolExecutor
from ai_engine.inference.gemma_e4b import (
    GemmaModelRunner,
    get_default_gemma_runner,
)

logger = logging.getLogger(
    "aurix.ai_brain.agent_router"
)


class AgentRouter:
    """LLM-first natural language router.

    User language does NOT have to match fixed command syntax.

    Example:

        "could you open chrome for me"

    becomes:

        {
            "tool": "open_app",
            "args": {
                "target": "chrome"
            }
        }

    The router:
        1. Understands user intent with the LLM.
        2. Selects an AURIX tool when required.
        3. Sends physical actions through ToolExecutor.
        4. Stores successful tool interactions in clean conversation memory.
        5. Falls back to normal LLM conversation when no tool is required.
    """

    def __init__(
        self,
        executor: Optional[ToolExecutor] = None,
        model_runner: Optional[GemmaModelRunner] = None,
    ) -> None:

        self.executor = (
            executor or ToolExecutor()
        )

        # Keep model loading lazy.
        # This prevents the LLM from loading during basic imports/tests
        # unless it is actually required.
        self._runner = model_runner

    # ============================================================
    # MODEL
    # ============================================================

    @property
    def runner(self) -> GemmaModelRunner:
        """Return the shared AURIX reasoning model."""

        if self._runner is None:

            self._runner = (
                get_default_gemma_runner()
            )

        return self._runner

    # ============================================================
    # MAIN ROUTING
    # ============================================================

    def route(
        self,
        text: str,
    ) -> Tuple[str, bool]:
        """Understand a user request and either answer or execute a tool."""

        if not text or not text.strip():
            return "", False

        clean_text = text.strip()

        # --------------------------------------------------------
        # STEP 1:
        # Ask the LLM what the user actually wants.
        # --------------------------------------------------------

        try:

            decision = self.runner.select_tool(
                clean_text
            )

        except Exception as exc:

            logger.exception(
                "Tool selection failed: %s",
                exc,
            )

            # If routing itself fails, do not lose the user's request.
            # Fall back to normal conversation.
            return (
                self._general_answer(clean_text),
                True,
            )

        # Defensive validation.
        if not isinstance(decision, dict):

            logger.warning(
                "Tool selector returned invalid type: %s",
                type(decision).__name__,
            )

            return (
                self._general_answer(clean_text),
                True,
            )

        tool_name = str(
            decision.get("tool", "")
        ).strip()

        args = decision.get(
            "args",
            {},
        )

        if not isinstance(args, dict):
            args = {}

        logger.info(
            "Agent decision: tool=%s args=%s",
            tool_name,
            args,
        )

        # --------------------------------------------------------
        # STEP 2:
        # Normal reasoning / conversation
        # --------------------------------------------------------

        if (
            not tool_name
            or tool_name == "general_answer"
        ):

            return (
                self._general_answer(clean_text),
                True,
            )

        # --------------------------------------------------------
        # STEP 3:
        # Execute a physical computer action
        # --------------------------------------------------------

        if self.executor.supports(
            tool_name
        ):

            try:

                result = self.executor.execute(
                    tool_name,
                    args,
                )

            except Exception as exc:

                logger.exception(
                    "Tool execution failed: tool=%s error=%s",
                    tool_name,
                    exc,
                )

                result = (
                    f"I understood the request, but the "
                    f"{tool_name} action failed: {exc}"
                )

            # ----------------------------------------------------
            # IMPORTANT:
            # Tool responses do not pass through runner.chat().
            #
            # Therefore we manually store the clean interaction
            # so follow-up references still make sense.
            #
            # Example:
            #
            # User: Open Chrome
            # AURIX: Chrome opened.
            #
            # User: Now close it
            #
            # The model can infer "it" = Chrome.
            # ----------------------------------------------------

            if not result.startswith("TRUST_TOKEN_REQUIRED:"):
                self._remember_tool_exchange(
                    user_message=clean_text,
                    assistant_message=result,
                )

            return result, True

        # --------------------------------------------------------
        # Unknown tool safety fallback
        # --------------------------------------------------------

        logger.warning(
            "Model selected unsupported tool '%s'",
            tool_name,
        )

        return (
            self._general_answer(clean_text),
            True,
        )

    # ============================================================
    # CONVERSATION
    # ============================================================

    def _general_answer(
        self,
        text: str,
    ) -> str:
        """Generate a normal conversational answer."""

        try:

            return self.runner.chat(
                user_message=text
            )

        except Exception as exc:

            logger.exception(
                "General reasoning failed: %s",
                exc,
            )

            return (
                "I couldn't complete the reasoning "
                "request because the local model "
                "encountered an error."
            )

    # ============================================================
    # MEMORY
    # ============================================================

    def _remember_tool_exchange(
        self,
        user_message: str,
        assistant_message: str,
    ) -> None:
        """Store successful tool/action interactions in chat history.

        runner.chat() automatically stores normal conversation.

        Tool actions bypass runner.chat(), so without this method they
        would disappear from short-term context.
        """

        try:

            remember = getattr(
                self.runner,
                "remember_exchange",
                None,
            )

            if callable(remember):

                remember(
                    user_message=user_message,
                    assistant_message=str(
                        assistant_message
                    ),
                )

            else:

                logger.debug(
                    "GemmaModelRunner does not provide "
                    "remember_exchange(); tool interaction "
                    "will not be added to conversation history."
                )

        except Exception as exc:

            # Memory failure must NEVER prevent an action result
            # from being returned to the user.
            logger.warning(
                "Could not record tool exchange: %s",
                exc,
            )