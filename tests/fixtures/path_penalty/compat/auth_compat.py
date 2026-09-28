def require_valid_session(session: dict) -> None:
    """Compat shim mirroring the production middleware."""
    if not session.get("active", False):
        raise ValueError("session is not active")
