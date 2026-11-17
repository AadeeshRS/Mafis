"""Publish committed Shared Memory records for dashboard workers."""

import json
import logging
import os
from contextlib import contextmanager
from time import perf_counter

FEED_ENV = "MAFIS_DASHBOARD_MEMORY_FEED"
FEED_NAME = "shared_memory.jsonl"

logger = logging.getLogger("mafis.shared_memory.feed")
logger.propagate = False


def configure_memory_feed():
    path = os.environ.get(FEED_ENV)
    if not path or logger.handlers:
        return
    try:
        logger.addHandler(logging.FileHandler(path, encoding="utf-8"))
    except OSError:
        logging.getLogger(__name__).exception("Could not open the dashboard Shared Memory feed")
        return
    logger.setLevel(logging.INFO)


def publish_memory_entries(run_id, *entries):
    if logger.isEnabledFor(logging.INFO) and logger.handlers:
        logger.info(json.dumps([
            {"run_id": run_id, "kind": kind,
             "record": record if isinstance(record, dict) else record.model_dump(mode="json")}
            for kind, record in entries
        ]))


@contextmanager
def track_stage(stage, run_id):
    """Record actual execution boundaries in the worker's dashboard feed."""
    if stage is None or not logger.handlers:
        yield
        return
    started = perf_counter()
    publish_memory_entries(run_id, ("stage", {"stage": stage, "status": "running"}))
    status = "failed"
    try:
        yield
        status = "done"
    finally:
        publish_memory_entries(run_id, ("stage", {"stage": stage, "status": status,
                                                  "duration_ms": (perf_counter() - started) * 1000}))
