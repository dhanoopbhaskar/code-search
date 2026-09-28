"""Utility helpers — a module-level duplicate of getBySlug."""

from models import Article


def getBySlug(slug: str) -> Article:
    return Article(slug)


def unused_helper() -> None:
    """A symbol nobody calls — no recorded callers/callees."""
    pass
