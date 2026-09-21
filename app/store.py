import asyncio
import copy
import json
import time

from redis.asyncio import Redis


class MemoryStore:
    """Single-process local development store; entries are short-lived."""
    def __init__(self):
        self.values = {}
        self.lock = asyncio.Lock()

    def prune(self):
        now = time.time()
        self.values = {k: v for k, v in self.values.items() if v[0] > now}

    async def get(self, key):
        self.prune()
        return copy.deepcopy(self.values.get(key, (0, None))[1])

    async def set(self, key, value, ttl=900, nx=False):
        async with self.lock:
            self.prune()
            if nx and key in self.values:
                return False
            self.values[key] = (time.time() + ttl, copy.deepcopy(value))
            return True

    async def limit(self, key, count, seconds):
        async with self.lock:
            self.prune()
            expiry, current = self.values.get(key, (time.time() + seconds, 0))
            self.values[key] = (expiry, current + 1)
            return current < count

    async def close(self):
        pass


class RedisStore:
    def __init__(self, url):
        self.client = Redis.from_url(url, decode_responses=True, socket_connect_timeout=5, socket_timeout=5)

    async def get(self, key):
        value = await self.client.get('vq:' + key)
        return json.loads(value) if value is not None else None

    async def set(self, key, value, ttl=900, nx=False):
        return bool(await self.client.set('vq:' + key, json.dumps(value), ex=ttl, nx=nx))

    async def limit(self, key, count, seconds):
        result = await self.client.eval('''
            local n = redis.call('INCR', KEYS[1])
            if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
            return n
        ''', 1, 'vq:' + key, seconds)
        return result <= count

    async def close(self):
        await self.client.aclose()
