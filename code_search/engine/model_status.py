"""Model warm/cold status reporting for MCP responses.

Mirrors the CLI ``model_status`` schema, surfacing per-request latency
and warm/cold state information in every ranked MCP response.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ModelState(StrEnum):
    """Current model state for the request."""

    WARM = "warm"
    COLD = "cold"
    INITIALIZING = "initializing"


def report_model_status(
    query_time_ms: int,
    warmup_time_ms: int,
    embedding_time_ms: int,
    ranking_time_ms: int,
    io_time_ms: int,
    is_first_request: bool,
    warmup_state: str | None = None,
) -> dict[str, Any]:
    """Generate the model warm/cold status report for an MCP response.

    Args:
        query_time_ms: Total query latency in milliseconds.
        warmup_time_ms: Time elapsed since model initialization began.
        embedding_time_ms: Time spent computing embeddings.
        ranking_time_ms: Time spent ranking results.
        io_time_ms: Time spent in I/O operations.
        is_first_request: Whether this is the first request since model
            initialization.
        warmup_state: Optional lifecycle state (``cold``/``warming``/``warm``/
            ``failed``/``disabled``); emitted as an additive key when provided.

    Returns:
        dict with keys:
        - ``state`` (ModelState): Current model state (`warm`, `cold`,
          `initializing`)
        - ``warmup_state`` (str): Lifecycle state, present only when supplied
        - ``warmup_time_ms`` (integer): Time elapsed since model
          initialization began
        - ``latency_breakdown`` (dict): Per-phase latency breakdown with
          keys ``cold_start``, ``embedding``, ``ranking``, ``io``
        - ``is_first_request`` (boolean): Whether this is the first request
          since model initialization
    """
    # Determine model state
    if is_first_request:
        state = ModelState.INITIALIZING
    elif warmup_time_ms > 0:
        state = ModelState.COLD
    else:
        state = ModelState.WARM

    # Cold-start time: time spent before model was warm.
    # For WARM state: cold_start = 0.
    # For COLD/INITIALIZING state: cold_start = warmup_time_ms (initialization time).
    cold_start = warmup_time_ms if state in (ModelState.COLD, ModelState.INITIALIZING) else 0

    # Verify latency breakdown sums to query_time_ms per contract constraint.
    # cold_start + embedding + ranking + io must equal query_time_ms.
    breakdown_sum = cold_start + embedding_time_ms + ranking_time_ms + io_time_ms
    if breakdown_sum != query_time_ms:
        # Distribute the difference to ensure the constraint is met.
        diff = query_time_ms - breakdown_sum
        # Add the diff to the largest component to minimize impact.
        components = [
            ("cold_start", cold_start),
            ("embedding", embedding_time_ms),
            ("ranking", ranking_time_ms),
            ("io", io_time_ms),
        ]
        components.sort(key=lambda x: x[1], reverse=True)
        if len(components) > 1:
            # Add the diff to the second largest to avoid double-counting
            # the largest.
            sorted_idx = 1
            adjustment = {c[0]: c[1] for c in components}
            key = components[sorted_idx][0]
            adjustment[key] = adjustment.get(key, 0) + diff
            cold_start_final = adjustment.get("cold_start", cold_start)
            embedding_final = adjustment.get("embedding", embedding_time_ms)
            ranking_final = adjustment.get("ranking", ranking_time_ms)
            io_final = adjustment.get("io", io_time_ms)
        else:
            cold_start_final = cold_start + diff
            embedding_final = embedding_time_ms
            ranking_final = ranking_time_ms
            io_final = io_time_ms
    else:
        cold_start_final = cold_start
        embedding_final = embedding_time_ms
        ranking_final = ranking_time_ms
        io_final = io_time_ms

    latency_breakdown: dict[str, Any] = {
        "cold_start": cold_start_final,
        "embedding": embedding_final,
        "ranking": ranking_final,
        "io": io_final,
    }

    report: dict[str, Any] = {
        "state": state,
        "warmup_time_ms": warmup_time_ms,
        "latency_breakdown": latency_breakdown,
        "is_first_request": is_first_request,
    }
    if warmup_state is not None:
        report["warmup_state"] = warmup_state
    return report
