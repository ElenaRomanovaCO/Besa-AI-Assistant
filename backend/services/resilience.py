"""Resilience utilities: circuit breakers, timeouts, and retry with backoff.

Provides decorators and context managers for protecting external service calls
(Discord API, Bedrock, MCP server) from cascading failures.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


# --------------------------------------------------------------------------- #
# Circuit Breaker
# --------------------------------------------------------------------------- #

class CircuitState(str, Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing — reject calls immediately
    HALF_OPEN = "half_open"  # Testing recovery — allow one call through


@dataclass
class CircuitBreaker:
    """
    Circuit breaker for external service calls.

    State transitions:
      CLOSED → OPEN: after `failure_threshold` consecutive failures
      OPEN → HALF_OPEN: after `recovery_timeout` seconds
      HALF_OPEN → CLOSED: on first success
      HALF_OPEN → OPEN: on first failure

    Thread-safe via threading.Lock.
    """

    name: str
    failure_threshold: int = 5
    recovery_timeout: int = 60  # seconds before trying again
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record_success(self) -> None:
        """Record a successful call — reset failure count, close circuit."""
        with self._lock:
            self.failure_count = 0
            if self.state == CircuitState.HALF_OPEN:
                logger.info("Circuit '%s' recovered → CLOSED", self.name)
            self.state = CircuitState.CLOSED

    def record_failure(self) -> None:
        """Record a failed call — increment counter, potentially open circuit."""
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN
                logger.warning("Circuit '%s' HALF_OPEN → OPEN (failure during recovery)", self.name)
            elif self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
                logger.warning(
                    "Circuit '%s' OPEN after %d consecutive failures",
                    self.name, self.failure_count,
                )

    def allow_request(self) -> bool:
        """Check if a request should be allowed through."""
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True

            if self.state == CircuitState.OPEN:
                elapsed = time.time() - self.last_failure_time
                if elapsed >= self.recovery_timeout:
                    self.state = CircuitState.HALF_OPEN
                    logger.info(
                        "Circuit '%s' OPEN → HALF_OPEN (recovery window reached)",
                        self.name,
                    )
                    return True
                return False

            # HALF_OPEN — allow exactly one request through
            return True

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self.state == CircuitState.OPEN


# --------------------------------------------------------------------------- #
# Timeout Budget
# --------------------------------------------------------------------------- #

class TimeoutError(Exception):
    """Raised when an operation exceeds its timeout budget."""
    pass


@dataclass
class TimeoutBudget:
    """
    Per-agent timeout budget for the waterfall pipeline.

    Tracks elapsed time and enforces per-step and total limits.
    """

    total_budget_seconds: float = 120.0  # Total waterfall budget
    _start_time: float = field(default_factory=time.time)

    @property
    def elapsed_seconds(self) -> float:
        return time.time() - self._start_time

    @property
    def remaining_seconds(self) -> float:
        return max(0, self.total_budget_seconds - self.elapsed_seconds)

    @property
    def is_expired(self) -> bool:
        return self.remaining_seconds <= 0

    def check_budget(self, step_name: str) -> None:
        """Raise TimeoutError if the total budget is exhausted."""
        if self.is_expired:
            raise TimeoutError(
                f"Waterfall timeout: {step_name} skipped — "
                f"{self.elapsed_seconds:.1f}s elapsed, "
                f"budget was {self.total_budget_seconds:.1f}s"
            )

    def step_timeout(self, step_budget_seconds: float) -> float:
        """Return the effective timeout for a step (min of step budget and remaining total)."""
        return min(step_budget_seconds, self.remaining_seconds)


# Default timeout budgets per agent step (seconds)
AGENT_TIMEOUTS = {
    "faq": 10.0,
    "discord": 15.0,
    "reasoning": 30.0,
    "aws_docs": 20.0,
}

# Default total waterfall budget
WATERFALL_TIMEOUT = 120.0


# --------------------------------------------------------------------------- #
# Retry with Exponential Backoff
# --------------------------------------------------------------------------- #

def retry_with_backoff(
    func: Callable[..., T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 8.0,
    retryable_exceptions: tuple = (Exception,),
    circuit_breaker: Optional[CircuitBreaker] = None,
) -> T:
    """
    Execute a function with exponential backoff retry.

    Args:
        func: Callable to execute
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries (seconds)
        max_delay: Maximum delay between retries (seconds)
        retryable_exceptions: Tuple of exception types to retry on
        circuit_breaker: Optional circuit breaker to check/update

    Returns:
        Result of the function call

    Raises:
        The last exception if all retries are exhausted
    """
    last_exception = None

    for attempt in range(max_retries + 1):
        # Check circuit breaker
        if circuit_breaker and not circuit_breaker.allow_request():
            raise RuntimeError(
                f"Circuit breaker '{circuit_breaker.name}' is OPEN — "
                f"skipping call after {circuit_breaker.failure_count} failures"
            )

        try:
            result = func()
            if circuit_breaker:
                circuit_breaker.record_success()
            return result
        except retryable_exceptions as e:
            last_exception = e
            if circuit_breaker:
                circuit_breaker.record_failure()

            if attempt < max_retries:
                delay = min(base_delay * (2 ** attempt), max_delay)
                # Add jitter (±25%)
                import random
                jitter = delay * 0.25 * (2 * random.random() - 1)
                actual_delay = max(0, delay + jitter)
                logger.warning(
                    "Retry %d/%d after %.1fs (error: %s)",
                    attempt + 1, max_retries, actual_delay, e,
                )
                time.sleep(actual_delay)

    raise last_exception  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Pre-built circuit breakers for known external services
# --------------------------------------------------------------------------- #

# Singleton circuit breakers — shared across warm Lambda invocations
discord_circuit = CircuitBreaker(
    name="discord_api",
    failure_threshold=5,
    recovery_timeout=60,
)

bedrock_circuit = CircuitBreaker(
    name="bedrock_api",
    failure_threshold=5,
    recovery_timeout=30,
)

mcp_circuit = CircuitBreaker(
    name="mcp_server",
    failure_threshold=3,
    recovery_timeout=120,
)
