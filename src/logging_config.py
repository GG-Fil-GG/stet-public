"""Application logging setup (post-M9c pilot).

The M9c-prep per-step agent logging (``src.agent.loop``) was silently dropped in
the running server: nothing ever configured logging, so Python's root logger
stayed at WARNING and every ``logger.info`` from ``src.*`` was discarded. This
module wires up a single INFO console handler for the ``src`` tree and quiets the
``/agent/progress`` access-log spam (the 2 s progress poll otherwise floods the
terminal and buries the agent trace). Call :func:`configure_logging` once at
startup (``main.py``).
"""

from __future__ import annotations

import logging

_PROGRESS_PATH = "/agent/progress"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class _DropProgressAccessLogs(logging.Filter):
    """Filter out uvicorn access lines for the high-frequency progress poll."""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 - Filter API
        return _PROGRESS_PATH not in record.getMessage()


def configure_logging(level: int = logging.INFO) -> None:
    """Enable INFO logging for ``src.*`` and mute the progress-poll access spam.

    Idempotent: safe to call more than once (won't stack handlers or filters).
    """
    root = logging.getLogger()
    if not any(getattr(h, "_stet_handler", False) for h in root.handlers):
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_FORMAT))
        handler._stet_handler = True  # type: ignore[attr-defined]  # marker for idempotency
        root.addHandler(handler)
    if root.level > level or root.level == logging.NOTSET:
        root.setLevel(level)
    logging.getLogger("src").setLevel(level)

    access = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _DropProgressAccessLogs) for f in access.filters):
        access.addFilter(_DropProgressAccessLogs())
