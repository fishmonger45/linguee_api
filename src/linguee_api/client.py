import httpx
import structlog
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from linguee_api.languages import LANGUAGE_NAMES

log = structlog.get_logger()

LINGUEE_BASE = "https://www.linguee.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class CaptchaError(Exception):
    pass


class LingueeError(Exception):
    def __init__(self, status_code: int, detail: str = ""):
        self.status_code = status_code
        self.detail = detail
        super().__init__(detail)


def _build_url(src: str, dst: str, query: str, ajax: bool = True) -> str:
    src_name = LANGUAGE_NAMES[src]
    dst_name = LANGUAGE_NAMES[dst]
    url = f"{LINGUEE_BASE}/{src_name}-{dst_name}/search"
    params = {"query": query}
    if ajax:
        params["ajax"] = "1"
    return f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"


def _build_autocomplete_url(src: str, dst: str, query: str) -> str:
    src_name = LANGUAGE_NAMES[src]
    dst_name = LANGUAGE_NAMES[dst]
    return f"{LINGUEE_BASE}/{src_name}-{dst_name}/search?qe={query}&source=auto&cw=350"


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_search(client: httpx.AsyncClient, src: str, dst: str, query: str) -> str:
    url = _build_url(src, dst, query)
    log.debug("fetching_linguee", url=url)
    resp = await client.get(url, headers=HEADERS)
    if resp.status_code == 503:
        raise CaptchaError("Linguee returned 503 — likely CAPTCHA")
    if resp.status_code != 200:
        raise LingueeError(resp.status_code, f"Linguee returned {resp.status_code}")
    return resp.text


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=4),
    reraise=True,
)
async def fetch_autocompletions(client: httpx.AsyncClient, src: str, dst: str, query: str) -> str:
    url = _build_autocomplete_url(src, dst, query)
    log.debug("fetching_autocompletions", url=url)
    resp = await client.get(url, headers=HEADERS)
    if resp.status_code == 503:
        raise CaptchaError("Linguee returned 503 — likely CAPTCHA")
    if resp.status_code != 200:
        raise LingueeError(resp.status_code, f"Linguee returned {resp.status_code}")
    return resp.text
