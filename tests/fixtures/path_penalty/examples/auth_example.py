def verify_credentials(session: dict) -> bool:
    """Example twin of the production auth helper."""
    return session.get("active", False)
