"""Vector embedding generation and flat-file vector index.

Provides EmbeddingGenerator (wrapping a Model2Vec StaticModel) for
converting code text into fixed-dimension dense vectors, and VectorIndex
for storing/searching those vectors on disk as a binary numpy array
paired with a JSON metadata sidecar.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import sysconfig
import threading
import time
from contextlib import suppress
from dataclasses import replace
from enum import StrEnum
from pathlib import Path
from typing import Any

import numpy as np

from src.engine.config import Settings
from src.engine.embed_representation import REPRESENTATION_SCHEME_VERSION

logger = logging.getLogger(__name__)

_warned_keys: set[str] = set()

#: ``index_metadata`` key holding the representation scheme that produced the
#: stored embeddings.
_REPRESENTATION_SCHEME_KEY = "representation_scheme_version"


class WarmupState(StrEnum):
    """Lifecycle state of the in-process embedding model.

    ``COLD`` means no load has started; ``WARMING`` a background load is in
    flight; ``WARM`` a usable model is in memory; ``FAILED`` the load raised;
    ``DISABLED`` the model is explicitly off (``--no-model``).
    """

    COLD = "cold"
    WARMING = "warming"
    WARM = "warm"
    FAILED = "failed"
    DISABLED = "disabled"


# Authoritative discriminators for the ranked response path. ``hybrid`` is the
# default fused path; ``lexical_reduced`` is the explicitly-labelled cold path
# served while the model warms; ``lexical_degraded`` is the existing fallback
# when the model is unavailable or disabled.
RANKED_PATH_HYBRID = "hybrid"
RANKED_PATH_LEXICAL_REDUCED = "lexical_reduced"
RANKED_PATH_LEXICAL_DEGRADED = "lexical_degraded"

#: Whether the opt-in ``fast`` model profile is shipped to users. Gated on a
#: measured tradeoff (``tests/evaluation/model_tradeoff_eval.py``): the
#: profile ships only if a local candidate reduces cold-load time by >= 40 %
#: while keeping P@5/MRR@10 within a 5 % relative delta of the default. No
#: candidate met the floors, so the profile is withheld rather than shipping a
#: quality-collapsing option.
FAST_PROFILE_SHIPPED = False


def _reset_warned_keys() -> None:
    """Clear the deduplicated model-load warnings (used by tests)."""
    _warned_keys.clear()


# Default model constants — overridable via Settings.embedding_model / embedding_dim.
MODEL_NAME = "potion-code-16m-32d"
EMBEDDING_DIM = 32
EMBEDDING_DTYPE = np.float32
EMBEDDING_BYTES = EMBEDDING_DIM * 4

_model_instance: object | None = None
_LOAD_FAILED_SENTINEL = object()
_LOADED_SENTINEL = object()
_loaded_model_path: str | None = None

_MODEL_LOAD_STATUS_KEY = "model_load_status"
_MODEL_LOAD_TIMESTAMP_KEY = "model_load_timestamp"
_MODEL_LOAD_PATH_KEY = "model_load_path"


def _get_user_base() -> Path:
    """Return the per-user base directory used by ``pip install --user``.

    Cross-platform: ``~/.local`` on Linux/macOS, ``%APPDATA%\\Python`` on
    Windows. The bundle installer places shared models under this base, so the
    runtime must agree on the same value.
    """
    base = sysconfig.get_config_var("userbase")
    if base:
        return Path(base)
    return Path.home() / ".local"


def _find_local_model_path(model_name: str, context_dir: Path | None = None) -> Path | None:
    """Search known local paths for a saved model directory.

    Returns the first path that exists, or *None* if no local copy is found.
    Search order:
      1. ``CODE_SEARCH_MODEL_PATH`` env var directly (if set)
      2. ``./models/{model_name}`` relative to current directory
      3. ``.context/models/{model_name}``
      4. Parent-of-context-dir: ``{context_dir.parent}/models/{model_name}``
      5. Walk-up-from-CWD: starting from ``Path.cwd()``, walk up looking for
         ``models/<model_name>``
      6. ``CODE_SEARCH_DATA_DIR`` env var: ``$CODE_SEARCH_DATA_DIR/models/{model_name}``
      7. ``../models/{model_name}`` relative to the installed binary location
      8. Install-wide share dirs: ``{sys.prefix}/share/code-search/models/`` and
         ``{pip --user base}/share/code-search/models/`` (populated by the bundle installer)
      9. Package-relative ``models/`` next to the installed ``src`` tree
         (covers editable installs of this repo)
      10. Hugging Face cache (``~/.cache/huggingface/hub/``)
    """
    env_path = os.environ.get("CODE_SEARCH_MODEL_PATH")
    if env_path:
        p = Path(env_path)
        if p.is_dir():
            return p
        candidate = p / model_name
        if candidate.is_dir():
            return candidate

    candidates = [
        Path.cwd() / "models" / model_name,
        Path.cwd() / ".context" / "models" / model_name,
    ]

    if context_dir is not None:
        ctx_path = Path(context_dir) if isinstance(context_dir, str) else context_dir
        candidates.append(ctx_path.parent / "models" / model_name)

    current = Path.cwd()
    for _ in range(10):
        candidate = current / "models" / model_name
        if candidate.is_dir():
            candidates.append(candidate)
            break
        parent = current.parent
        if parent == current:
            break
        current = parent

    data_dir = os.environ.get("CODE_SEARCH_DATA_DIR")
    if data_dir:
        candidates.append(Path(data_dir) / "models" / model_name)

    binary_path = _get_binary_dir()
    if binary_path is not None:
        candidates.append(binary_path / ".." / "models" / model_name)

    for prefix in (Path(sys.prefix), _get_user_base()):
        candidates.append(prefix / "share" / "code-search" / "models" / model_name)

    candidates.append(Path(__file__).resolve().parents[2] / "models" / model_name)

    for c in candidates:
        if c.is_dir():
            return c

    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    if hf_cache.is_dir():
        model_folder = f"models--{model_name.replace('/', '--')}"
        snapshots_dir = hf_cache / model_folder / "snapshots"
        if snapshots_dir.is_dir():
            snapshots = sorted(snapshots_dir.iterdir())
            if snapshots:
                return snapshots[-1]

    return None


def _get_binary_dir() -> Path | None:
    """Return the directory containing the installed binary, or None."""
    try:
        binary = Path(sys.argv[0])
        if binary.is_file() and binary.parent.is_dir():
            return binary.parent.resolve()
    except Exception:
        pass
    return None


def _emit_warning_once(key: str, message: str, *args: Any) -> None:
    """Emit a user-visible warning only on the first call per *key* per process."""
    if key not in _warned_keys:
        logger.warning(message, *args)
        _warned_keys.add(key)
    else:
        logger.debug(message, *args)


def _get_metadata_store(context_dir: Path) -> Any:
    """Get or create an IndexMetadataStore for a context directory."""
    try:
        from src.engine.graph import GraphDatabase, IndexMetadataStore

        db_path = context_dir / "graph.db"
        if not db_path.exists():
            return None
        db = GraphDatabase(db_path)
        db.initialize()
        store: IndexMetadataStore = IndexMetadataStore(db)
        return store
    except Exception:
        return None


def _check_persistent_model_state(
    model_name: str, context_dir: Path | None = None
) -> dict[str, Any] | None:
    """Query IndexMetadataStore for model-load state.

    Returns a dict with status, timestamp, path (or None if not persisted).
    If status is 'loaded' and the recorded path still exists, returns the state.
    If status is 'loaded' but path no longer exists, clears the stale state and returns None.
    If status is 'failed' and a model path candidate now exists, clears the state and returns None.
    """
    if context_dir is None:
        return None
    store = _get_metadata_store(context_dir)
    if store is None:
        return None
    status = store.get(_MODEL_LOAD_STATUS_KEY)
    if status is None:
        return None
    timestamp_str = store.get(_MODEL_LOAD_TIMESTAMP_KEY)
    path = store.get(_MODEL_LOAD_PATH_KEY)
    timestamp = int(timestamp_str) if timestamp_str else 0
    if status == "loaded":
        if path and Path(path).exists():
            return {"status": status, "timestamp": timestamp, "path": path}
        # stale state
        store.set(_MODEL_LOAD_STATUS_KEY, "")
        return None
    if status == "failed":
        local_path = _find_local_model_path(model_name, context_dir=context_dir)
        if local_path and Path(local_path).is_dir() and path != str(local_path):
            store.set(_MODEL_LOAD_STATUS_KEY, "")
            return None
        return {"status": status, "timestamp": timestamp, "path": path or ""}
    return None


def _persist_model_state(
    status: str,
    path: str | None = None,
    context_dir: Path | None = None,
) -> None:
    """Write model-load status, timestamp, and path to IndexMetadataStore."""
    if context_dir is None:
        return
    store = _get_metadata_store(context_dir)
    if store is None:
        return
    store.set(_MODEL_LOAD_STATUS_KEY, status)
    store.set(_MODEL_LOAD_TIMESTAMP_KEY, str(int(time.time())))
    if path:
        store.set(_MODEL_LOAD_PATH_KEY, path)


def profile_model_available(settings: Settings) -> bool:
    """Return whether the active profile's model is available locally.

    The ``default`` profile is always considered available (it has the bundled
    fallback). The opt-in ``fast`` profile is withheld until a local candidate
    has been measured to meet the latency/quality floors and explicitly
    shipped (``FAST_PROFILE_SHIPPED``); it is never downloaded and never
    silently substituted.

    Args:
        settings: Active settings carrying ``model_profile`` and paths.

    Returns:
        ``True`` when the profile's model can be used locally.
    """
    if settings.model_profile == "default":
        return True
    if not FAST_PROFILE_SHIPPED:
        return False
    model, _dim = settings.resolve_embedding_profile()
    return _find_local_model_path(model, context_dir=settings.context_dir) is not None


def check_index_model_compatibility(settings: Settings, metadata_store: Any) -> None:
    """Raise when the index was built by a different embedding model.

    Vectors are model-specific, so scoring a query from one model against
    vectors produced by another is silently wrong. This surfaces the mismatch
    as an explicit error (and the re-index requirement) instead.

    Args:
        settings: Active settings; its model profile resolves the active model.
        metadata_store: The index metadata store, or ``None`` when unavailable.

    Raises:
        ValueError: When the recorded model differs from the active model.
    """
    if metadata_store is None:
        return
    try:
        recorded = metadata_store.get("vector_model_name")
    except Exception:
        return
    if not recorded:
        return
    model, _dim = settings.resolve_embedding_profile()
    if recorded != model:
        raise ValueError(
            f"Index was built with embedding model {recorded!r} but the active "
            f"model profile resolves to {model!r}; re-run 'code-search index --force' "
            "to rebuild vectors for the selected model."
        )


def get_representation_scheme_version(metadata_store: Any) -> int | None:
    """Return the stored representation-scheme version, or ``None`` when unset.

    Args:
        metadata_store: The index metadata store, or ``None`` when unavailable.

    Returns:
        The stored scheme version, or ``None`` when the marker is absent.
    """
    if metadata_store is None:
        return None
    try:
        stored = metadata_store.get_int(_REPRESENTATION_SCHEME_KEY)
    except Exception:
        return None
    return int(stored) if stored is not None else None


def set_representation_scheme_version(metadata_store: Any, version: int | None = None) -> None:
    """Record the representation-scheme version in the index metadata.

    Args:
        metadata_store: The index metadata store, or ``None`` to no-op.
        version: The scheme to record; defaults to the running code's
            ``REPRESENTATION_SCHEME_VERSION``.
    """
    if metadata_store is None:
        return
    metadata_store.set_int(
        _REPRESENTATION_SCHEME_KEY,
        REPRESENTATION_SCHEME_VERSION if version is None else version,
    )


def check_index_representation_compatibility(
    metadata_store: Any, *, has_vectors: bool = False
) -> None:
    """Raise when stored embeddings are not from the running representation scheme.

    Mirrors :func:`check_index_model_compatibility`: a representation change
    makes stored vectors stale, so serving them as current would silently rank
    on the wrong text. A marker that is present must equal the running code's
    scheme. A marker that is absent is compatible only for a vector-less or
    synthetic/manual index; an engine-built index (records ``vector_model_name``)
    that already holds vectors is a pre-marker index and is treated as stale.

    Args:
        metadata_store: The index metadata store, or ``None`` when unavailable.
        has_vectors: Whether the vector index currently holds any vectors.

    Raises:
        ValueError: When the stored scheme differs from the running code, or the
            marker is absent on an engine-built vector-bearing index.
    """
    if metadata_store is None:
        return
    try:
        recorded = metadata_store.get_int(_REPRESENTATION_SCHEME_KEY)
    except Exception:
        return
    if recorded is not None:
        if recorded != REPRESENTATION_SCHEME_VERSION:
            raise ValueError(
                f"Index was built with representation scheme {recorded} but the "
                f"active code produces scheme {REPRESENTATION_SCHEME_VERSION}; "
                "re-run 'code-search index --force' to rebuild embeddings for the "
                "current representation."
            )
        return
    if has_vectors and metadata_store.get("vector_model_name"):
        raise ValueError(
            "Index holds embeddings produced before the representation scheme was "
            "recorded; re-run 'code-search index --force' to rebuild embeddings "
            "for the current representation."
        )


def _load_model(settings: Settings | None = None) -> object | None:
    """Lazily load the Model2Vec model once (module-level singleton).

    Caches both success and failure so repeated calls in subprocess
    workers only log the warning once. Persists load state to
    IndexMetadataStore for cross-process deduplication.
    """
    global _model_instance
    if _model_instance is _LOAD_FAILED_SENTINEL:
        return None
    if _model_instance is not None:
        return _model_instance
    model_name = settings.embedding_model if settings else MODEL_NAME
    context_dir = settings.context_dir if settings else None
    if isinstance(context_dir, str):
        context_dir = Path(context_dir)

    # Check persistent state — handle loaded and failed states
    persistent = _check_persistent_model_state(model_name, context_dir=context_dir)
    if persistent is not None and persistent.get("status") == "loaded":
        persisted_path = persistent.get("path", "")
        if persisted_path and Path(persisted_path).is_dir():
            global _loaded_model_path
            _loaded_model_path = persisted_path
            _model_instance = _LOADED_SENTINEL
            logger.info("Model load deferred: %s", persisted_path)
            return _model_instance
    if persistent is not None and persistent.get("status") == "failed":
        key = f"model:{model_name}"
        local_path = _find_local_model_path(model_name, context_dir=context_dir)
        persisted_path = persistent.get("path", "")
        if local_path and str(local_path) != persisted_path:
            # New path appeared — clear stale failure state and attempt load
            _persist_model_state("cleared", context_dir=context_dir)
        else:
            # Same failure condition — suppress warning and return
            _model_instance = _LOAD_FAILED_SENTINEL
            _warned_keys.add(key)
            logger.debug("Model load skipped: persistent failure record")
            return None

    try:
        from model2vec import StaticModel

        local_path = _find_local_model_path(model_name, context_dir=context_dir)
        profile = getattr(settings, "model_profile", "default")
        if local_path:
            _model_instance = StaticModel.from_pretrained(str(local_path))
            logger.info("Loaded Model2Vec model from local path: %s", local_path)
        elif profile != "default":
            # A non-default profile must resolve to a local model; never fetch
            # it from the network (air-gap constraint).
            _emit_warning_once(
                key,
                "Model %s for profile %s is not available locally; place it under "
                "models/ or set CODE_SEARCH_MODEL_PATH.",
                model_name,
                profile,
            )
            _model_instance = _LOAD_FAILED_SENTINEL
            _persist_model_state("failed", path="", context_dir=context_dir)
            return None
        else:
            _model_instance = StaticModel.from_pretrained(model_name)
            logger.info("Loaded Model2Vec model: %s", model_name)
        _persist_model_state(
            "loaded",
            path=str(local_path) if local_path else str(model_name),
            context_dir=context_dir,
        )
        return _model_instance
    except Exception as exc:
        key = f"model:{model_name}"
        _emit_warning_once(key, "Failed to load Model2Vec model %s: %s", model_name, exc)
        _model_instance = _LOAD_FAILED_SENTINEL
        local_path = _find_local_model_path(model_name, context_dir=context_dir)
        _persist_model_state(
            "failed",
            path=str(local_path) if local_path else "",
            context_dir=context_dir,
        )
        return None


class EmbeddingGenerator:
    """Generates normalised vector embeddings for code text.

    Uses a Model2Vec StaticModel under the hood. All returned vectors are
    unit-normalised and padded/truncated to *embedding_dim*.
    """

    def __init__(self, settings: Settings | None = None, disabled: bool = False) -> None:
        """Initialize the generator with the settings governing model/dimension.

        The model is loaded lazily on first :meth:`encode` / :meth:`is_available`
        call; no model download happens at construction time.

        Args:
            settings: Engine settings (``embedding_model``, ``embedding_dim``,
                ``context_dir``); defaults to ``Settings.from_env()``.
            disabled: When true the model is explicitly off (``--no-model``);
                the warmup lifecycle stays terminal at ``disabled``.
        """
        self._settings = settings or Settings.from_env()
        model, dim = self._settings.resolve_embedding_profile()
        self._embedding_model = model
        self._embedding_dim = dim
        self._load_settings = (
            replace(self._settings, embedding_model=model, embedding_dim=dim)
            if (model != self._settings.embedding_model or dim != self._settings.embedding_dim)
            else self._settings
        )
        self._model: object | None = None
        self._disabled = disabled
        self._warm_lock = threading.Lock()
        self._warm_event = threading.Event()
        self._warm_state = WarmupState.DISABLED if disabled else WarmupState.COLD
        self._warm_thread: threading.Thread | None = None
        # Set by the CLI when a resident service owns the single model load so
        # a one-shot invocation does not start a competing in-process load.
        self.warmup_external = False
        if disabled:
            self._warm_event.set()

    def _ensure_model(self) -> object | None:
        """Return a usable Model2Vec model, loading or deferring as needed.

        Handles the module-level load states: performs the initial (or lazy
        deferred) load, transitions ``_LOADED_SENTINEL`` to a real model by
        loading from the persisted path, and treats ``_LOAD_FAILED_SENTINEL``
        as permanently unavailable.

        Returns:
            A loaded model object, or ``None`` when the model cannot be loaded
            (air-gap failure).
        """
        if self._model is None:
            self._model = _load_model(self._load_settings)
        if self._model is _LOAD_FAILED_SENTINEL:
            return None
        if self._model is _LOADED_SENTINEL:
            if _loaded_model_path:
                try:
                    from model2vec import StaticModel

                    self._model = StaticModel.from_pretrained(_loaded_model_path)
                    logger.info("Lazy-loaded Model2Vec model: %s", _loaded_model_path)
                except Exception as exc:
                    logger.warning("Lazy model load failed: %s", exc)
                    self._model = _LOAD_FAILED_SENTINEL
                    _persist_model_state(
                        "failed",
                        path=_loaded_model_path,
                        context_dir=self._settings.context_dir,
                    )
            else:
                self._model = _LOAD_FAILED_SENTINEL
        if self._model is _LOAD_FAILED_SENTINEL:
            return None
        if self._model is _LOADED_SENTINEL:
            return None
        return self._model

    def is_available(self) -> bool:
        """Return whether the embedding model is loaded (or loadable).

        Triggers a load when no model is cached yet; never raises — a missing
        or failed model simply yields ``False`` so callers can degrade to
        lexical-only search.

        Returns:
            ``True`` when a usable model is available, ``False`` otherwise.
        """
        if self._model is not None:
            return self._model is not _LOAD_FAILED_SENTINEL
        self._model = _load_model(self._load_settings)
        return self._model is not None and self._model is not _LOAD_FAILED_SENTINEL

    def model_load_was_warm(self) -> bool:
        """Return whether a real model was already loaded before this request.

        ``False`` when the model was not yet loaded (or only present as the
        deferred ``_LOADED_SENTINEL``), so the request that actually triggers
        the first load reports ``cold`` — measured model state, not elapsed
        time alone — the request that loads it reports cold. A real, already-in-memory model
        reports ``True``.

        Returns:
            ``True`` when a usable model instance was in memory before this
            call, ``False`` otherwise.
        """
        return (
            self._model is not None
            and self._model is not _LOADED_SENTINEL
            and self._model is not _LOAD_FAILED_SENTINEL
        )

    def warm_start(self) -> bool:
        """Eagerly load the vector model so the daemon holds it warm.

        Idempotent: returns True when the model is available after the call,
        False when the model cannot be loaded (air-gap failure). The daemon
        calls this at launch so repeated CLI invocations forwarded to it skip
        the per-process model load.
        """
        if self._model is not None and self._model is not _LOAD_FAILED_SENTINEL:
            self._mark_warm(self._model)
            return True
        model = _load_model(self._load_settings)
        self._mark_warm(model if model is not _LOAD_FAILED_SENTINEL else None)
        return model is not None and model is not _LOAD_FAILED_SENTINEL

    def _mark_warm(self, model: object | None) -> None:
        """Record the outcome of a synchronous or background load.

        Args:
            model: The loaded model, or ``None`` when the load failed.
        """
        with self._warm_lock:
            self._model = model
            self._warm_state = WarmupState.WARM if model is not None else WarmupState.FAILED
            self._warm_event.set()

    def _warmup_worker(self) -> None:
        """Load the model in a background thread and publish the outcome.

        Runs off the request path so a query that arrives while the model is
        loading is served from the reduced lexical path instead of blocking.
        """
        try:
            model = self._ensure_model()
        except Exception as exc:
            logger.warning("Background model warmup failed: %s", exc)
            model = None
        self._mark_warm(model if model is not _LOAD_FAILED_SENTINEL else None)

    def begin_warmup(self) -> None:
        """Start loading the model in the background; safe to call repeatedly.

        Idempotent and concurrency-safe: the first caller spawns exactly one
        loader thread and every other caller observes the same outcome. A no-op
        when the model is already warm, already warming, permanently failed, or
        disabled, and when a resident service owns the load.
        """
        with self._warm_lock:
            if self._warm_state in (
                WarmupState.WARM,
                WarmupState.WARMING,
                WarmupState.FAILED,
                WarmupState.DISABLED,
            ):
                return
            if self.warmup_external:
                return
            if self.model_load_was_warm():
                self._warm_state = WarmupState.WARM
                self._warm_event.set()
                return
            self._warm_state = WarmupState.WARMING
            self._warm_event.clear()
            thread = threading.Thread(
                target=self._warmup_worker, name="embedding-warmup", daemon=True
            )
            self._warm_thread = thread
            thread.start()

    def is_warm(self) -> bool:
        """Return whether a real model is in memory; never blocks.

        Returns:
            ``True`` when the model is warm, ``False`` while cold, warming,
            failed, or disabled.
        """
        if self._warm_state is WarmupState.WARM:
            return True
        return self.model_load_was_warm()

    def warm_state(self) -> WarmupState:
        """Return the model lifecycle state; never blocks.

        Returns:
            The current :class:`WarmupState`.
        """
        if self._warm_state is WarmupState.COLD and self.model_load_was_warm():
            return WarmupState.WARM
        return self._warm_state

    def wait_warm(self, timeout: float | None = None) -> bool:
        """Wait up to *timeout* seconds for warmup to finish.

        Intended for readiness probes only, never the query path.

        Args:
            timeout: Maximum seconds to wait; ``None`` waits indefinitely.

        Returns:
            ``True`` when the model is warm after the wait, else ``False``.
        """
        self._warm_event.wait(timeout)
        return self.is_warm()

    def reset_model(self) -> None:
        """Reset the model state to force a reload on next use.

        Used during index reload to ensure the embedding model is re-initialized
        with the new index state. Returns the lifecycle to ``cold`` (or
        ``disabled``) so a later :meth:`begin_warmup` re-warms.
        """
        with self._warm_lock:
            self._model = None
            self._warm_state = WarmupState.DISABLED if self._disabled else WarmupState.COLD
            self._warm_thread = None
            self._warm_event.clear()
            if self._disabled:
                self._warm_event.set()

    def encode(self, text: str) -> np.ndarray | None:
        """Encode a single text string into a normalised embedding vector."""
        model = self._ensure_model()
        if model is None:
            return None
        try:
            vec = model.encode(text)  # type: ignore[attr-defined]
            return self._normalize_vector(vec)
        except Exception as exc:
            logger.warning("Embedding encoding failed: %s", exc)
            return None

    def _normalize_vector(self, vec: np.ndarray) -> np.ndarray:
        """Pad/truncate a raw model output row to *embedding_dim* and L2-normalise."""
        dim = self._embedding_dim
        arr = np.array(vec, dtype=EMBEDDING_DTYPE)
        if arr.ndim > 1:
            arr = arr.flatten()
        if len(arr) > dim:
            arr = arr[:dim]
        elif len(arr) < dim:
            arr = np.pad(arr, (0, dim - len(arr)))
        norm = np.linalg.norm(arr)
        if norm > 0:
            arr = arr / norm
        return arr

    def encode_batch(self, texts: list[str]) -> list[np.ndarray | None]:
        """Encode a list of texts with one batched ``model.encode`` call.

        Model2Vec's tokenizer pads batch sequences to the batch's longest
        sequence (``BatchLongest``), which shifts mean-pooled vectors versus
        the per-item path, so batches are encoded one sentence at a time
        (``batch_size=1``) — same vectors as :meth:`encode` per item, single
        model dispatch.

        Args:
            texts: The texts to embed.

        Returns:
            A list parallel to *texts* where each entry is the normalised
            vector for that item, or ``None`` when the item failed to encode.
        """
        model = self._ensure_model()
        if model is None:
            return [None] * len(texts)
        try:
            vecs = model.encode(  # type: ignore[attr-defined]
                texts, batch_size=1, use_multiprocessing=False
            )
            rows = np.array(vecs, dtype=EMBEDDING_DTYPE)
            if rows.ndim == 1:
                rows = rows.reshape(1, -1)
            return [self._normalize_vector(row) for row in rows]
        except Exception as exc:
            logger.warning("Batch embedding encoding failed: %s", exc)
            return [None] * len(texts)

    def embedding_to_bytes(self, embedding: np.ndarray) -> bytes:
        """Serialise an embedding array to raw ``float32`` bytes.

        Args:
            embedding: The embedding vector to serialise.

        Returns:
            The array cast to :data:`EMBEDDING_DTYPE` and written as bytes.
        """
        return embedding.astype(EMBEDDING_DTYPE).tobytes()

    def bytes_to_embedding(self, data: bytes) -> np.ndarray:
        """Deserialise raw ``float32`` bytes back into an embedding array.

        Resizes (truncates or zero-pads) the result to ``embedding_dim`` so
        caller-supplied vectors always match the expected dimension.

        Args:
            data: Raw bytes as produced by :meth:`embedding_to_bytes`.

        Returns:
            A ``float32`` array of length ``embedding_dim``.
        """
        arr = np.frombuffer(data, dtype=EMBEDDING_DTYPE)
        dim = self._embedding_dim
        if len(arr) != dim:
            arr = np.resize(arr, dim)
        return arr


_INITIAL_CAPACITY = 1024


class VectorIndex:
    """Flat numpy-based vector store with O(1) removal via tombstones.

    Persists three files: ``vectors.bin`` (append-only ``float32`` rows),
    ``vectors.meta.json`` (append-only NDJSON entries), and ``vectors.removed``
    (append-only tombstone indices). Removal flips an in-memory alive flag and
    queues a tombstone; :meth:`save` writes only the delta accumulated since
    the previous save, so an incremental index never rewrites the corpus.
    Cosine-similarity search scores all rows but returns only alive ones.
    """

    def __init__(
        self,
        vectors_bin_path: Path,
        vectors_meta_path: Path,
        removed_path: Path | None = None,
    ) -> None:
        """Initialize an in-memory vector index backed by three on-disk files.

        Nothing is read until :meth:`load` is called explicitly. *removed_path*
        defaults to *vectors_bin_path* with a ``.removed`` suffix, so existing
        two-argument construction sites keep working.

        Args:
            vectors_bin_path: Path of the raw ``float32`` numpy array file.
            vectors_meta_path: Path of the JSON metadata sidecar (one entry
                per vector, each carrying ``vec_index`` and ``chunk_id``).
            removed_path: Path of the append-only tombstone list; defaults to
                the binary path with a ``.removed`` suffix.
        """
        self._bin_path = vectors_bin_path
        self._meta_path = vectors_meta_path
        self._removed_path = removed_path or vectors_bin_path.with_suffix(".removed")
        self._buffer: np.ndarray | None = None
        self._vectors: np.ndarray | None = None
        self._metadata: list[dict[str, Any]] = []
        self._alive: list[bool] = []
        self._alive_count = 0
        self._chunk_to_vec: dict[int, int] = {}
        self._n = 0
        self._rows_written = 0
        self._pending_removed: list[int] = []
        self._dirty = False

    def load(self) -> None:
        """Load vectors, metadata, and tombstones from disk, if they exist."""
        try:
            if self._bin_path.exists():
                raw = np.fromfile(str(self._bin_path), dtype=EMBEDDING_DTYPE)
                n = len(raw) // EMBEDDING_DIM
                if n > 0:
                    self._buffer = raw[: n * EMBEDDING_DIM].reshape(-1, EMBEDDING_DIM)
                    self._vectors = self._buffer
                else:
                    self._buffer = None
                    self._vectors = None
                self._n = n
                self._rows_written = n
            else:
                self._buffer = None
                self._vectors = None
                self._n = 0
                self._rows_written = 0
            self._metadata = self._read_metadata()[: self._n]
            self._alive = [True] * len(self._metadata)
            self._alive_count = len(self._metadata)
            self._chunk_to_vec = {
                meta["chunk_id"]: vec_index
                for vec_index, meta in enumerate(self._metadata)
                if meta.get("chunk_id") is not None
            }
            for idx in self._read_removed():
                if 0 <= idx < len(self._alive) and self._alive[idx]:
                    self._alive[idx] = False
                    self._alive_count -= 1
                    self._chunk_to_vec.pop(self._metadata[idx]["chunk_id"], None)
            self._dirty = False
            logger.debug("Loaded vector index: %d vectors", self.size)
        except Exception as exc:
            logger.warning("Failed to load vector index: %s", exc)
            self._reset_empty()

    def save(self) -> None:
        """Persist the delta since the last save (appended rows + tombstones).

        A no-op when nothing changed since the previous save, so steady-state
        indexing does not touch the on-disk files.
        """
        if not self._dirty:
            return
        try:
            if self._n > self._rows_written:
                vectors = self._vectors
                if vectors is not None:
                    with self._bin_path.open("ab") as f:
                        vectors[self._rows_written : self._n].tofile(f)
                with self._meta_path.open("a") as f:
                    for entry in self._metadata[self._rows_written : self._n]:
                        f.write(json.dumps(entry) + "\n")
            if self._pending_removed:
                with self._removed_path.open("a") as f:
                    for vec_index in self._pending_removed:
                        f.write(f"{vec_index}\n")
            self._rows_written = self._n
            self._pending_removed = []
            self._dirty = False
            logger.debug("Saved vector index: %d vectors", self.size)
        except Exception as exc:
            logger.warning("Failed to save vector index: %s", exc)

    def _read_metadata(self) -> list[dict[str, Any]]:
        """Parse the metadata sidecar, accepting both legacy array and NDJSON."""
        if not self._meta_path.exists():
            return []
        text = self._meta_path.read_text()
        if not text.strip():
            return []
        stripped = text.strip()
        if stripped.startswith("["):
            try:
                data = json.loads(stripped)
            except Exception:
                return []
            return list(data) if isinstance(data, list) else []
        entries: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except Exception:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
        return entries

    def _read_removed(self) -> list[int]:
        """Parse the tombstone sidecar (one integer index per line)."""
        if not self._removed_path.exists():
            return []
        indices: list[int] = []
        for line in self._removed_path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                indices.append(int(line))
            except ValueError:
                continue
        return indices

    def _ensure_capacity(self, needed: int) -> None:
        """Grow the backing buffer so at least *needed* rows fit."""
        if self._buffer is not None and needed <= self._buffer.shape[0]:
            return
        new_capacity = (
            max(needed, self._buffer.shape[0] * 2)
            if self._buffer is not None
            else max(needed, _INITIAL_CAPACITY)
        )
        new_buffer = np.zeros((new_capacity, EMBEDDING_DIM), dtype=EMBEDDING_DTYPE)
        if self._n > 0:
            old_buffer = self._buffer
            assert old_buffer is not None
            new_buffer[: self._n] = old_buffer[: self._n]
        self._buffer = new_buffer
        self._vectors = self._buffer[: self._n]

    def add(self, chunk_id: int, embedding: np.ndarray, metadata: dict[str, Any]) -> int:
        """Append one vector + metadata entry and return its physical index.

        Physical indices are never reused: a chunk added after removals still
        gets a fresh index, keeping previously persisted rows addressable.

        Args:
            chunk_id: The ``code_chunks.id`` this embedding was produced from.
            embedding: The vector to store.
            metadata: Per-entry metadata; MUST carry a non-empty ``file_path``
                so every stored embedding can be correlated back to the chunk
                it was produced from. A missing or empty ``file_path`` raises
                ``ValueError`` instead of silently persisting an uncorrelated
                entry.

        Returns:
            The new physical index of the appended row.

        Raises:
            ValueError: When ``metadata`` lacks a non-empty ``file_path``.
        """
        file_path = metadata.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("VectorIndex.add requires non-empty metadata['file_path']")
        emb = np.asarray(embedding, dtype=EMBEDDING_DTYPE).reshape(EMBEDDING_DIM)
        self._ensure_capacity(self._n + 1)
        buffer_array = self._buffer
        assert buffer_array is not None
        buffer_array[self._n] = emb
        self._n += 1
        self._vectors = buffer_array[: self._n]
        vec_index = self._n - 1
        meta_entry = {"vec_index": vec_index, "chunk_id": chunk_id, **metadata}
        self._metadata.append(meta_entry)
        self._alive.append(True)
        self._alive_count += 1
        self._chunk_to_vec[chunk_id] = vec_index
        self._dirty = True
        return vec_index

    def add_batch(
        self,
        chunk_ids: list[int],
        embeddings: list[np.ndarray],
        metadata_list: list[dict[str, Any]],
    ) -> list[int]:
        """Append multiple vectors + metadata entries atomically.

        Args:
            chunk_ids: ``chunk_id`` for each entry, parallel to *embeddings*.
            embeddings: The vectors to append.
            metadata_list: Extra metadata dict per entry, parallel to
                *embeddings*.

        Returns:
            The list of ``vec_index`` values assigned, in order.
        """
        indices: list[int] = []
        for cid, emb, meta in zip(chunk_ids, embeddings, metadata_list, strict=True):
            idx = self.add(cid, emb, meta)
            indices.append(idx)
        return indices

    def search(
        self,
        query_embedding: np.ndarray,
        top_k: int = 10,
        exclude_file_paths: set[str] | None = None,
        content: str = "all",
    ) -> list[tuple[int, float]]:
        """Cosine-similarity search — returns ``(chunk_id, score)`` sorted descending.

        When *exclude_file_paths* is given, candidates whose metadata
        ``file_path`` is in the set are skipped before ranking:
        the anchor chunk's own file is dropped from the neighbour set as a
        single set-filter over the alive vectors, so ``find_related`` never
        presents same-file self-chunks as cross-file relatedness. The anchor
        chunk itself is excluded the same way when its file is excluded.
        When *content* is a specific content axis (``"code"``/``"config"``/
        ``"docs"``), only vectors whose metadata ``content_type`` matches are
        considered, so a scoped query's vector pool never admits out-of-scope
        chunks.
        """
        if self._vectors is None or self._n == 0:
            return []
        alive = np.flatnonzero(np.asarray(self._alive, dtype=bool))
        alive = alive[alive < self._n]
        if alive.size == 0:
            return []
        if exclude_file_paths:
            keep = np.asarray(
                [
                    self._metadata[int(idx)].get("file_path") not in exclude_file_paths
                    for idx in alive
                ],
                dtype=bool,
            )
            alive = alive[keep]
            if alive.size == 0:
                return []
        if content != "all":
            if content == "code_focused":
                keep = np.asarray(
                    [
                        self._metadata[int(idx)].get("content_type", "code") == "code"
                        for idx in alive
                    ],
                    dtype=bool,
                )
            else:
                keep = np.asarray(
                    [
                        self._metadata[int(idx)].get("content_type", "code") == content
                        for idx in alive
                    ],
                    dtype=bool,
                )
            alive = alive[keep]
            if alive.size == 0:
                return []
        q = np.asarray(query_embedding, dtype=EMBEDDING_DTYPE).reshape(-1)
        q_norm = np.linalg.norm(q)
        if q_norm > 0:
            q = q / q_norm
        dots = self._vectors @ q
        alive_dots = dots[alive]
        k = min(top_k, alive.size)
        top_alive = np.argpartition(alive_dots, -k)[-k:]
        top_alive = top_alive[np.argsort(alive_dots[top_alive])[::-1]]
        results: list[tuple[int, float]] = []
        for pos in top_alive:
            vec_index = int(alive[pos])
            chunk_id = self._metadata[vec_index]["chunk_id"]
            score = float(alive_dots[pos])
            score = max(0.0, min(1.0, score))
            results.append((chunk_id, score))
        return results

    @property
    def size(self) -> int:
        """Return the number of alive vectors currently in the index."""
        return self._alive_count

    def remove(self, chunk_id: int) -> bool:
        """Remove the vector + metadata entry for *chunk_id* by tombstoning it.

        Args:
            chunk_id: The chunk to drop.

        Returns:
            ``True`` when an alive entry with *chunk_id* was found and
            tombstoned, ``False`` when it was not present.
        """
        return self.remove_many([chunk_id]) > 0

    def remove_many(self, chunk_ids: list[int]) -> int:
        """Tombstone every alive vector whose chunk id is in *chunk_ids*.

        O(K) over the requested ids using the chunk→index map; rows are kept
        physically and only their alive flag flips, so running removals never
        copy the corpus. Unknown or already-removed ids are ignored.

        Args:
            chunk_ids: The chunks to drop.

        Returns:
            The number of alive entries tombstoned.
        """
        removed = 0
        pending: list[int] = []
        for chunk_id in set(chunk_ids):
            vec_index = self._chunk_to_vec.get(chunk_id)
            if vec_index is None:
                continue
            if self._alive[vec_index]:
                self._alive[vec_index] = False
                self._alive_count -= 1
                pending.append(vec_index)
                removed += 1
                self._chunk_to_vec.pop(chunk_id, None)
        if removed:
            self._pending_removed.extend(pending)
            self._dirty = True
        return removed

    def _reset_empty(self) -> None:
        """Drop all in-memory state and clear the pending delta."""
        self._buffer = None
        self._vectors = None
        self._metadata = []
        self._alive = []
        self._alive_count = 0
        self._chunk_to_vec = {}
        self._n = 0
        self._rows_written = 0
        self._pending_removed = []
        self._dirty = False

    def clear(self) -> None:
        """Drop all vectors and metadata, truncating the on-disk files.

        Call :meth:`save` afterwards to persist any remaining state.
        """
        self._reset_empty()
        for file_path in (self._bin_path, self._meta_path, self._removed_path):
            with suppress(Exception):
                file_path.write_text("")
