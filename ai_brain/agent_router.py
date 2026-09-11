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

    Responsibilities:
        1. Understand natural-language requests using the LLM.
        2. Detect incomplete/ambiguous action commands.
        3. Ask clarification instead of inventing missing targets.
        4. Keep short pending-action context for follow-up answers.
        5. Select AURIX tools when physical actions are needed.
        6. Send all physical actions through ToolExecutor.
        7. Store successful tool interactions in clean conversation memory.
        8. Fall back to normal LLM conversation when no tool is required.
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
        # The model is only loaded when it is actually needed.
        self._runner = model_runner

        # --------------------------------------------------------
        # Pending clarification state
        #
        # Example:
        #
        # User: open
        # AURIX: What would you like me to open?
        #
        # User: Chrome
        #
        # Internally becomes:
        # "open Chrome"
        # --------------------------------------------------------

        self._pending_action: Optional[str] = None

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
        # STEP 0:
        # Handle pending clarification.
        # --------------------------------------------------------

        clean_text, pending_response = (
            self._handle_pending_action(
                clean_text
            )
        )

        if pending_response is not None:
            return pending_response, True

        # --------------------------------------------------------
        # STEP 0.5:
        # Prevent the model from inventing targets for incomplete
        # commands such as:
        #
        # "open"
        # "delete"
        # "close"
        #
        # Instead AURIX asks the user for the missing information.
        # --------------------------------------------------------

        clarification = (
            self._check_ambiguous_command(
                clean_text
            )
        )

        if clarification is not None:

            pending_action, prompt = clarification

            self._pending_action = (
                pending_action
            )

            logger.info(
                "Incomplete action detected: %s",
                clean_text,
            )

            return prompt, True

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

            # Routing failure should never lose the user's request.
            return (
                self._general_answer(
                    clean_text
                ),
                True,
            )

        # --------------------------------------------------------
        # Defensive validation
        # --------------------------------------------------------

        if not isinstance(
            decision,
            dict,
        ):

            logger.warning(
                "Tool selector returned invalid type: %s",
                type(decision).__name__,
            )

            return (
                self._general_answer(
                    clean_text
                ),
                True,
            )

        tool_name = str(
            decision.get(
                "tool",
                "",
            )
        ).strip()

        args = decision.get(
            "args",
            {},
        )

        if not isinstance(
            args,
            dict,
        ):
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
                self._general_answer(
                    clean_text
                ),
                True,
            )

        # --------------------------------------------------------
        # STEP 3:
        # Execute a physical computer action.
        # --------------------------------------------------------

        if self.executor.supports(
            tool_name
        ):

            try:

                result = (
                    self.executor.execute(
                        tool_name,
                        args,
                    )
                )

            except Exception as exc:

                logger.exception(
                    "Tool execution failed: "
                    "tool=%s error=%s",
                    tool_name,
                    exc,
                )

                result = (
                    "I understood the request, "
                    f"but the {tool_name} action "
                    f"failed: {exc}"
                )

            # ----------------------------------------------------
            # Tool responses bypass runner.chat().
            #
            # Store successful/normal tool interactions manually
            # so follow-up context remains available.
            #
            # We intentionally do NOT store the temporary
            # TRUST_TOKEN_REQUIRED response.
            # ----------------------------------------------------

            if not str(result).startswith(
                "TRUST_TOKEN_REQUIRED:"
            ):

                self._remember_tool_exchange(
                    user_message=clean_text,
                    assistant_message=str(
                        result
                    ),
                )

            return str(result), True

        # --------------------------------------------------------
        # Unknown tool safety fallback
        # --------------------------------------------------------

        logger.warning(
            "Model selected unsupported tool '%s'",
            tool_name,
        )

        return (
            self._general_answer(
                clean_text
            ),
            True,
        )

    # ============================================================
    # AMBIGUITY / CLARIFICATION
    # ============================================================

    def _check_ambiguous_command(
        self,
        text: str,
    ) -> Optional[Tuple[str, str]]:
        """Detect incomplete action-only commands.

        Returns:

            (
                pending_action,
                clarification_prompt
            )

        or None when the request contains enough information.
        """

        normalized = (
            text
            .lower()
            .strip()
            .strip(" .!?")
        )

        ambiguous_commands = {

            # ====================================================
            # OPEN
            # ====================================================

            "open": (
                "open",
                "What would you like me to open?",
            ),

            "open app": (
                "open",
                "Which application would you like me to open?",
            ),

            "open application": (
                "open",
                "Which application would you like me to open?",
            ),

            "launch": (
                "open",
                "What would you like me to launch?",
            ),

            "launch app": (
                "open",
                "Which application would you like me to launch?",
            ),

            "start": (
                "open",
                "What would you like me to start?",
            ),

            # Roman Urdu

            "khol": (
                "open",
                "Kya open karna hai?",
            ),

            "khol do": (
                "open",
                "Kya open karna hai?",
            ),

            "open karo": (
                "open",
                "Kya open karna hai?",
            ),

            # ====================================================
            # CLOSE
            # ====================================================

            "close": (
                "close",
                "What would you like me to close?",
            ),

            "close app": (
                "close",
                "Which application would you like me to close?",
            ),

            "close application": (
                "close",
                "Which application would you like me to close?",
            ),

            "exit": (
                "close",
                "Which application would you like me to close?",
            ),

            # Roman Urdu

            "band karo": (
                "close",
                "Konsi application band karni hai?",
            ),

            "close karo": (
                "close",
                "Konsi application close karni hai?",
            ),

            # ====================================================
            # DELETE
            # ====================================================

            "delete": (
                "delete",
                "What would you like me to delete?",
            ),

            "delete file": (
                "delete",
                "Which file would you like me to delete?",
            ),

            "remove": (
                "delete",
                "What would you like me to remove?",
            ),

            "remove file": (
                "delete",
                "Which file would you like me to remove?",
            ),

            # Roman Urdu

            "delete karo": (
                "delete",
                "Konsi file ya folder delete karna hai?",
            ),

            "remove karo": (
                "delete",
                "Konsi file ya folder remove karna hai?",
            ),

            # ====================================================
            # RENAME
            # ====================================================

            "rename": (
                "rename",
                "What would you like me to rename?",
            ),

            "rename file": (
                "rename",
                "Which file would you like me to rename?",
            ),

            "rename karo": (
                "rename",
                "Konsi file ya folder rename karna hai?",
            ),

            # ====================================================
            # MOVE
            # ====================================================

            "move": (
                "move",
                "What would you like me to move?",
            ),

            "move file": (
                "move",
                "Which file would you like me to move?",
            ),

            "move karo": (
                "move",
                "Konsi file ya folder move karna hai?",
            ),

            # ====================================================
            # COPY
            # ====================================================

            "copy": (
                "copy",
                "What would you like me to copy?",
            ),

            "copy file": (
                "copy",
                "Which file would you like me to copy?",
            ),

            "copy karo": (
                "copy",
                "Konsi file ya folder copy karna hai?",
            ),

            # ====================================================
            # READ
            # ====================================================

            "read": (
                "read",
                "What would you like me to read?",
            ),

            "read file": (
                "read",
                "Which file would you like me to read?",
            ),

            "parho": (
                "read",
                "Konsi file read karni hai?",
            ),

            # ====================================================
            # WRITE
            # ====================================================

            "write": (
                "write",
                "What would you like me to write?",
            ),

            "write file": (
                "write",
                "Which file would you like me to write to?",
            ),

            # ====================================================
            # CREATE
            # ====================================================

            "create": (
                "create",
                "What would you like me to create?",
            ),

            "create file": (
                "create file",
                "What file would you like me to create?",
            ),

            "create folder": (
                "create folder",
                "What folder would you like me to create?",
            ),

            # ====================================================
            # PLAY
            # ====================================================

            "play": (
                "play",
                "What would you like me to play?",
            ),

            "play music": (
                "play",
                "What music would you like me to play?",
            ),

            "play song": (
                "play",
                "Which song would you like me to play?",
            ),

            # ====================================================
            # SEARCH
            # ====================================================

            "search": (
                "search",
                "What would you like me to search for?",
            ),

            "search web": (
                "search",
                "What would you like me to search for?",
            ),

            "google": (
                "search",
                "What would you like me to search for?",
            ),

            # ====================================================
            # CALL
            # ====================================================

            "call": (
                "make whatsapp call to",
                "Who would you like me to call?",
            ),

            "make call": (
                "make whatsapp call to",
                "Who would you like me to call?",
            ),

            "whatsapp call": (
                "make whatsapp call to",
                "Who would you like me to call on WhatsApp?",
            ),

            "call karo": (
                "make whatsapp call to",
                "Kisko call karni hai?",
            ),

            # ====================================================
            # SEND
            # ====================================================

            "send": (
                "send",
                "What would you like me to send, and to whom?",
            ),

            "send message": (
                "send message to",
                "Who would you like me to message?",
            ),

            "send email": (
                "send email to",
                "Who would you like me to email?",
            ),

            "message": (
                "send message to",
                "Who would you like me to message?",
            ),
        }

        return ambiguous_commands.get(
            normalized
        )

    # ============================================================
    # PENDING FOLLOW-UP
    # ============================================================

    def _handle_pending_action(
        self,
        text: str,
    ) -> Tuple[
        str,
        Optional[str],
    ]:
        """Resolve a user's follow-up to a clarification question.

        Example:

            User:
                open

            AURIX:
                What would you like me to open?

            User:
                Chrome

        becomes internally:

            open Chrome
        """

        if not self._pending_action:

            return text, None

        normalized = (
            text
            .lower()
            .strip()
            .strip(" .!?")
        )

        cancel_words = {
            "cancel",
            "cancel it",
            "never mind",
            "nevermind",
            "stop",
            "no",
            "nope",
            "leave it",
            "forget it",

            # Roman Urdu
            "rehne do",
            "rehne doo",
            "rehna do",
            "rehna doo",
            "rehndo",
            "rehny do",
            "choro",
            "chor do",
            "chordo",
            "cancel karo",
            "nahi",
            "nai",
        }

        cancel_phrases = {
            "cancel",
            "never mind",
            "nevermind",
            "leave it",
            "forget it",
            "nothing",
            "stop",

            # Roman Urdu
            "rehne do",
            "rehndo",
            "rehny do",
            "choro",
            "chor do",
            "chordo",
            "cancel karo",
        }

        if (
            normalized in cancel_words
            or any(
                phrase in normalized
                for phrase in cancel_phrases
            )
        ):

            self._pending_action = None

            return (
                text,
                "Okay, cancelled.",
            )

        pending_action = (
            self._pending_action
        )

        # Clear before routing so stale actions cannot accidentally
        # affect future commands.
        self._pending_action = None

        combined_request = (
            f"{pending_action} {text}"
        ).strip()

        logger.info(
            "Resolved clarification: '%s'",
            combined_request,
        )

        return combined_request, None

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

        Tool actions bypass runner.chat(), so without this method
        they would disappear from short-term context.
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