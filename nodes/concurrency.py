import os
from concurrent.futures import ThreadPoolExecutor


def _max_workers(default: int = 8) -> int:
    try:
        return max(1, int(os.getenv("ENRICH_MAX_WORKERS", default)))
    except (TypeError, ValueError):
        return default


def parallel_map(fn, items: list, max_workers: int | None = None) -> list:
    """Apply fn to each item concurrently, preserving input order.

    The per-lead enrichment calls are network/LLM bound, so running them on a
    thread pool collapses a run's latency from the sum of every call to roughly
    its slowest one. Falls back to a plain loop for 0/1 items so the common
    single-lead path adds no threads. Exceptions propagate as in a serial map.
    """
    if len(items) <= 1:
        return [fn(item) for item in items]
    workers = min(max_workers or _max_workers(), len(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(fn, items))
