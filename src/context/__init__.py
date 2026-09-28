"""Context directory manager — ensures the storage structure exists and provides paths.

The context directory holds all persistent data:
  - ``graph.db`` — SQLite graph database (symbols, edges, chunks, metadata).
  - ``chunks.db`` — reserved (currently co-located in graph.db).
  - ``session.db`` — session-based personalisation events.
  - ``audit.db`` — append-only audit log.
  - ``vectors.bin`` / ``vectors.meta.json`` — binary vector index + metadata.
  - ``index.lock`` — filesystem lock for exclusive indexing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from src.engine.config import Settings

logger = logging.getLogger(__name__)


class ContextManager:
    """Ensures the context directory structure exists and exposes its paths.

    The context directory is the single root for all persistent data. Call
    :meth:`ensure` once before accessing :attr:`context_dir`, :attr:`paths`, or
    :meth:`get_path`.

    Attributes:
        SUB_DATABASES: Mapping of logical database name to its file name
            relative to the context directory.
    """

    SUB_DATABASES: ClassVar[dict[str, str]] = {
        "graph": "graph.db",
        "chunks": "chunks.db",
        "session": "session.db",
        "audit": "audit.db",
    }

    def __init__(self, settings: Settings | None = None) -> None:
        """Create a context manager backed by the given settings.

        Args:
            settings: Runtime settings; defaults to
                :func:`src.engine.config.Settings.from_env` when omitted.
        """
        self._settings = settings or Settings.from_env()
        self._context_dir: Path | None = None
        self._paths: dict[str, Path] = {}

    def ensure(self) -> Path:
        """Create the context directory and all sub-directories, then cache paths.

        Idempotent: existing directories are left untouched. After this call
        the paths for every database in :attr:`SUB_DATABASES`, plus the vector
        index files (``vectors.bin`` / ``vectors.meta.json``) and the index
        lock (``index.lock``), are available via :attr:`paths` and
        :meth:`get_path`.

        Returns:
            The resolved context directory path.
        """
        context_dir = self._settings.resolve_context_dir()
        self._context_dir = context_dir

        sub_dirs = [context_dir]
        for _name, _rel_path in self.SUB_DATABASES.items():
            sub_dirs.append(
                context_dir / Path(_rel_path).parent
                if Path(_rel_path).parent != Path()
                else context_dir
            )

        for d in set(sub_dirs):
            d.mkdir(parents=True, exist_ok=True)

        for name, rel_path in self.SUB_DATABASES.items():
            self._paths[name] = context_dir / rel_path

        self._paths["vectors_bin"] = context_dir / "vectors.bin"
        self._paths["vectors_meta"] = context_dir / "vectors.meta.json"
        self._paths["lock"] = context_dir / "index.lock"

        logger.debug("Context directory ensured at %s", context_dir)
        return context_dir

    @property
    def context_dir(self) -> Path:
        """The resolved context directory path.

        Raises:
            RuntimeError: If :meth:`ensure` has not been called yet.
        """
        if self._context_dir is None:
            raise RuntimeError("Context directory not initialized. Call ensure() first.")
        return self._context_dir

    @property
    def paths(self) -> dict[str, Path]:
        """A copy of the cached path mapping (name to file path).

        Raises:
            RuntimeError: If :meth:`ensure` has not been called yet.
        """
        if not self._paths:
            raise RuntimeError("Context directory not initialized. Call ensure() first.")
        return dict(self._paths)

    def get_path(self, key: str) -> Path:
        """Return the cached path for the given logical name.

        Args:
            key: A logical path name such as ``"graph"`` or ``"lock"``.

        Returns:
            The cached file path for *key*.

        Raises:
            KeyError: If *key* is not a known context path name.
        """
        path = self._paths.get(key)
        if path is None:
            raise KeyError(f"Unknown context path key: {key}")
        return path
