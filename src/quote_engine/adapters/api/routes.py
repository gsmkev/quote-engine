import asyncio
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

from quote_engine.adapters.api.schemas import QuoteDetail, QuoteOut, quote_version
from quote_engine.adapters.db.uow import UnitOfWork
from quote_engine.application.ingest import (
    Conflict,
    ConversationIn,
    Duplicate,
    IngestResult,
    MessageIn,
    ingest_conversation,
    ingest_message,
)
from quote_engine.application.reviews import ResolveIn, ReviewNotOpen, StaleVersion, resolve_review
from quote_engine.domain.quote import DomainError

router = APIRouter()


def _uow(request: Request) -> UnitOfWork:
    return UnitOfWork(request.app.state.session_factory)


async def _inbox(request: Request, seq: int) -> dict[str, Any] | None:
    async with _uow(request) as uow:
        row = (
            (
                await uow.session.execute(
                    text("SELECT seq, status, decision, error FROM inbox WHERE seq = :s"),
                    {"s": seq},
                )
            )
            .mappings()
            .one_or_none()
        )
    return None if row is None else dict(row)


async def _respond(request: Request, result: IngestResult, wait: bool) -> JSONResponse:
    if isinstance(result, Conflict):
        return JSONResponse({"error": "message_id reused with different payload"}, status_code=409)
    if isinstance(result, Duplicate):
        return JSONResponse({"status": "duplicate", "inbox_seq": result.seq})
    seq = result.seq
    if wait:
        timeout = request.app.state.settings.wait_timeout_s
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            row = await _inbox(request, seq)
            if row and row["status"] != "pending":
                return JSONResponse(
                    {"inbox_seq": seq, "status": row["status"], "decision": row["decision"]}
                )
            await asyncio.sleep(0.25)
    return JSONResponse({"inbox_seq": seq, "status_url": f"/v1/inbox/{seq}"}, status_code=202)


@router.post("/v1/conversations")
async def post_conversation(body: ConversationIn, request: Request, wait: bool = False):
    async with _uow(request) as uow:
        result = await ingest_conversation(uow, body)
    return await _respond(request, result, wait)


@router.post("/v1/messages")
async def post_message(body: MessageIn, request: Request, wait: bool = False):
    async with _uow(request) as uow:
        result = await ingest_message(uow, body)
    return await _respond(request, result, wait)


@router.get("/v1/inbox/{seq}")
async def get_inbox(seq: int, request: Request):
    row = await _inbox(request, seq)
    if row is None:
        raise HTTPException(404, "inbox item not found")
    return row


@router.get("/v1/quotes")
async def list_quotes(customer: str, request: Request) -> dict[str, list[QuoteOut]]:
    async with _uow(request) as uow:
        quotes = await uow.quotes.list_by_customer(customer)
    return {"quotes": [QuoteOut.of(q) for q in quotes]}


@router.get("/v1/quotes/{quote_id}")
async def get_quote(quote_id: str, request: Request) -> QuoteDetail:
    async with _uow(request) as uow:
        q = await uow.quotes.get(quote_id)
    if q is None:
        raise HTTPException(404, "quote not found")
    return QuoteDetail(**QuoteOut.of(q).model_dump())


@router.get("/v1/quotes/{quote_id}/history")
async def quote_history(quote_id: str, request: Request):
    async with _uow(request) as uow:
        if await uow.quotes.get(quote_id) is None:
            raise HTTPException(404, "quote not found")
        return await uow.quotes.history(quote_id)


@router.get("/v1/reviews")
async def list_reviews(request: Request, status: str = "open", customer: str | None = None):
    async with _uow(request) as uow:
        reviews = await uow.reviews.list(status, customer)
        for rv in reviews:
            rv["candidates"] = [
                quote_version(q)
                for i in rv.pop("candidate_quote_ids")
                if (q := await uow.quotes.get(i))
            ]
    return reviews


@router.post("/v1/reviews/{review_id}/resolve")
async def resolve(review_id: int, body: ResolveIn, request: Request):
    try:
        async with _uow(request) as uow:
            review, quote = await resolve_review(uow, review_id, body)
    except ReviewNotOpen as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    except StaleVersion as e:
        return JSONResponse(
            {"error": "stale_version", "current": quote_version(e.current)}, status_code=409
        )
    except (DomainError, ValueError) as e:
        return JSONResponse({"error": str(e)}, status_code=422)
    return {"review": review, "quote": QuoteOut.of(quote) if quote else None}


@router.get("/health")
async def health(request: Request):
    settings = request.app.state.settings
    out: dict[str, Any] = {"db": "ok", "llm": "ok", "model": settings.llm_model}
    try:
        async with _uow(request) as uow:
            await uow.session.execute(text("SELECT 1"))
    except Exception:
        out["db"] = "down"
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(f"{settings.llm_base_url.rstrip('/')}/models")
            r.raise_for_status()
        # Docker Model Runner lists HF models as "huggingface.co/<lowercased ref>".
        want = settings.llm_model.removeprefix("hf.co/").removeprefix("huggingface.co/").lower()
        out["model_present"] = any(
            m.get("id", "").removeprefix("huggingface.co/").lower() == want
            for m in r.json()["data"]
        )
    except Exception:
        out["llm"] = "down"
        out["model_present"] = False
    return JSONResponse(out, status_code=200 if out["db"] == "ok" else 503)
