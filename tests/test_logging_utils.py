import logging
from importlib import reload

import pytest

from mcp_vertica import logging_utils


@pytest.mark.parametrize(
    "debug_value, expected_level",
    [
        (None, logging.WARNING),
        ("", logging.WARNING),
        ("0", logging.WARNING),
        ("1", logging.INFO),
        ("2", logging.DEBUG),
        ("3", logging.DEBUG),
    ],
)
def test_configure_logging_respects_debug_env(monkeypatch, debug_value, expected_level):
    if debug_value is None:
        monkeypatch.delenv("DEBUG", raising=False)
    else:
        monkeypatch.setenv("DEBUG", debug_value)

    reload(logging_utils)
    logging_utils.configure_logging(force=True)

    assert logging.getLogger().level == expected_level


def test_record_service_error_tracks_entries(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    reload(logging_utils)
    logging_utils.configure_logging(force=True)

    logging_utils.record_service_error(source="database", message="test error")

    errors = logging_utils.recent_errors()
    assert errors
    assert errors[-1]["message"] == "test error"
    assert errors[-1]["source"] == "database"
