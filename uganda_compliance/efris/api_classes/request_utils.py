"""Legacy compatibility shim.

Envelope construction lives in `efris.client.envelope`; HTTP transport lives
in `efris.client.http`. This module re-exports the small surface used by the
older code paths so imports keep working.
"""
from uganda_compliance.efris.client.envelope import (
    build_envelope,
    get_ug_time_str,
    guidv4,
)
from uganda_compliance.efris.client.http import post_req as _new_post_req


def fetch_data():
    """Legacy name for the request envelope builder."""
    return build_envelope()


def post_req(data, mode_post_url):
    """Legacy `(data, url)` signature. New callers should use `efris.client.http.post_req`."""
    return _new_post_req(data, mode_post_url)


__all__ = ["fetch_data", "guidv4", "post_req", "get_ug_time_str"]
