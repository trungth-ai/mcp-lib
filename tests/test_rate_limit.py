from __future__ import annotations

from hpu_library_mcp.security.rate_limit import RateLimiter


def test_allows_up_to_limit():
    limiter = RateLimiter(window_seconds=60)
    for _ in range(5):
        assert limiter.allow("key-a", limit_per_window=5) is True


def test_rejects_after_limit_exceeded():
    limiter = RateLimiter(window_seconds=60)
    for _ in range(5):
        limiter.allow("key-a", limit_per_window=5)
    assert limiter.allow("key-a", limit_per_window=5) is False


def test_different_keys_have_independent_limits():
    limiter = RateLimiter(window_seconds=60)
    for _ in range(5):
        limiter.allow("key-a", limit_per_window=5)
    assert limiter.allow("key-b", limit_per_window=5) is True


def test_window_expiry_allows_again(monkeypatch):
    import hpu_library_mcp.security.rate_limit as rate_limit_module

    fake_now = [1000.0]
    monkeypatch.setattr(rate_limit_module.time, "monotonic", lambda: fake_now[0])

    limiter = RateLimiter(window_seconds=60)
    for _ in range(3):
        limiter.allow("key-a", limit_per_window=3)
    assert limiter.allow("key-a", limit_per_window=3) is False

    fake_now[0] += 61  # qua khỏi cửa sổ 60s
    assert limiter.allow("key-a", limit_per_window=3) is True
