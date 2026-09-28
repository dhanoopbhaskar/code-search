def verify_credentials(session: dict) -> bool:
    """Check that a caller session is still valid before serving requests."""
    return session.get("active", False)
