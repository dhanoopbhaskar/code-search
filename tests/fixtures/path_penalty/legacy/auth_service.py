def verify_credentials(session: dict) -> bool:
    """Legacy twin kept for old callers."""
    return session.get("active", False)
