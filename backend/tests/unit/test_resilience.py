"""Tests for circuit breakers, timeout budgets, and retry logic."""

import time

import pytest

from backend.services.resilience import (
    CircuitBreaker,
    CircuitState,
    TimeoutBudget,
    TimeoutError,
    retry_with_backoff,
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert not cb.allow_request()

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()

    def test_success_resets_failure_count(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.failure_count == 0
        assert cb.state == CircuitState.CLOSED

    def test_half_open_after_recovery_timeout(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        # With 0 recovery timeout, should transition immediately
        assert cb.allow_request()
        assert cb.state == CircuitState.HALF_OPEN

    def test_half_open_to_closed_on_success(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        cb.allow_request()  # transitions to HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_half_open_to_open_on_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0)
        cb.record_failure()
        cb.allow_request()  # transitions to HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_is_open_property(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        assert not cb.is_open
        cb.record_failure()
        assert cb.is_open


class TestTimeoutBudget:
    def test_initial_budget(self):
        budget = TimeoutBudget(total_budget_seconds=60.0)
        assert budget.remaining_seconds > 0
        assert not budget.is_expired

    def test_expired_budget(self):
        budget = TimeoutBudget(total_budget_seconds=0.0)
        assert budget.is_expired
        assert budget.remaining_seconds == 0.0

    def test_check_budget_raises_on_expired(self):
        budget = TimeoutBudget(total_budget_seconds=0.0)
        with pytest.raises(TimeoutError, match="Waterfall timeout"):
            budget.check_budget("faq")

    def test_check_budget_passes_when_valid(self):
        budget = TimeoutBudget(total_budget_seconds=120.0)
        budget.check_budget("faq")  # Should not raise

    def test_step_timeout_respects_remaining(self):
        budget = TimeoutBudget(total_budget_seconds=5.0)
        # Step budget of 30s should be capped by remaining total
        assert budget.step_timeout(30.0) <= 5.0

    def test_step_timeout_uses_step_budget_when_smaller(self):
        budget = TimeoutBudget(total_budget_seconds=120.0)
        assert budget.step_timeout(10.0) == 10.0

    def test_elapsed_increases(self):
        budget = TimeoutBudget(total_budget_seconds=120.0)
        assert budget.elapsed_seconds >= 0


class TestRetryWithBackoff:
    def test_success_on_first_try(self):
        result = retry_with_backoff(lambda: "ok", max_retries=3)
        assert result == "ok"

    def test_success_after_retries(self):
        call_count = {"n": 0}

        def flaky():
            call_count["n"] += 1
            if call_count["n"] < 3:
                raise ValueError("fail")
            return "ok"

        result = retry_with_backoff(
            flaky, max_retries=3, base_delay=0.01, max_delay=0.02
        )
        assert result == "ok"
        assert call_count["n"] == 3

    def test_raises_after_max_retries(self):
        def always_fail():
            raise ValueError("always fails")

        with pytest.raises(ValueError, match="always fails"):
            retry_with_backoff(
                always_fail, max_retries=2, base_delay=0.01, max_delay=0.02
            )

    def test_respects_circuit_breaker(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()  # Open the circuit

        with pytest.raises(RuntimeError, match="Circuit breaker"):
            retry_with_backoff(
                lambda: "ok",
                max_retries=1,
                circuit_breaker=cb,
            )

    def test_updates_circuit_breaker_on_success(self):
        cb = CircuitBreaker(name="test")
        result = retry_with_backoff(lambda: "ok", circuit_breaker=cb)
        assert result == "ok"
        assert cb.failure_count == 0

    def test_updates_circuit_breaker_on_failure(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)

        try:
            retry_with_backoff(
                lambda: (_ for _ in ()).throw(ValueError("fail")),
                max_retries=1,
                base_delay=0.01,
                circuit_breaker=cb,
            )
        except ValueError:
            pass

        assert cb.failure_count > 0
