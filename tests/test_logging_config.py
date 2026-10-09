"""Logging setup tests (post-M9c pilot).

Guards that the app actually enables INFO for ``src.*`` (the M9c-prep per-step
agent logs were silently dropped before this) and that the ``/agent/progress``
poll spam is filtered out of the access log.
"""

import logging

from src.logging_config import configure_logging, _DropProgressAccessLogs


class TestConfigureLogging:
    def test_enables_info_for_src(self):
        configure_logging()
        assert logging.getLogger("src").level == logging.INFO

    def test_is_idempotent(self):
        configure_logging()
        root_handlers = [h for h in logging.getLogger().handlers if getattr(h, "_stet_handler", False)]
        access_filters = [f for f in logging.getLogger("uvicorn.access").filters
                          if isinstance(f, _DropProgressAccessLogs)]
        configure_logging()  # second call must not stack handlers/filters
        root_handlers_2 = [h for h in logging.getLogger().handlers if getattr(h, "_stet_handler", False)]
        access_filters_2 = [f for f in logging.getLogger("uvicorn.access").filters
                            if isinstance(f, _DropProgressAccessLogs)]
        assert len(root_handlers_2) == len(root_handlers) == 1
        assert len(access_filters_2) == len(access_filters) == 1

    def test_progress_access_logs_filtered(self):
        f = _DropProgressAccessLogs()
        drop = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                                 'GET /api/workspace/x/agent/progress HTTP/1.1', (), None)
        keep = logging.LogRecord("uvicorn.access", logging.INFO, "", 0,
                                 'POST /api/workspace/x/agent/run HTTP/1.1', (), None)
        assert f.filter(drop) is False
        assert f.filter(keep) is True
