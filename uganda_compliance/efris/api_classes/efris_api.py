"""Legacy entry point preserved for backwards compatibility.

The transport now lives in `uganda_compliance.efris.client`. This module
exposes the historical `make_post(...)` returning a `(success, response)`
tuple so existing call sites do not need to change.
"""
from uganda_compliance.efris.client.transport import make_post_legacy as make_post

__all__ = ["make_post"]
