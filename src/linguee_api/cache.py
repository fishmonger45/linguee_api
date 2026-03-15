import hashlib
import time
from pathlib import Path
from typing import Protocol

import structlog

from linguee_api.config import settings

log = structlog.get_logger()


class Cache(Protocol):
    async def get(self, key: str) -> str | None: ...
    async def set(self, key: str, value: str, ttl: int) -> None: ...


def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


class MemoryCache:
    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def set(self, key: str, value: str, ttl: int) -> None:
        self._store[key] = value


class RedisCache:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    async def get(self, key: str) -> str | None:
        val = await self._redis.get(key)
        if val is not None:
            return val.decode() if isinstance(val, bytes) else val
        return None

    async def set(self, key: str, value: str, ttl: int) -> None:
        await self._redis.set(key, value, ex=ttl)


async def create_cache() -> Cache:
    if settings.redis_url:
        try:
            import redis.asyncio as aioredis

            client = aioredis.from_url(settings.redis_url, decode_responses=False)
            await client.ping()
            log.info("cache_backend", backend="redis")
            return RedisCache(client)
        except Exception as e:
            log.warning("redis_unavailable", error=str(e))

    log.info("cache_backend", backend="memory")
    return MemoryCache()


class DiskCache:
    def __init__(self, ttl: int = 86400) -> None:
        self._dir = Path.home() / ".cache" / "linguee"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._ttl = ttl

    async def get(self, key: str) -> str | None:
        p = self._dir / key
        if not p.exists():
            return None
        if time.time() - p.stat().st_mtime > self._ttl:
            p.unlink(missing_ok=True)
            return None
        return p.read_text()

    async def set(self, key: str, value: str, ttl: int) -> None:
        p = self._dir / key
        p.write_text(value)


async def cached_fetch(cache: Cache, key: str, fetcher) -> str:
    cached = await cache.get(key)
    if cached is not None:
        log.debug("cache_hit", key=key[:16])
        return cached

    log.debug("cache_miss", key=key[:16])
    result = await fetcher()
    await cache.set(key, result, settings.cache_ttl)
    return result
