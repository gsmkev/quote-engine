import httpx
import pytest
from helpers import fx, replay_extractor

from quote_engine.adapters.api.app import create_app
from quote_engine.config import Settings

FINAL = {
    "quotes": [
        {
            "quote_id": "Q-001",
            "status": "draft",
            "conversations": ["wa-thread-411", "wa-thread-662"],
            "line_items": [
                {"sku": "ALFBTC-013-320100", "qty": 15},
                {"sku": "ALMCLC-0909-320100", "qty": 5},
                {"sku": "AVMICS-1A-137050", "qty": 5},
            ],
        },
        {
            "quote_id": "Q-002",
            "status": "draft",
            "conversations": ["wa-thread-411", "wa-thread-662"],
            "line_items": [{"sku": "ARACBL-03-122244", "qty": 4}],
        },
    ]
}


@pytest.fixture
async def client(pg_url, session_factory, catalog):
    settings = Settings(
        database_url=pg_url, extractor_mode="replay", wait_timeout_s=30, poll_interval_s=0.05
    )
    app = create_app(settings, extractor=replay_extractor(catalog), run_inline_worker=True)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
            yield c


async def post_all(c, names):
    for name in names:
        path = "/v1/conversations" if name == "phase1" else "/v1/messages"
        r = await c.post(f"{path}?wait=true", json=fx(name))
        assert r.status_code == 200, r.text
    return r


async def test_phase1_wait_processed(client):
    r = await client.post("/v1/conversations?wait=true", json=fx("phase1"))
    assert r.status_code == 200
    assert r.json()["status"] == "processed"


async def test_challenge_final_state(client):
    await post_all(client, ["phase1", "event1", "event2", "event3", "event4"])
    r = await client.get("/v1/quotes", params={"customer": "C-10029"})
    assert r.json() == FINAL


async def test_duplicate_and_conflict(client):
    await post_all(client, ["phase1", "event1", "event2", "event3", "event4"])
    r = await client.post("/v1/messages", json=fx("event4"))
    assert r.status_code == 200 and r.json()["status"] == "duplicate"
    r = await client.post("/v1/messages", json={**fx("event4"), "text": "otra cosa"})
    assert r.status_code == 409
    assert r.json() == {"error": "message_id reused with different payload"}


async def test_async_accept_and_inbox(client):
    r = await client.post("/v1/conversations", json=fx("phase1"))
    assert r.status_code == 202
    seq = r.json()["inbox_seq"]
    assert r.json()["status_url"] == f"/v1/inbox/{seq}"
    assert (await client.get(f"/v1/inbox/{seq}")).status_code == 200
    assert (await client.get("/v1/inbox/9999")).status_code == 404


async def test_malformed_422(client):
    body = fx("event1")
    del body["message_id"]
    assert (await client.post("/v1/messages", json=body)).status_code == 422


async def test_reads(client):
    await post_all(client, ["phase1", "event1", "event2", "event3", "event4"])
    r = await client.get("/v1/quotes/Q-001")
    assert r.json()["document_type"] == "Oferta_de_Venta"
    assert (await client.get("/v1/quotes/Q-999")).status_code == 404
    hist = (await client.get("/v1/quotes/Q-002/history")).json()
    assert hist and all("message_text" in h for h in hist)
    assert any(h["message_text"] for h in hist)


async def test_review_flow(client):
    await post_all(client, ["phase1", "event1", "event2", "event3", "event4", "cancel"])
    reviews = (await client.get("/v1/reviews", params={"status": "open"})).json()
    assert len(reviews) == 1
    rv = reviews[0]
    assert len(rv["candidates"]) == 2 and all("version" in c for c in rv["candidates"])
    assert rv["message"]["text"] == "mejor cancelalo"
    cand = rv["candidates"][0]
    body = {
        "action": "apply",
        "quote_id": cand["quote_id"],
        "ops": [{"op": "cancel"}],
    }
    r = await client.post(
        f"/v1/reviews/{rv['id']}/resolve", json={**body, "expected_version": cand["version"] + 5}
    )
    assert r.status_code == 409
    assert r.json()["error"] == "stale_version"
    assert r.json()["current"]["version"] == cand["version"]
    r = await client.post(
        f"/v1/reviews/{rv['id']}/resolve", json={**body, "expected_version": cand["version"]}
    )
    assert r.status_code == 200
    assert r.json()["quote"]["status"] == "cancelled"
    r = await client.post(
        f"/v1/reviews/{rv['id']}/resolve", json={**body, "expected_version": cand["version"]}
    )
    assert r.status_code == 409
    assert (
        await client.post("/v1/reviews/999/resolve", json={"action": "dismiss"})
    ).status_code == 409


async def test_resolve_invalid_422(client):
    await post_all(client, ["phase1", "event1", "event2", "event3", "event4", "cancel"])
    [rv] = (await client.get("/v1/reviews")).json()
    r = await client.post(f"/v1/reviews/{rv['id']}/resolve", json={"action": "apply"})
    assert r.status_code == 422


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] == "ok" and body["model"] and "model_present" in body


async def test_inline_worker_catalog_has_defaults(pg_url, catalog):
    settings = Settings(database_url=pg_url, extractor_mode="replay", poll_interval_s=0.05)
    app = create_app(settings, extractor=replay_extractor(catalog), run_inline_worker=True)
    async with app.router.lifespan_context(app):
        assert app.state.catalog == catalog
        assert app.state.catalog.defaults
