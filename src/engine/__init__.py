"""code-search engine — AI code context engine for air-gapped enterprise environments.

Provides local, privacy-preserving code search and navigation through
AST-based indexing, hybrid (BM25 + vector) retrieval, session-aware
reranking, and an audit-graded compliance layer.
"""

VERSION = "0.1.0"

__version__ = VERSION

__all__ = [
    "VERSION",
    "__version__",
]
