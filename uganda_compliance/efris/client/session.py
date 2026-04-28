"""URA AES session-key cache.

URA's T104 handshake yields an AES key that's reusable for the device's
session. The legacy code re-ran T104 on every `make_post`, doubling the
number of round-trips. We cache per `(tin, device_no, mode)` in `frappe.cache`
with a configurable TTL.

On decrypt failure (stale key after URA rotation), the caller invalidates
the cache via `invalidate(...)` and the next call performs a fresh handshake.
"""
import frappe

from .logger import get_logger

# URA documents an 8h session lifetime; default to 6h for headroom.
DEFAULT_TTL_SECONDS = 6 * 60 * 60
_CACHE_NAMESPACE = "efris:aes_key"


def _key(tin: str, device_no: str, mode_url: str) -> str:
    return f"{_CACHE_NAMESPACE}:{tin}:{device_no}:{mode_url}"


def get_cached(tin: str, device_no: str, mode_url: str) -> bytes | None:
    raw = frappe.cache().get_value(_key(tin, device_no, mode_url))
    if not raw:
        return None
    if isinstance(raw, str):
        raw = raw.encode("latin-1")
    return raw


def set_cached(
    tin: str,
    device_no: str,
    mode_url: str,
    aes_key: bytes,
    ttl: int = DEFAULT_TTL_SECONDS,
) -> None:
    frappe.cache().set_value(
        _key(tin, device_no, mode_url),
        aes_key.decode("latin-1"),
        expires_in_sec=ttl,
    )
    get_logger().info(
        f"EFRIS AES key cached tin={tin} device={device_no} ttl={ttl}s"
    )


def invalidate(tin: str, device_no: str, mode_url: str) -> None:
    frappe.cache().delete_value(_key(tin, device_no, mode_url))
    get_logger().info(f"EFRIS AES key invalidated tin={tin} device={device_no}")
