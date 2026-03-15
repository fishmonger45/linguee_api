from contextlib import asynccontextmanager
from typing import Annotated

import httpx
import structlog
from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse, RedirectResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from linguee_api.cache import Cache, _cache_key, cached_fetch, create_cache
from linguee_api.client import (
    CaptchaError,
    LingueeError,
    _build_autocomplete_url,
    _build_url,
    fetch_autocompletions,
    fetch_search,
)
from linguee_api.config import settings
from linguee_api.languages import LanguageCode
from linguee_api.logging import setup_logging
from linguee_api.models import (
    AutocompletionItem,
    Correction,
    Example,
    ExternalSource,
    FollowCorrections,
    Lemma,
    NotFound,
    ParseError,
    SearchResult,
)
from linguee_api.parser import parse_autocompletions, parse_search_result

log = structlog.get_logger()

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    log.info("starting")

    if settings.sentry_dsn:
        try:
            import sentry_sdk

            sentry_sdk.init(dsn=settings.sentry_dsn)
            log.info("sentry_enabled")
        except ImportError:
            log.warning("sentry_sdk_not_installed")

    app.state.http_client = httpx.AsyncClient(timeout=10.0)
    app.state.cache = await create_cache()
    yield
    await app.state.http_client.aclose()
    log.info("shutdown")


app = FastAPI(title="Linguee API", version="2.0.0", lifespan=lifespan)
app.state.limiter = limiter

UNPROTECTED_PATHS = {"/health", "/openapi.json", "/docs", "/redoc"}


@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    if settings.api_key and request.url.path not in UNPROTECTED_PATHS:
        key = request.headers.get("X-API-Key")
        if key != settings.api_key:
            return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key"})
    return await call_next(request)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _do_search(
    request: Request,
    query: str,
    src: LanguageCode,
    dst: LanguageCode,
    follow_corrections: FollowCorrections = FollowCorrections.on_empty_translations,
) -> SearchResult:
    client: httpx.AsyncClient = request.app.state.http_client
    cache: Cache = request.app.state.cache
    url = _build_url(src, dst, query)
    key = _cache_key(url)

    try:
        html = await cached_fetch(cache, key, lambda: fetch_search(client, src, dst, query))
    except CaptchaError as e:
        raise LingueeError(429, "Too many requests — Linguee rate limit hit") from e
    except httpx.TimeoutException as e:
        raise LingueeError(502, "Linguee timed out") from e

    result = parse_search_result(html)

    if isinstance(result, ParseError):
        raise LingueeError(500, result.message)
    if isinstance(result, NotFound):
        raise LingueeError(404, f"No results found for '{query}'")

    if isinstance(result, Correction):
        if follow_corrections == FollowCorrections.never:
            raise LingueeError(404, f"No results found for '{query}'")
        return await _do_search(request, result.text, src, dst, FollowCorrections.never)

    if (
        follow_corrections == FollowCorrections.on_empty_translations
        and isinstance(result, SearchResult)
        and not result.lemmas
        and result.correct_query
    ):
        return await _do_search(request, result.correct_query, src, dst, FollowCorrections.never)

    return result


@app.get("/api/v2/translations", response_model=list[Lemma])
@limiter.limit(settings.rate_limit)
async def translations(
    request: Request,
    query: Annotated[str, Query(min_length=1)],
    src: LanguageCode,
    dst: LanguageCode,
    guess_direction: bool = False,
    follow_corrections: FollowCorrections = FollowCorrections.on_empty_translations,
):
    try:
        result = await _do_search(request, query, src, dst, follow_corrections)
        return result.lemmas
    except LingueeError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    except CaptchaError:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})


@app.get("/api/v2/examples", response_model=list[Example])
@limiter.limit(settings.rate_limit)
async def examples(
    request: Request,
    query: Annotated[str, Query(min_length=1)],
    src: LanguageCode,
    dst: LanguageCode,
    guess_direction: bool = False,
    follow_corrections: FollowCorrections = FollowCorrections.on_empty_translations,
):
    try:
        result = await _do_search(request, query, src, dst, follow_corrections)
        return result.examples
    except LingueeError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    except CaptchaError:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})


@app.get("/api/v2/external_sources", response_model=list[ExternalSource])
@limiter.limit(settings.rate_limit)
async def external_sources(
    request: Request,
    query: Annotated[str, Query(min_length=1)],
    src: LanguageCode,
    dst: LanguageCode,
    guess_direction: bool = False,
    follow_corrections: FollowCorrections = FollowCorrections.on_empty_translations,
):
    try:
        result = await _do_search(request, query, src, dst, follow_corrections)
        return result.external_sources
    except LingueeError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})
    except CaptchaError:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})


@app.get("/api/v2/autocompletions", response_model=list[AutocompletionItem])
@limiter.limit(settings.rate_limit)
async def autocompletions(
    request: Request,
    query: Annotated[str, Query(min_length=1)],
    src: LanguageCode,
    dst: LanguageCode,
):
    client: httpx.AsyncClient = request.app.state.http_client
    cache: Cache = request.app.state.cache
    url = _build_autocomplete_url(src, dst, query)
    key = _cache_key(url)

    try:
        raw = await cached_fetch(cache, key, lambda: fetch_autocompletions(client, src, dst, query))
    except CaptchaError:
        return JSONResponse(status_code=429, content={"detail": "Too many requests"})
    except LingueeError as e:
        return JSONResponse(status_code=e.status_code, content={"detail": e.detail})

    items = parse_autocompletions(raw)
    return [
        AutocompletionItem(
            text=item.get("phrase", ""),
            pos=item.get("wordType") or None,
            translations=[
                t.get("phrase", "") for t in item.get("translations", []) if t.get("phrase")
            ],
        )
        for item in items
        if item.get("phrase")
    ]
