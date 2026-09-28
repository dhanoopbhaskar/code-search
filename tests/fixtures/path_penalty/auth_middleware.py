def require_valid_session(session: dict) -> None:
    """Reject requests that carry an expired or absent caller session."""
    if not session.get("active", False):
        raise ValueError("session is not active")
