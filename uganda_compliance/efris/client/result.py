"""Typed result + exception types for EFRIS calls.

Replaces the historical `(success: bool, response: str | dict)` tuple convention.
The legacy `efris_api.make_post` shim still returns the tuple for backwards
compatibility; new code should use `EfrisResponse` directly.
"""
from dataclasses import dataclass, field


class EfrisError(Exception):
    """Raised when URA returns a non-success returnCode or transport fails."""

    def __init__(
        self,
        message: str,
        interface_code: str | None = None,
        return_code: str | None = None,
        request_id: str | None = None,
        log_name: str | None = None,
        partial_failures: list | None = None,
    ):
        super().__init__(message)
        self.message = message
        self.interface_code = interface_code
        self.return_code = return_code
        self.request_id = request_id
        self.log_name = log_name
        self.partial_failures = partial_failures or []


@dataclass
class EfrisResponse:
    ok: bool
    interface_code: str
    request_id: str
    data: dict | list | None = None
    error_code: str | None = None
    error_message: str | None = None
    log_name: str | None = None
    partial_failures: list = field(default_factory=list)

    def raise_for_error(self):
        if not self.ok:
            raise EfrisError(
                self.error_message or "EFRIS call failed",
                interface_code=self.interface_code,
                return_code=self.error_code,
                request_id=self.request_id,
                log_name=self.log_name,
                partial_failures=self.partial_failures,
            )

    def as_legacy_tuple(self):
        """Translate to the legacy `(bool, str|dict)` shape used across the codebase."""
        if self.ok:
            return True, self.data
        return False, self.error_message or "EFRIS call failed"
