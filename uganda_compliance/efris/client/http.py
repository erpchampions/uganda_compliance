"""HTTP transport for URA EFRIS.

A single `requests.Session` with connection pooling, idempotent retries on
transient 5xx responses, and a default timeout. The legacy `post_req` did
none of these — a stalled URA could hang a worker indefinitely.
"""
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .logger import get_logger


DEFAULT_CONNECT_TIMEOUT = 30
DEFAULT_READ_TIMEOUT = 60
RETRY_TOTAL = 3
RETRY_BACKOFF_FACTOR = 0.5
RETRY_STATUS_FORCELIST = (502, 503, 504)


def _build_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=RETRY_TOTAL,
        backoff_factor=RETRY_BACKOFF_FACTOR,
        status_forcelist=RETRY_STATUS_FORCELIST,
        allowed_methods=frozenset(["POST"]),
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


_session: requests.Session | None = None


def get_session() -> requests.Session:
    global _session
    if _session is None:
        _session = _build_session()
    return _session


def post_req(
    data: str,
    url: str,
    *,
    interface_code: str | None = None,
    request_id: str | None = None,
    connect_timeout: int = DEFAULT_CONNECT_TIMEOUT,
    read_timeout: int = DEFAULT_READ_TIMEOUT,
) -> str:
    """POST raw JSON to URA and return the response text.

    Raises `requests.RequestException` on transport error after retries.
    """
    log = get_logger()
    log.info(
        f"EFRIS POST url={url} interfaceCode={interface_code} dataExchangeId={request_id}"
    )
    response = get_session().post(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        timeout=(connect_timeout, read_timeout),
    )
    log.info(
        f"EFRIS RESP status={response.status_code} interfaceCode={interface_code} "
        f"dataExchangeId={request_id} bytes={len(response.content)}"
    )
    return response.text
