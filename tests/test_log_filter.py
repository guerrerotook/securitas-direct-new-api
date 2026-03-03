"""Tests for SensitiveDataFilter."""

import logging

from custom_components.securitas.log_filter import SensitiveDataFilter


def test_redacts_secret_in_message():
    """Filter replaces a registered secret in the log message."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "eyJhbGciOiJIUzI1NiJ9.secret")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="Token is eyJhbGciOiJIUzI1NiJ9.secret here",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert "eyJhbGciOiJIUzI1NiJ9.secret" not in record.msg
    assert "[AUTH_TOKEN]" in record.msg


def test_redacts_secret_in_format_args():
    """Filter replaces a registered secret in %s format args."""
    f = SensitiveDataFilter()
    f.update_secret("password", "hunter2")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="Login with %s",
        args=("hunter2",),
        exc_info=None,
    )
    f.filter(record)
    assert "hunter2" not in str(record.args)
    assert "[PASSWORD]" in str(record.args)


def test_redacts_multiple_secrets():
    """Filter replaces multiple different secrets in the same message."""
    f = SensitiveDataFilter()
    f.update_secret("username", "user@example.com")
    f.update_secret("password", "hunter2")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="user@example.com logged in with hunter2",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert "[USERNAME]" in record.msg
    assert "[PASSWORD]" in record.msg
    assert "user@example.com" not in record.msg
    assert "hunter2" not in record.msg


def test_update_secret_replaces_old_value():
    """Updating a secret key removes the old value and tracks the new one."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "old-token")
    f.update_secret("auth_token", "new-token")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="old-token and new-token",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    # Old value should pass through (no longer tracked)
    assert "old-token" in record.msg
    # New value should be redacted
    assert "[AUTH_TOKEN]" in record.msg
    assert "new-token" not in record.msg


def test_filter_always_returns_true():
    """Filter never suppresses log records."""
    f = SensitiveDataFilter()
    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="safe message",
        args=(),
        exc_info=None,
    )
    assert f.filter(record) is True


def test_empty_and_none_secrets_ignored():
    """Empty string and None values are not registered as secrets."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "")
    f.update_secret("password", None)

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="normal message",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert record.msg == "normal message"


def test_non_string_args_handled():
    """Filter handles non-string args (int, dict, None) without raising."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "secret123")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="code %d data %s",
        args=(42, {"key": "secret123"}),
        exc_info=None,
    )
    f.filter(record)
    assert "secret123" not in str(record.args)


def test_filter_survives_malformed_record():
    """A malformed record doesn't crash the filter."""
    f = SensitiveDataFilter()
    f.update_secret("auth_token", "secret123")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg=None,
        args=None,
        exc_info=None,
    )
    # Should not raise
    result = f.filter(record)
    assert result is True


def test_add_installation_masks_number():
    """Installation numbers are partially masked (last 4 visible)."""
    f = SensitiveDataFilter()
    f.add_installation("1234567")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="No services for 1234567",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert "1234567" not in record.msg
    assert "***4567" in record.msg


def test_add_installation_short_number():
    """Installation numbers with 4 or fewer chars are fully masked."""
    f = SensitiveDataFilter()
    f.add_installation("1234")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="Installation 1234",
        args=(),
        exc_info=None,
    )
    f.filter(record)
    assert "1234" not in record.msg
    assert "***" in record.msg


def test_add_installation_in_format_args():
    """Installation numbers in %s args are masked."""
    f = SensitiveDataFilter()
    f.add_installation("9876543")

    record = logging.LogRecord(
        name="test",
        level=logging.DEBUG,
        pathname="",
        lineno=0,
        msg="No services for %s",
        args=("9876543",),
        exc_info=None,
    )
    f.filter(record)
    assert "9876543" not in str(record.args)
    assert "***6543" in str(record.args)


def test_filter_attached_to_logger():
    """Verify the filter can be attached to a logger and intercepts records."""
    import io

    f = SensitiveDataFilter()
    f.update_secret("password", "hunter2")

    logger = logging.getLogger("test.securitas.filter_attach")
    logger.addFilter(f)
    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(io.StringIO())
    handler.setLevel(logging.DEBUG)
    logger.addHandler(handler)

    try:
        logger.debug("Password is hunter2")
        output = handler.stream.getvalue()
        assert "hunter2" not in output
        assert "[PASSWORD]" in output
    finally:
        logger.removeFilter(f)
        logger.removeHandler(handler)
