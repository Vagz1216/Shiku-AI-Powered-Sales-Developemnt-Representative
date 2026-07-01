import asyncio

from utils import auth


class _FakeResponse:
    status_code = 200

    def json(self):
        return {
            "primary_email_address_id": "email_1",
            "email_addresses": [{"id": "email_1", "email_address": "person@example.com"}],
            "first_name": "Test",
            "last_name": "User",
        }


class _EmptyFakeResponse:
    status_code = 404

    def json(self):
        return {}


class _FakeAsyncClient:
    calls = 0

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, *args, **kwargs):
        type(self).calls += 1
        return _FakeResponse()


class _SlowFakeAsyncClient(_FakeAsyncClient):
    async def get(self, *args, **kwargs):
        await asyncio.sleep(0.01)
        return await super().get(*args, **kwargs)


class _EmptyFakeAsyncClient(_FakeAsyncClient):
    async def get(self, *args, **kwargs):
        type(self).calls += 1
        return _EmptyFakeResponse()


class _FailingFakeAsyncClient(_FakeAsyncClient):
    async def get(self, *args, **kwargs):
        type(self).calls += 1
        raise TimeoutError("clerk timeout")


def test_clerk_user_enrichment_cache_reuses_profile(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "clerk_user_cache_ttl_seconds", 300)
    _FakeAsyncClient.calls = 0

    clerk_auth = auth.ClerkAuth()

    first = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))
    second = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))

    assert first["email"] == "person@example.com"
    assert first["name"] == "Test User"
    assert second["email"] == "person@example.com"
    assert _FakeAsyncClient.calls == 1


def test_clerk_user_enrichment_cache_can_be_disabled(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "clerk_user_cache_ttl_seconds", 0)
    _FakeAsyncClient.calls = 0

    clerk_auth = auth.ClerkAuth()

    asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))
    asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))

    assert _FakeAsyncClient.calls == 2


def test_clerk_user_enrichment_deduplicates_concurrent_fetches(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth.httpx, "AsyncClient", _SlowFakeAsyncClient)
    monkeypatch.setattr(settings, "clerk_user_cache_ttl_seconds", 300)
    _SlowFakeAsyncClient.calls = 0

    clerk_auth = auth.ClerkAuth()

    async def enrich_all():
        return await asyncio.gather(
            clerk_auth.enrich_payload({"sub": "user_1"}),
            clerk_auth.enrich_payload({"sub": "user_1"}),
            clerk_auth.enrich_payload({"sub": "user_1"}),
        )

    results = asyncio.run(enrich_all())

    assert all(result["email"] == "person@example.com" for result in results)
    assert _SlowFakeAsyncClient.calls == 1


def test_clerk_user_enrichment_caches_empty_response_briefly(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth.httpx, "AsyncClient", _EmptyFakeAsyncClient)
    monkeypatch.setattr(settings, "clerk_user_cache_ttl_seconds", 300)
    monkeypatch.setattr(settings, "clerk_user_enrichment_circuit_cooldown_seconds", 30)
    _EmptyFakeAsyncClient.calls = 0

    clerk_auth = auth.ClerkAuth()

    first = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))
    second = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))

    assert first == {"sub": "user_1"}
    assert second == {"sub": "user_1"}
    assert _EmptyFakeAsyncClient.calls == 1


def test_clerk_user_enrichment_caches_failure_briefly(monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth.httpx, "AsyncClient", _FailingFakeAsyncClient)
    monkeypatch.setattr(settings, "clerk_user_cache_ttl_seconds", 300)
    monkeypatch.setattr(settings, "clerk_user_enrichment_circuit_cooldown_seconds", 30)
    _FailingFakeAsyncClient.calls = 0

    clerk_auth = auth.ClerkAuth()

    first = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))
    second = asyncio.run(clerk_auth.enrich_payload({"sub": "user_1"}))

    assert first == {"sub": "user_1"}
    assert second == {"sub": "user_1"}
    assert _FailingFakeAsyncClient.calls == 1
