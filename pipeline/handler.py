"""Lambda entry points for the weekly Step Functions run (alias of ``stages.py``).

The cloud pipeline is no longer a single Lambda. An EventBridge schedule starts the
``RebellionStateMachine`` (``infra/statemachine/rebellion.asl.json``), which runs:

    Preflight -> Fetch -> ExtractEach (Map, one Extract per article) -> Assemble

Each state is a Lambda backed by a function in :mod:`pipeline.stages`; this module
re-exports them so ``pipeline.handler.<stage>`` also works as a Lambda handler path.
"""

from __future__ import annotations

from .stages import assemble, extract, fetch, preflight

__all__ = ["assemble", "extract", "fetch", "preflight"]
