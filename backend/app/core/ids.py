"""Prefixed ID generation utilities."""

import secrets


def generate_id(prefix: str) -> str:
    """Generate an entity ID with prefix and 16 lowercase hex characters.
    
    Example: prj_0123456789abcdef
    """
    return f"{prefix}_{secrets.token_hex(8)}"


def generate_request_id() -> str:
    """Generate a request ID with 12 lowercase hex characters.
    
    Example: req_0123456789ab
    """
    return f"req_{secrets.token_hex(6)}"

