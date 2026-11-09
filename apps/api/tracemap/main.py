"""TraceMap v0.1 development API.

Development-only authentication and synchronous parsing are deliberately guarded.
Not a production service or real LLM integration.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import logging
import os
import re
import uuid
from typing import Any

from fastapi import FastAPI, Header, HTTPException, UploadFile, File, Request
from fastapi.exceptions import RequestValidationError
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from sqlalchemy import select, update, delete, func
from sqlalchemy.exc import SQLAlchemyError, OperationalError

from . import config  # noqa: F401  (loads .env before any TRACEMAP_* value is read — see config.py)
from .db import Base, Project, Source, Paragraph, Change, Draft, Idempotency, Job, engine_for, session_factory, now
from .core import (RuleError, uid, sha, canon, split_paragraphs, root_map,
                   validate_tree, verify_ref, apply_ops, purge_source, extractive_draft,
                   markdown_export, MAX_FILE_BYTES, MAX_TOTAL_CHARS, MAX_SOURCES,
                   EXTRACTIVE_SELECTION_POLICY)
from . import llm
from .pdf_worker import PDFParseError, parse_pdf_isolated

# Largest revision we accept from a client. Chosen to be far below the SQLite
# signed-64-bit limit (the CAS update writes expected + 1) and at the JavaScript
# Number.MAX_SAFE_INTEGER boundary so a round-tripped revision is lossless.
MAX_REVISION = 2 ** 53 - 1

LOGGER = logging.getLogger("tracemap")


def storage_error_status(exc: BaseException) -> tuple[int, str, str, bool]:
    """Map an unexpected/storage exception to the unified error contract.

    A pure function so it can be unit-tested without a live database. The
    client never receives driver text, SQL, or tracebacks (see GT-0020).
    """
    if isinstance(exc, OperationalError) and "locked" in str(exc).lower():
        return 503, "STORAGE_BUSY", "本地存储暂时繁忙，请稍后重试", True
    if isinstance(exc, SQLAlchemyError):
        return 500, "STORAGE_ERROR", "本地存储发生错误", False
    return 500, "INTERNAL_ERROR", "服务器内部错误", False


def _source_ids_in(value: Any) -> set[str]:
    """Collect source IDs from persisted JSON without trusting its shape."""
    found: set[str] = set()
    if isinstance(value, dict):
        source_id = value.get("sourceId")
        if isinstance(source_id, str) and source_id:
            found.add(source_id)
        for child in value.values():
            found.update(_source_ids_in(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_source_ids_in(child))
    return found


def purge_legacy_source_residue(Session) -> int:
    """Idempotently scrub pre-Phase-0 references whose Source row is gone.

    Older builds marked anchors source_deleted but retained copied quote text in
    map/history/draft JSON. Run once at app startup so an existing SQLite DB is
    brought under the new live-data deletion contract before serving requests.
    """
    affected_projects = 0
    with Session.begin() as s:
        projects = s.scalars(select(Project)).all()
        for project in projects:
            changes = s.scalars(select(Change).where(Change.project_id == project.id)).all()
            drafts = s.scalars(select(Draft).where(Draft.project_id == project.id)).all()
            candidate_ids = _source_ids_in(project.map_json)
            for change in changes:
                candidate_ids.update(_source_ids_in(change.before_json))
                candidate_ids.update(_source_ids_in(change.after_json))
            for draft in drafts:
                candidate_ids.update(_source_ids_in(draft.payload))
            if not candidate_ids:
                continue

            live_ids = set(s.scalars(
                select(Source.id).where(Source.project_id == project.id)
            ).all())
            missing_ids = candidate_ids - live_ids
            if not missing_ids:
                continue

            before = deepcopy(project.map_json)
            after = deepcopy(before)
            for source_id in sorted(missing_ids):
                after = purge_source(after, source_id)
            project.map_json = after

            for change in changes:
                before_snapshot = change.before_json
                after_snapshot = change.after_json
                for source_id in sorted(missing_ids):
                    before_snapshot = purge_source(before_snapshot, source_id)
                    after_snapshot = purge_source(after_snapshot, source_id)
                change.before_json = before_snapshot
                change.after_json = after_snapshot

            # A stale candidate may carry paraphrases or operations not fully
            # represented by EvidenceRefs. Clear every draft in the affected
            # project rather than attempting unsafe partial redaction.
            for draft in drafts:
                draft.payload = {"invalidatedReason": "legacy_source_purged"}
                draft.status = "invalidated"

            safe_before = deepcopy(before)
            for source_id in sorted(missing_ids):
                safe_before = purge_source(safe_before, source_id)
            rev_before = project.revision
            project.revision += 1
            project.updated_at = now()
            s.add(Change(
                id=uid(), project_id=project.id, owner_id=project.owner_id,
                rev_before=rev_before, rev_after=project.revision,
                kind="source_delete_legacy_purge",
                before_json=safe_before, after_json=after,
            ))
            affected_projects += 1

    if affected_projects:
        LOGGER.warning(
            "scrubbed legacy deleted-source residue in %s project(s)",
            affected_projects,
        )
    return affected_projects


class NewProject(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    goal: str = Field(default="", max_length=1000)


class TextPayload(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=80000)
    format: str = "text"


class GeneratePayload(BaseModel):
    goal: str = Field(min_length=1, max_length=1000)
    sourceIds: list[str] = Field(min_length=1, max_length=5)
    language: str = "zh-CN"


class OperationsPayload(BaseModel):
    operations: list[dict]


class PatchPayload(BaseModel):
    targetNodeId: str
    baseRevision: int
    operation: str


class ApplyPayload(BaseModel):
    acceptedOpIds: list[str]


def project_view(p: Project) -> dict:
    return {"id": p.id, "title": p.title, "goal": p.goal, "revision": p.revision,
            "createdAt": p.created_at.isoformat(), "updatedAt": p.updated_at.isoformat()}


def source_view(s: Source) -> dict:
    return {"id": s.id, "projectId": s.project_id, "title": s.title, "kind": s.kind,
            "sha256": s.sha256, "status": s.status, "extractedCharCount": s.extracted_count}


def problem(code, message, status=422):
    raise RuleError(code, message, status)


def create_app(database_url: str | None = None) -> FastAPI:
    env = os.getenv("TRACEMAP_ENV", "development")
    if env != "development":
        raise RuntimeError("Only local development is enabled; production/staging require real authentication, isolated PDF workers and retention controls")
    database_url = database_url or os.getenv("TRACEMAP_DATABASE_URL", "sqlite:///./tracemap-dev.db")
    engine = engine_for(database_url)
    Base.metadata.create_all(engine)  # development convenience; production requires migrations
    Session = session_factory(engine)
    purge_legacy_source_residue(Session)

    app = FastAPI(title="TraceMap Development API", version="0.1.0", description="Dev-only auth, extractive demonstration generation; not yet real AI.")
    app.state.engine = engine
    app.state.Session = Session
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

    @app.middleware("http")
    async def _local_dev_only(request: Request, call_next):
        # Defense in depth for this deliberately insecure development identity.
        # Reject common reverse-proxy metadata rather than treating a loopback
        # proxy as if it were the original local browser.
        proxy_headers = {
            "forwarded", "x-forwarded-for", "x-forwarded-host",
            "x-forwarded-proto", "x-forwarded-port", "x-real-ip",
            "x-original-forwarded-for", "x-client-ip", "true-client-ip",
            "cf-connecting-ip",
        }
        if any(name in request.headers for name in proxy_headers):
            return JSONResponse(status_code=403, content={"error": {
                "code": "DEV_PROXY_HEADERS_REJECTED",
                "message": "开发接口不接受反向代理转发请求", "retryable": False}})

        host = (request.url.hostname or "").lower()
        if host not in {"127.0.0.1", "::1", "localhost", "testserver"}:
            return JSONResponse(status_code=403, content={"error": {
                "code": "DEV_HOST_NOT_LOCAL",
                "message": "开发接口仅接受本机 Host", "retryable": False}})

        client_ip = request.client.host if request.client else None
        if client_ip not in {"127.0.0.1", "::1", "localhost", "testclient"}:
            return JSONResponse(status_code=403, content={"error": {
                "code": "DEV_LOCAL_ONLY", "message": "开发接口仅允许本地回环访问", "retryable": False}})
        return await call_next(request)

    @app.exception_handler(RuleError)
    async def _rule_error(_request: Request, exc: RuleError):
        return JSONResponse(status_code=exc.status, content={"error": {"code": exc.code, "message": exc.message, "retryable": False}})

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError):
        return JSONResponse(status_code=422, content={"error": {
            "code": "SCHEMA_INVALID", "message": "请求字段格式无效", "retryable": False,
            "details": [{"field": ".".join(str(p) for p in e.get("loc", [])), "type": e.get("type", "invalid")} for e in exc.errors()]}})

    @app.exception_handler(SQLAlchemyError)
    async def _storage_error(_request: Request, exc: SQLAlchemyError):
        status, code, message, retryable = storage_error_status(exc)
        LOGGER.error("storage error: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "retryable": retryable}})

    @app.exception_handler(Exception)
    async def _unhandled_error(_request: Request, exc: Exception):
        status, code, message, retryable = storage_error_status(exc)
        LOGGER.error("unhandled error: %s", type(exc).__name__, exc_info=exc)
        return JSONResponse(status_code=status, content={"error": {
            "code": code, "message": message, "retryable": retryable}})

    def owner(authorization: str | None) -> str:
        if not authorization or not re.fullmatch(r"Bearer dev-[a-z0-9][a-z0-9_-]{0,40}", authorization):
            problem("UNAUTHENTICATED", "开发模式仅接受 Bearer dev-<name>，不可用于生产", 401)
        return authorization[11:]

    def get_project(s, pid: str, user: str):
        p = s.scalar(select(Project).where(Project.id == pid, Project.owner_id == user))
        if p is None:
            problem("NOT_FOUND", "项目不存在", 404)
        return p

    def get_revision(if_match: str | None) -> int:
        # Bound the parsed revision so a client-supplied count can never overflow
        # the 64-bit INTEGER column during the CAS UPDATE (previously a 500).
        if not if_match or not re.fullmatch(r'"rev-[0-9]{1,19}"', if_match):
            problem("BAD_REQUEST", '必须提供 If-Match: "rev-N"', 400)
        value = int(if_match[5:-1])
        if value > MAX_REVISION:
            problem("BAD_REQUEST", 'If-Match 版本号超出支持范围', 400)
        return value

    def claim_revision(s, p: Project, expected: int):
        result = s.execute(update(Project).where(Project.id == p.id, Project.revision == expected)
                           .values(revision=expected + 1, updated_at=now()))
        if result.rowcount != 1:
            problem("REVISION_CONFLICT", "项目已更新，请重新加载并审阅", 409)
        p.revision = expected + 1
        return expected + 1

    def require_key(key: str | None):
        if not key or len(key) > 128 or len(key) < 8:
            problem("BAD_REQUEST", "写请求需要至少 8 字符的 Idempotency-Key", 400)
        return key

    def fingerprint(payload: Any) -> str:
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def replay(s, user: str, route: str, key: str, payload: Any):
        existing = s.scalar(select(Idempotency).where(Idempotency.owner_id == user,
                    Idempotency.scope == route, Idempotency.key == key))
        if existing:
            if existing.fingerprint != fingerprint(payload):
                problem("IDEMPOTENCY_KEY_REUSED", "同一个幂等键对应不同的请求内容", 409)
            return existing.response_json
        return None

    def record(s, user: str, route: str, key: str, payload: Any, response: dict, status=200):
        s.add(Idempotency(id=uid(), owner_id=user, scope=route, key=key,
                          fingerprint=fingerprint(payload), response_json=deepcopy(response), status_code=status))
        return response

    def paragraphs_of(s, pid: str):
        rows = s.execute(select(Paragraph.source_id, Paragraph.id, Paragraph.text)
                         .join(Source, Source.id == Paragraph.source_id)
                         .where(Source.project_id == pid, Source.status == "ready")).all()
        return {(r[0], r[1]): r[2] for r in rows}

    def source_limits(s, pid: str, new_chars: int):
        sources = s.scalars(select(Source).where(Source.project_id == pid)).all()
        if len(sources) >= MAX_SOURCES:
            problem("LIMIT_REACHED", "每个项目最多 5 份来源", 429)
        if sum(x.extracted_count for x in sources) + new_chars > MAX_TOTAL_CHARS:
            problem("PAYLOAD_TOO_LARGE", "每个项目最多提取 80,000 个 Unicode 码点", 413)

    def save_source(s, p, title, kind, text, page_chunks=None):
        text = canon(text)
        if not text.strip():
            problem("NO_EXTRACTABLE_TEXT", "文件没有可提取的文字，不支持 OCR", 422)
        source_limits(s, p.id, len(text))
        source_id = uid()
        source = Source(id=source_id, project_id=p.id, title=title, kind=kind,
                        sha256=sha(text), extracted_count=len(text), status="ready")
        s.add(source)
        s.flush()  # ensure referenced Source exists before Paragraph rows are inserted
        chunks = (split_paragraphs(text, source_id) if page_chunks is None else
                  [item for page_no, page in page_chunks for item in split_paragraphs(page, source_id, page_no)])
        # PDF page segmentation may include repeated paragraph IDs. Re-key each occurrence with ordinal.
        for ordinal, item in enumerate(chunks):
            p_id = sha(f"{source_id}\0v1\0{ordinal}\0{item['text']}")[:32]
            s.add(Paragraph(id=p_id, source_id=source_id, ordinal=ordinal,
                            page_no=item["pageNo"], text=item["text"], text_sha256=item["textSha256"]))
        if not chunks:
            problem("NO_EXTRACTABLE_TEXT", "找不到可引用的段落", 422)
        return source

    def append_change(s, p, before, after, expected, user, kind):
        """Keep source and map revisions in the same transaction and audit log."""
        cid = uid()
        s.add(Change(id=cid, project_id=p.id, owner_id=user, rev_before=expected,
                     rev_after=p.revision, kind=kind, before_json=deepcopy(before), after_json=deepcopy(after)))
        return {"revision": p.revision, "changeSetId": cid}

    def commit_map(s, p, before, after, expected, user, kind):
        validate_tree(after, paragraphs_of(s, p.id))
        claim_revision(s, p, expected)
        p.map_json = deepcopy(after)
        return append_change(s, p, before, after, expected, user, kind)

    @app.get("/health")
    def health():
        config = llm.public_config()
        return {"status": "ok", "mode": "development",
                "generationProvider": llm.active_backend(),
                "generationModel": config["model"],
                "llmConfigured": config["llmConfigured"]}

    @app.get("/api/v1/projects")
    def list_projects(authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            items = s.scalars(select(Project).where(Project.owner_id == user).order_by(Project.updated_at.desc())).all()
            return {"items": [project_view(p) for p in items]}

    @app.post("/api/v1/projects", status_code=201)
    def create_project(body: NewProject, authorization: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, key = owner(authorization), require_key(idempotency_key)
        with Session.begin() as s:
            payload = body.model_dump()
            if (prev := replay(s, user, "POST:/projects", key, payload)) is not None:
                return prev
            p = Project(id=uid(), owner_id=user, title=body.title, goal=body.goal, revision=0, map_json=root_map(body.title))
            s.add(p)
            s.flush()
            return record(s, user, "POST:/projects", key, payload, project_view(p), 201)

    @app.get("/api/v1/projects/{pid}")
    def read_project(pid: str, authorization: str | None = Header(None)):
        with Session() as s:
            return project_view(get_project(s, pid, owner(authorization)))

    @app.delete("/api/v1/projects/{pid}", status_code=202)
    def delete_project(pid: str, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            if (prev := replay(s, user, f"DELETE:{pid}", key, {"revision": expected})) is not None:
                return prev
            p = get_project(s, pid, user)
            claim_revision(s, p, expected)
            s.execute(delete(Project).where(Project.id == pid))
            return record(s, user, f"DELETE:{pid}", key, {"revision": expected}, {"deleted": True}, 202)

    @app.get("/api/v1/projects/{pid}/sources")
    def list_sources(pid: str, authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            get_project(s, pid, user)
            return {"items": [source_view(x) for x in s.scalars(select(Source).where(Source.project_id == pid)).all()]}

    @app.post("/api/v1/projects/{pid}/sources/text", status_code=202)
    def add_text_source(pid: str, body: TextPayload, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        if body.format not in {"text", "markdown"}:
            problem("UNSUPPORTED_MEDIA_TYPE", "仅支持 text、markdown", 415)
        with Session.begin() as s:
            payload = body.model_dump() | {"revision": expected}
            if (prev := replay(s, user, f"POST:{pid}:sources/text", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            source = save_source(s, p, body.title, body.format, body.text)
            revision = claim_revision(s, p, expected)
            append_change(s, p, p.map_json, p.map_json, expected, user, "source_add")
            job_id = uid()
            s.add(Job(id=job_id, project_id=pid, status="completed", kind="source_parse_sync", result_id=source.id))
            return record(s, user, f"POST:{pid}:sources/text", key, payload,
                          {"sourceId": source.id, "jobId": job_id, "status": "ready", "revision": revision}, 202)

    @app.post("/api/v1/projects/{pid}/sources", status_code=202)
    async def upload_source(pid: str, file: UploadFile = File(...), authorization: str | None = Header(None),
                            if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        content = await file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            problem("PAYLOAD_TOO_LARGE", "文件不能超过 10 MB", 413)
        filename = file.filename or "upload"
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        scope = f"POST:{pid}:sources"
        payload = {"filename": filename, "sha256": hashlib.sha256(content).hexdigest(), "revision": expected}

        # Check replay, ownership and source-count quota before parser work.
        # Re-check inside the final transaction for race safety.
        with Session() as s:
            if (prev := replay(s, user, scope, key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            source_limits(s, p.id, 0)

        pages = None
        if ext in ("txt", "md"):
            try:
                text = content.decode("utf-8-sig")
            except UnicodeDecodeError:
                problem("UNSUPPORTED_MEDIA_TYPE", "文本文件必须为 UTF-8", 415)
            if content.startswith(b"%PDF"):
                problem("UNSUPPORTED_MEDIA_TYPE", "文件内容与扩展名不匹配", 415)
            kind = "markdown" if ext == "md" else "text"
        elif ext == "pdf" and content.startswith(b"%PDF-"):
            try:
                pages = await run_in_threadpool(
                    parse_pdf_isolated, content, max_pages=100, max_chars=MAX_TOTAL_CHARS
                )
            except PDFParseError as exc:
                problem(exc.code, exc.message, exc.status)
            text = "\n\n".join(part for _, part in pages)
            kind = "pdf"
        else:
            problem("UNSUPPORTED_MEDIA_TYPE", "仅支持 UTF-8 .txt/.md 和有文本层的 PDF", 415)

        with Session.begin() as s:
            if (prev := replay(s, user, scope, key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            source = save_source(s, p, filename, kind, text, pages)
            revision = claim_revision(s, p, expected)
            append_change(s, p, p.map_json, p.map_json, expected, user, "source_add")
            job_id = uid()
            s.add(Job(id=job_id, project_id=pid, status="completed", kind="source_parse_sync", result_id=source.id))
            return record(s, user, scope, key, payload,
                          {"sourceId": source.id, "jobId": job_id, "status": "ready", "revision": revision}, 202)

    @app.get("/api/v1/projects/{pid}/sources/{sid}/paragraphs")
    def paragraphs(pid: str, sid: str, authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            get_project(s, pid, user)
            source = s.scalar(select(Source).where(Source.project_id == pid, Source.id == sid))
            if not source:
                problem("NOT_FOUND", "资料不存在", 404)
            items = s.scalars(select(Paragraph).where(Paragraph.source_id == sid).order_by(Paragraph.ordinal)).all()
            return {"items": [{"id": p.id, "sourceId": sid, "text": p.text, "pageNo": p.page_no,
                                 "ordinal": p.ordinal, "textSha256": p.text_sha256} for p in items]}

    @app.delete("/api/v1/projects/{pid}/sources/{sid}")
    def remove_source(pid: str, sid: str, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            scope = f"DELETE:{pid}:source:{sid}"
            payload = {"sid": sid, "revision": expected}
            if (prev := replay(s, user, scope, key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            source = s.scalar(select(Source).where(Source.project_id == pid, Source.id == sid))
            if not source:
                problem("NOT_FOUND", "资料不存在", 404)

            before = deepcopy(p.map_json)
            after = purge_source(before, sid)
            validate_tree(after, paragraphs_of(s, p.id))
            purged_nodes = len(before["nodes"]) - len(after["nodes"])
            claim_revision(s, p, expected)
            p.map_json = after

            # Drafts may contain source excerpts, model paraphrases or proposed
            # operations. Invalidate and clear all candidates rather than infer
            # partial provenance from transient model output.
            drafts = s.scalars(select(Draft).where(Draft.project_id == pid)).all()
            for draft in drafts:
                draft.payload = {"invalidatedReason": "source_purged"}
                draft.status = "invalidated"

            # Historical snapshots can contain copied exact quotes. Scrub every
            # revision before writing the deletion audit row.
            changes = s.scalars(select(Change).where(Change.project_id == pid)).all()
            for change in changes:
                change.before_json = purge_source(change.before_json, sid)
                change.after_json = purge_source(change.after_json, sid)

            s.execute(delete(Source).where(Source.id == sid))
            safe_before = purge_source(before, sid)
            append_change(s, p, safe_before, after, expected, user, "source_delete")
            result = {
                "revision": p.revision,
                "deletionMode": "permanent_purge",
                "purgedNodeCount": purged_nodes,
                "invalidatedDraftCount": len(drafts),
            }
            return record(s, user, scope, key, payload, result)

    @app.get("/api/v1/projects/{pid}/history")
    def list_history(pid: str, authorization: str | None = Header(None)):
        """Privacy-minimal revision audit; no original document/quote text."""
        with Session() as s:
            p = get_project(s, pid, owner(authorization))
            changes = s.scalars(select(Change).where(Change.project_id == pid)
                                .order_by(Change.rev_after.desc()).limit(20)).all()
            return {"items": [{"changeSetId": c.id, "kind": c.kind,
                    "revBefore": c.rev_before, "revAfter": c.rev_after,
                    "createdAt": c.created_at.isoformat(), "undone": c.undone,
                    "undoable": (not c.undone and c.rev_after == p.revision
                                 and c.kind in {"manual", "generation_demo", "patch_demo"})}
                    for c in changes]}

    @app.get("/api/v1/projects/{pid}/map")
    def read_map(pid: str, authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            p = get_project(s, pid, user)
            return JSONResponse({"revision": p.revision, **p.map_json}, headers={"ETag": f'"rev-{p.revision}"'})

    @app.post("/api/v1/projects/{pid}/nodes/ops")
    def apply_manual(pid: str, body: OperationsPayload, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            payload = body.model_dump() | {"revision": expected}
            if (prev := replay(s, user, f"POST:{pid}:ops", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            before = deepcopy(p.map_json)
            after = apply_ops(before, body.operations, paragraphs_of(s, pid))
            result = commit_map(s, p, before, after, expected, user, "manual")
            return record(s, user, f"POST:{pid}:ops", key, payload, result)

    @app.post("/api/v1/projects/{pid}/generate", status_code=202)
    def generate(pid: str, body: GeneratePayload, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        if body.language not in {"en", "zh-CN"} or len(set(body.sourceIds)) != len(body.sourceIds):
            problem("BAD_REQUEST", "语言或资料选择无效", 400)
        scope = f"POST:{pid}:generate"
        payload = body.model_dump() | {"revision": expected}
        # 1. Read-only prep: idempotency replay and source scoping. A write
        #    transaction is never held across the (slow, external) provider call.
        with Session() as s:
            if (prev := replay(s, user, scope, key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            if p.revision != expected:
                problem("REVISION_CONFLICT", "生成所基于的版本已经变化", 409)
            source_paragraphs: dict[str, list[dict]] = {}
            source_titles: dict[str, str] = {}
            for sid in body.sourceIds:
                source = s.scalar(select(Source).where(Source.project_id == pid, Source.id == sid, Source.status == "ready"))
                if not source:
                    problem("NOT_FOUND", "所选来源不存在", 404)
                source_titles[sid] = source.title
                source_paragraphs[sid] = [{"id": x.id, "ordinal": x.ordinal, "text": x.text} for x in
                     s.scalars(select(Paragraph).where(Paragraph.source_id == sid).order_by(Paragraph.ordinal)).all()]
            reference_paragraphs = paragraphs_of(s, pid)
        # 2. Compute a read-only candidate draft (deterministic demo, or the
        #    configured model when explicitly enabled). The model never writes.
        if llm.llm_ready():
            documents = [{"sourceId": sid, "title": source_titles[sid], "paragraphs": paras}
                         for sid, paras in source_paragraphs.items()]
            result = llm.draft_from_llm(body.goal, documents, reference_paragraphs, source_titles)
            tree = result["tree"]
            draft_meta = {"provider": result["provider"], "usage": result["usage"],
                          "droppedEvidenceCount": result["droppedEvidenceCount"],
                          "promptSha256": result["promptSha256"]}
            job_kind = "generation_llm_sync"
            response_meta = {"generationMode": "llm", "provider": result["provider"]}
        else:
            tree = extractive_draft(body.goal, source_paragraphs)
            draft_meta = {"selectionPolicy": EXTRACTIVE_SELECTION_POLICY}
            job_kind = "generation_sync_demo"
            response_meta = {"generationMode": "extractive_demo", "selectionPolicy": EXTRACTIVE_SELECTION_POLICY}
        validate_tree(tree, reference_paragraphs)
        # 3. Persist the draft; the live map is unchanged until an explicit commit.
        with Session.begin() as s:
            if (prev := replay(s, user, scope, key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            if p.revision != expected:
                problem("REVISION_CONFLICT", "生成所基于的版本已经变化", 409)
            draft = Draft(id=uid(), project_id=pid, base_revision=expected,
                          payload={"map": tree, "generationMode": response_meta["generationMode"], **draft_meta}, kind="generation")
            job = Job(id=uid(), project_id=pid, kind=job_kind, status="completed", result_id=draft.id)
            s.add_all([draft, job])
            return record(s, user, scope, key, payload,
                          {"jobId": job.id, "draftId": draft.id, "status": "completed", **response_meta}, 202)

    @app.get("/api/v1/jobs/{job_id}")
    def read_job(job_id: str, authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            job = s.scalar(select(Job).join(Project, Project.id == Job.project_id)
                           .where(Job.id == job_id, Project.owner_id == user))
            if not job:
                problem("NOT_FOUND", "任务不存在", 404)
            return {"id": job.id, "kind": job.kind, "status": job.status, "resultId": job.result_id}

    @app.get("/api/v1/projects/{pid}/generation-drafts/{did}")
    def get_draft(pid: str, did: str, authorization: str | None = Header(None)):
        with Session() as s:
            get_project(s, pid, owner(authorization))
            d = s.scalar(select(Draft).where(Draft.id == did, Draft.project_id == pid, Draft.kind == "generation"))
            if not d:
                problem("NOT_FOUND", "草稿不存在", 404)
            return {"draftId": d.id, "baseRevision": d.base_revision, "status": d.status, **d.payload}

    @app.post("/api/v1/projects/{pid}/generation-drafts/{did}/commit")
    def commit_draft(pid: str, did: str, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            payload = {"draft": did, "revision": expected}
            if (prev := replay(s, user, f"POST:{pid}:draft:{did}:commit", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            d = s.scalar(select(Draft).where(Draft.id == did, Draft.project_id == pid, Draft.kind == "generation"))
            if not d:
                problem("NOT_FOUND", "草稿不存在", 404)
            if d.status != "proposed" or d.base_revision != expected:
                problem("REVISION_CONFLICT", "该草稿已应用或基于旧版本", 409)
            result = commit_map(s, p, p.map_json, d.payload["map"], expected, user, "generation_demo")
            d.status = "accepted"
            return record(s, user, f"POST:{pid}:draft:{did}:commit", key, payload, result)

    @app.post("/api/v1/projects/{pid}/patches", status_code=202)
    def propose_patch(pid: str, body: PatchPayload, authorization: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, key = owner(authorization), require_key(idempotency_key)
        if body.operation not in {"questions", "challenge", "expand"}:
            problem("NOT_IMPLEMENTED", "此操作在后续 AI 阶段实现；当前仅提供规则型演示", 501)
        with Session.begin() as s:
            payload = body.model_dump()
            if (prev := replay(s, user, f"POST:{pid}:patches", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            if p.revision != body.baseRevision:
                problem("REVISION_CONFLICT", "目标地图已改变", 409)
            if body.targetNodeId not in {n["id"] for n in p.map_json["nodes"]}:
                problem("NOT_FOUND", "目标节点不存在", 404)
            phrase = {"questions": "还有哪些证据需要人工核验？", "challenge": "哪些反例可能推翻当前观点？",
                      "expand": "当前材料能否支持更细的论点？"}[body.operation]
            op = {"opId": uid(), "op": "add", "parentId": body.targetNodeId,
                  "node": {"type": "question", "title": phrase, "evidenceRefs": [], "verification": "unverified"}}
            apply_ops(p.map_json, [op], paragraphs_of(s, pid), ai_target=body.targetNodeId)
            d = Draft(id=uid(), project_id=pid, base_revision=p.revision, kind="patch",
                      payload={"targetNodeId": body.targetNodeId, "operation": body.operation,
                               "generationMode": "extractive_demo", "proposedOps": [op]})
            s.add(d)
            return record(s, user, f"POST:{pid}:patches", key, payload,
                          {"patchId": d.id, "status": "proposed", "generationMode": "extractive_demo"}, 202)

    @app.get("/api/v1/projects/{pid}/patches/{patch_id}")
    def read_patch(pid: str, patch_id: str, authorization: str | None = Header(None)):
        with Session() as s:
            get_project(s, pid, owner(authorization))
            d = s.scalar(select(Draft).where(Draft.id == patch_id, Draft.project_id == pid, Draft.kind == "patch"))
            if not d:
                problem("NOT_FOUND", "候选修改不存在", 404)
            return {"patchId": d.id, "baseRevision": d.base_revision, "status": d.status, **d.payload}

    @app.post("/api/v1/projects/{pid}/patches/{patch_id}/apply")
    def apply_patch(pid: str, patch_id: str, body: ApplyPayload, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            payload = body.model_dump() | {"revision": expected}
            if (prev := replay(s, user, f"POST:{pid}:patch:{patch_id}:apply", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            d = s.scalar(select(Draft).where(Draft.id == patch_id, Draft.project_id == pid, Draft.kind == "patch"))
            if not d:
                problem("NOT_FOUND", "候选修改不存在", 404)
            if d.status != "proposed" or d.base_revision != expected:
                problem("REVISION_CONFLICT", "Patch 已应用或基于旧版本", 409)
            proposed = d.payload["proposedOps"]
            selected = body.acceptedOpIds
            if not selected or len(set(selected)) != len(selected) or not set(selected).issubset({x["opId"] for x in proposed}):
                problem("SCHEMA_INVALID", "勾选的 Patch 操作无效", 422)
            operations = [op for op in proposed if op["opId"] in selected]
            before = deepcopy(p.map_json)
            after = apply_ops(before, operations, paragraphs_of(s, pid), ai_target=d.payload["targetNodeId"])
            result = commit_map(s, p, before, after, expected, user, "patch_demo")
            d.status = "accepted"
            return record(s, user, f"POST:{pid}:patch:{patch_id}:apply", key, payload, result)

    @app.post("/api/v1/projects/{pid}/undo")
    def undo(pid: str, authorization: str | None = Header(None), if_match: str | None = Header(None), idempotency_key: str | None = Header(None)):
        user, expected, key = owner(authorization), get_revision(if_match), require_key(idempotency_key)
        with Session.begin() as s:
            payload = {"revision": expected}
            if (prev := replay(s, user, f"POST:{pid}:undo", key, payload)) is not None:
                return prev
            p = get_project(s, pid, user)
            last = s.scalar(select(Change).where(Change.project_id == pid, Change.undone == False, Change.kind != "undo")
                            .order_by(Change.rev_after.desc()).limit(1))
            if not last or last.rev_after != expected or last.kind not in {"manual", "generation_demo", "patch_demo"}:
                # Source deletion is intentionally irreversible in this API.
                # Do not resurrect the map while its source paragraphs are gone.
                problem("NO_UNDO_AVAILABLE", "最新变更无法安全撤销", 409)
            result = commit_map(s, p, p.map_json, last.before_json, expected, user, "undo")
            last.undone = True
            return record(s, user, f"POST:{pid}:undo", key, payload, result)

    @app.get("/api/v1/projects/{pid}/export")
    def export(pid: str, format: str, authorization: str | None = Header(None)):
        user = owner(authorization)
        with Session() as s:
            p = get_project(s, pid, user)
            if format == "json":
                validate_tree(p.map_json)
                return {"projectId": p.id, "revision": p.revision, "map": p.map_json}
            if format == "md":
                sources = {x.id: x.title for x in s.scalars(select(Source).where(Source.project_id == pid))}
                return Response(content=markdown_export(p.map_json, sources), media_type="text/markdown; charset=utf-8",
                                headers={"Content-Disposition": 'attachment; filename="tracemap.md"'})
            problem("BAD_REQUEST", "导出格式仅支持 md 或 json", 400)

    return app


app = create_app()
