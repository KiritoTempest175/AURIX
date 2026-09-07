"""AURIX AI Brain — Central Intelligence Package.

Houses all brain-level autonomous capabilities: app control, shell execution,
and future cognitive modules. The BrainDispatcher is the single entry point
used by frontend.py to route user intents.
"""

from ai_brain.dispatcher import BrainDispatcher

__all__ = ["BrainDispatcher"]
