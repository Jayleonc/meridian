"""Compatibility shim for the Agent Chat API.

New code should import from `src.agent`.  This module stays temporarily so older
imports keep working while the Nexus Agent runtime is being split out.
"""

from src.agent import create_chat_router, get_chat_config

__all__ = ["create_chat_router", "get_chat_config"]
