"""Circuit breaker for URA EFRIS calls.

When URA is degraded, the legacy code keeps hammering it for every doc save
and surfaces a flood of `frappe.throw` errors to users. The breaker tracks
consecutive failures per (company, interfaceCode) and short-circuits further
calls once a threshold is crossed, giving the upstream time to recover.

States, lifted from the standard pattern:

- **CLOSED**: requests pass through. Each failure increments a counter.
- **OPEN**: requests fail-fast for a cool-off window. No URA call is made.
- **HALF_OPEN**: after the window expires, the next call is allowed through
  as a probe. Success → CLOSED. Failure → back to OPEN.

State is kept in `frappe.cache` so it survives across requests within a
worker but resets across redis restarts (acceptable — the breaker is a
soft optimisation, not a correctness guarantee).
"""
import json
import time

import frappe

from .logger import get_logger

# Tunables — could be promoted to E Invoicing Settings fields later.
FAILURE_THRESHOLD = 5      # Consecutive failures before opening.
COOLOFF_SECONDS = 5 * 60   # How long OPEN lasts before HALF_OPEN probe.
KEY_TTL = 30 * 60          # Cache row lifetime when idle.

_NAMESPACE = "efris:breaker"


def _key(company: str, interface_code: str) -> str:
    return f"{_NAMESPACE}:{company}:{interface_code}"


def _read(company: str, interface_code: str) -> dict:
    raw = frappe.cache().get_value(_key(company, interface_code))
    if not raw:
        return {"state": "CLOSED", "failures": 0, "opened_at": 0}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except Exception:
            return {"state": "CLOSED", "failures": 0, "opened_at": 0}
    return raw


def _write(company: str, interface_code: str, state: dict) -> None:
    frappe.cache().set_value(
        _key(company, interface_code),
        json.dumps(state),
        expires_in_sec=KEY_TTL,
    )


def allow(company: str, interface_code: str) -> tuple[bool, str | None]:
    """Return (allowed, reason). Reason is set only when the call is rejected."""
    state = _read(company, interface_code)
    if state["state"] == "OPEN":
        elapsed = time.time() - state.get("opened_at", 0)
        if elapsed >= COOLOFF_SECONDS:
            # Transition to HALF_OPEN — let the next call probe.
            state["state"] = "HALF_OPEN"
            _write(company, interface_code, state)
            return True, None
        retry_in = int(COOLOFF_SECONDS - elapsed)
        return False, (
            f"EFRIS circuit breaker OPEN for {interface_code} (company={company}); "
            f"retry in {retry_in}s"
        )
    return True, None


def record_success(company: str, interface_code: str) -> None:
    state = _read(company, interface_code)
    if state.get("state") != "CLOSED" or state.get("failures"):
        get_logger().info(
            f"EFRIS breaker CLOSED interfaceCode={interface_code} company={company}"
        )
    _write(
        company,
        interface_code,
        {"state": "CLOSED", "failures": 0, "opened_at": 0},
    )


def record_failure(company: str, interface_code: str) -> None:
    state = _read(company, interface_code)
    failures = state.get("failures", 0) + 1
    if state.get("state") == "HALF_OPEN" or failures >= FAILURE_THRESHOLD:
        new_state = {
            "state": "OPEN",
            "failures": failures,
            "opened_at": time.time(),
        }
        get_logger().warning(
            f"EFRIS breaker OPEN interfaceCode={interface_code} "
            f"company={company} failures={failures}"
        )
    else:
        new_state = {
            "state": "CLOSED",
            "failures": failures,
            "opened_at": 0,
        }
    _write(company, interface_code, new_state)
