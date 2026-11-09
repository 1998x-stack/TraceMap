"""Deterministic, side-effect-free TraceMap domain and evidence rules.

No model calls occur here. ``extractive_draft`` is a deliberately labelled,
lexical-only demonstration and MUST NOT be described as AI factual inference.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
import hashlib
import re
import unicodedata
import uuid

TYPES = {"topic", "claim", "evidence", "counterpoint", "question", "decision"}
ORIGINS = {"user", "ai"}
ANCHOR_STATES = {"anchored", "unverified", "invalid", "source_deleted"}
MAX_NODES = 120
MAX_DEPTH = 5
MAX_SOURCES = 5
MAX_TOTAL_CHARS = 80_000
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_QUOTE_CHARS = 1_200
MAX_REFS_PER_NODE = 20
EXTRACTIVE_SELECTION_POLICY = "lexical_v2_source_balanced"


class RuleError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def uid() -> str:
    return str(uuid.uuid4())


def _string(value, *, limit: int, field: str, blank: bool = False, code="SCHEMA_INVALID") -> str:
    if (not isinstance(value, str) or len(value) > limit or
            (not blank and not value.strip()) or
            any(0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise RuleError(code, f"{field} 格式无效")
    return value


def sha(text: str) -> str:
    _string(text, limit=MAX_FILE_BYTES, field="SHA 输入", blank=True)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(text: str) -> str:
    _string(text, limit=MAX_FILE_BYTES, field="正文", blank=True)
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def split_paragraphs(text: str, source_id: str, page_no: int | None = None) -> list[dict]:
    """Stable per-source paragraph IDs, retaining exact canonical quote offsets."""
    text = canon(text)
    _string(source_id, limit=128, field="Source ID")
    chunks = []
    for part in re.split(r"\n\s*\n", text):
        part = part.strip("\n")
        if not part.strip():
            continue
        for pos in range(0, len(part), MAX_QUOTE_CHARS):
            piece = part[pos:pos + MAX_QUOTE_CHARS]
            ordinal = len(chunks)
            identifier = sha(f"{source_id}\0v1\0{ordinal}\0{piece}")[:32]
            chunks.append({"id": identifier, "ordinal": ordinal, "pageNo": page_no,
                           "text": piece, "textSha256": sha(piece)})
    return chunks


def root_map(title: str) -> dict:
    _string(title, limit=1000, field="根节点标题")
    root = uid()
    return {"rootId": root, "nodes": [{"id": root, "parentId": None,
        "type": "topic", "title": title[:160], "note": "", "origin": "user",
        "verification": "unverified", "evidenceRefs": [], "sortOrder": 0}]}


def _check_ref_shape(ref: dict) -> None:
    if not isinstance(ref, dict):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用必须是结构化对象")
    _string(ref.get("sourceId"), limit=128, field="Source ID", code="QUOTE_ANCHOR_INVALID")
    _string(ref.get("paragraphId"), limit=128, field="Paragraph ID", code="QUOTE_ANCHOR_INVALID")
    _string(ref.get("exactQuote"), limit=MAX_QUOTE_CHARS, field="引用原文", code="QUOTE_ANCHOR_INVALID")
    start, end = ref.get("start"), ref.get("end")
    if (not isinstance(start, int) or isinstance(start, bool) or
            not isinstance(end, int) or isinstance(end, bool) or
            start < 0 or end <= start or end - start > MAX_QUOTE_CHARS):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用 Unicode 偏移无效")
    quote_sha = ref.get("quoteSha256")
    if quote_sha is not None and (not isinstance(quote_sha, str) or quote_sha != sha(ref["exactQuote"])):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引文哈希与原文不匹配")


def verify_ref(ref: dict, paragraphs: dict) -> dict:
    """Return only an exactly verified, same-project anchor; never trust client status."""
    _check_ref_shape(ref)
    para = paragraphs.get((ref["sourceId"], ref["paragraphId"]))
    if para is None or not isinstance(para, str):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用段落不存在或不属于当前项目")
    start, end = ref["start"], ref["end"]
    if end > len(para) or para[start:end] != ref["exactQuote"]:
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用文本与原文不一致")
    return {"sourceId": ref["sourceId"], "paragraphId": ref["paragraphId"],
            "start": start, "end": end, "exactQuote": ref["exactQuote"],
            "quoteSha256": sha(ref["exactQuote"]), "anchorStatus": "anchored"}


def validate_tree(tree: dict, paragraphs: dict | None = None) -> dict:
    """Reject malformed trees and dangling/provenance-spoofed anchored references."""
    if not isinstance(tree, dict) or not isinstance(tree.get("nodes"), list):
        raise RuleError("SCHEMA_INVALID", "地图数据格式错误")
    _string(tree.get("rootId"), limit=128, field="Root ID")
    nodes = tree["nodes"]
    if not nodes or len(nodes) > MAX_NODES:
        raise RuleError("SCHEMA_INVALID", "地图节点数必须在 1–120 之间")
    by_id: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict):
            raise RuleError("SCHEMA_INVALID", "节点必须是结构化对象")
        node_id = _string(n.get("id"), limit=128, field="Node ID")
        if node_id in by_id:
            raise RuleError("SCHEMA_INVALID", "节点 ID 重复")
        by_id[node_id] = n
    roots = [n for n in nodes if n.get("parentId") is None]
    if len(roots) != 1 or roots[0]["id"] != tree["rootId"]:
        raise RuleError("SCHEMA_INVALID", "必须为单根树")
    for n in nodes:
        if not isinstance(n.get("type"), str) or n["type"] not in TYPES:
            raise RuleError("SCHEMA_INVALID", "节点类型不受支持")
        if not isinstance(n.get("origin"), str) or n["origin"] not in ORIGINS:
            raise RuleError("SCHEMA_INVALID", "节点来源不受支持")
        if not isinstance(n.get("verification"), str) or n["verification"] not in {"unverified", "verified_by_user"}:
            raise RuleError("SCHEMA_INVALID", "核验状态无效")
        _string(n.get("title"), limit=160, field="节点标题")
        _string(n.get("note", ""), limit=8_000, field="节点备注", blank=True)
        parent = n.get("parentId")
        if parent is not None and (not isinstance(parent, str) or parent not in by_id):
            raise RuleError("SCHEMA_INVALID", "父节点不存在或无效")
        if not isinstance(n.get("sortOrder"), int) or isinstance(n["sortOrder"], bool) or n["sortOrder"] < 0:
            raise RuleError("SCHEMA_INVALID", "节点排序参数错误")
        refs = n.get("evidenceRefs")
        if not isinstance(refs, list) or len(refs) > MAX_REFS_PER_NODE:
            raise RuleError("SCHEMA_INVALID", "引用列表格式或数量无效")
        for ref in refs:
            _check_ref_shape(ref)
            anchor_status = ref.get("anchorStatus")
            if not isinstance(anchor_status, str) or anchor_status not in ANCHOR_STATES:
                raise RuleError("SCHEMA_INVALID", "无效的锚点状态")
            if ref["anchorStatus"] == "anchored" and paragraphs is not None:
                verify_ref(ref, paragraphs)
    for n in nodes:
        cur, seen, depth = n, set(), 0
        while cur is not None:
            if cur["id"] in seen:
                raise RuleError("SCHEMA_INVALID", "树存在循环")
            seen.add(cur["id"])
            depth += 1
            if depth > MAX_DEPTH:
                raise RuleError("SCHEMA_INVALID", "地图最大深度为 5")
            cur = by_id.get(cur["parentId"]) if cur.get("parentId") else None
        if tree["rootId"] not in seen:
            raise RuleError("SCHEMA_INVALID", "存在不连通节点")
    return tree


def descendants(nodes: list[dict], root_id: str) -> set[str]:
    result = {root_id}
    while True:
        found = {n["id"] for n in nodes if n.get("parentId") in result}
        union = result | found
        if union == result:
            return result
        result = union


def apply_ops(tree: dict, operations: list[dict], paragraphs: dict, *, ai_target: str | None = None) -> dict:
    """Apply an all-or-nothing ordered operation batch to a defensive copy."""
    validate_tree(tree, paragraphs)
    if not isinstance(operations, list) or not 1 <= len(operations) <= 40:
        raise RuleError("SCHEMA_INVALID", "一次操作必须包含 1–40 条命令")
    if ai_target is not None:
        _string(ai_target, limit=128, field="AI target ID")
        if ai_target not in {n["id"] for n in tree["nodes"]}:
            raise RuleError("SCHEMA_INVALID", "Patch 目标节点不存在")
    draft = deepcopy(tree)
    allowed = descendants(draft["nodes"], ai_target) if ai_target else set()
    for operation in operations:
        if not isinstance(operation, dict):
            raise RuleError("SCHEMA_INVALID", "操作必须是结构化对象")
        action = operation.get("op")
        if not isinstance(action, str) or action not in {"add", "rename", "move", "delete", "verify", "attach_evidence"}:
            raise RuleError("SCHEMA_INVALID", "未知操作类型")
        by_id = {n["id"]: n for n in draft["nodes"]}
        target_id = operation.get("nodeId")
        if action != "add":
            _string(target_id, limit=128, field="编辑节点 ID")
            if ai_target and target_id not in allowed:
                raise RuleError("PATCH_OUT_OF_SCOPE", "AI 修改超出了目标子树")
            node = by_id.get(target_id)
            if ai_target and node and (node["origin"] != "ai" or node["verification"] == "verified_by_user"):
                raise RuleError("PATCH_PROTECTED_NODE", "AI 不可修改人工或已核验节点")
        if action == "add":
            parent_id = _string(operation.get("parentId"), limit=128, field="父节点 ID")
            if parent_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "父节点不存在")
            if ai_target and parent_id not in allowed:
                raise RuleError("PATCH_OUT_OF_SCOPE", "AI 新增节点超出目标子树")
            payload = operation.get("node", {})
            if not isinstance(payload, dict):
                raise RuleError("SCHEMA_INVALID", "新节点必须是结构化对象")
            node_id = payload["id"] if "id" in payload else uid()
            _string(node_id, limit=128, field="新节点 ID")
            if node_id in by_id:
                raise RuleError("SCHEMA_INVALID", "节点 ID 重复")
            if ai_target and payload.get("verification", "unverified") != "unverified":
                raise RuleError("PATCH_PROTECTED_NODE", "AI 不能标记人工核验")
            raw_refs = payload.get("evidenceRefs", [])
            if not isinstance(raw_refs, list) or len(raw_refs) > MAX_REFS_PER_NODE:
                raise RuleError("SCHEMA_INVALID", "引用列表格式或数量无效")
            refs = [verify_ref(ref, paragraphs) for ref in raw_refs]
            item = {"id": node_id, "parentId": parent_id,
                    "title": _string(payload.get("title", ""), limit=160, field="节点标题"),
                    "note": _string(payload.get("note", ""), limit=8_000, field="节点备注", blank=True),
                    "type": payload.get("type", "question"),
                    "origin": "ai" if ai_target else "user", "verification": "unverified",
                    "evidenceRefs": refs,
                    "sortOrder": len([n for n in draft["nodes"] if n.get("parentId") == parent_id])}
            draft["nodes"].append(item)
            if ai_target:
                allowed.add(node_id)
        elif action == "rename":
            if target_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "编辑目标不存在")
            replacement = _string(operation.get("title"), limit=160, field="节点标题")
            changed = replacement != by_id[target_id]["title"]
            by_id[target_id]["title"] = replacement
            if not ai_target:
                by_id[target_id]["origin"] = "user"
                if changed:
                    # Verification refers to the original *claim*, not a new title.
                    by_id[target_id]["verification"] = "unverified"
        elif action == "move":
            node = by_id.get(target_id)
            new_parent = _string(operation.get("parentId"), limit=128, field="目标父节点 ID")
            if not node or target_id == draft["rootId"] or new_parent not in by_id:
                raise RuleError("SCHEMA_INVALID", "移动目标无效")
            subtree = descendants(draft["nodes"], target_id)
            if new_parent in subtree:
                raise RuleError("SCHEMA_INVALID", "禁止将节点移动到自身后代")
            if ai_target:
                if new_parent not in allowed:
                    raise RuleError("PATCH_OUT_OF_SCOPE", "AI 移动越界")
                if any(n["id"] in subtree and (n["origin"] != "ai" or n["verification"] == "verified_by_user") for n in draft["nodes"]):
                    raise RuleError("PATCH_PROTECTED_NODE", "AI 不可移动包含人工保护节点的子树")
            previous_parent = node["parentId"]
            node["parentId"] = new_parent
            node["sortOrder"] = len([n for n in draft["nodes"] if n.get("parentId") == new_parent])
            if not ai_target and previous_parent != new_parent:
                # Reparenting changes logical context, so conservative invalidation.
                for descendant in draft["nodes"]:
                    if descendant["id"] in subtree:
                        descendant["verification"] = "unverified"
        elif action == "delete":
            if target_id == draft["rootId"] or target_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "不能删除根节点或不存在的节点")
            subtree = descendants(draft["nodes"], target_id)
            if ai_target:
                if any(n["id"] in subtree and (n["id"] not in allowed or n["origin"] != "ai" or n["verification"] == "verified_by_user") for n in draft["nodes"]):
                    raise RuleError("PATCH_PROTECTED_NODE", "AI 不可删除保护节点")
            draft["nodes"] = [n for n in draft["nodes"] if n["id"] not in subtree]
            allowed.difference_update(subtree)
        elif action == "verify":
            if ai_target:
                raise RuleError("PATCH_PROTECTED_NODE", "AI 不可核验结论")
            node = by_id.get(target_id)
            if not node:
                raise RuleError("SCHEMA_INVALID", "核验目标不存在")
            requested = operation.get("verified")
            if not isinstance(requested, bool):
                raise RuleError("SCHEMA_INVALID", "核验参数必须为布尔值")
            if requested and not any(ref.get("anchorStatus") == "anchored" for ref in node["evidenceRefs"]):
                raise RuleError("QUOTE_ANCHOR_INVALID", "至少需要一个可定位的引用才能标记已核验")
            node["verification"] = "verified_by_user" if requested else "unverified"
        elif action == "attach_evidence":
            if ai_target:
                raise RuleError("PATCH_PROTECTED_NODE", "AI 暂不允许替换现有节点的引用")
            node = by_id.get(target_id)
            if not node:
                raise RuleError("SCHEMA_INVALID", "证据目标不存在")
            if len(node["evidenceRefs"]) >= MAX_REFS_PER_NODE:
                raise RuleError("SCHEMA_INVALID", "单节点最多 20 条引用")
            ref = verify_ref(operation.get("reference"), paragraphs)
            node["evidenceRefs"].append(ref)
            node["verification"] = "unverified"
        validate_tree(draft, paragraphs)
    return draft


def degrade_source(tree: dict, source_id: str) -> dict:
    result = deepcopy(tree)
    for n in result["nodes"]:
        touched = False
        for ref in n["evidenceRefs"]:
            if ref.get("sourceId") == source_id:
                ref["anchorStatus"] = "source_deleted"
                touched = True
        if touched:
            n["verification"] = "unverified"
    return result


def _terms(text: str) -> Counter[str]:
    """Cheap CJK-bigram and Latin-word coverage; not semantic search."""
    words = re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", canon(text).casefold())
    terms: Counter[str] = Counter()
    for word in words:
        if "\u3400" <= word[0] <= "\u9fff":
            if len(word) == 1:
                terms[word] += 1
            else:
                terms.update(word[i:i + 2] for i in range(len(word) - 1))
        elif len(word) >= 2:
            terms[word] += 1
    return terms


def _relevance(goal: str, paragraph: str, query: Counter[str]) -> tuple[int, int]:
    if not query:
        return (0, 0)
    doc = _terms(paragraph)
    overlap = sum(min(freq, doc.get(term, 0)) for term, freq in query.items())
    # A literal full-goal match is useful but not a substitute for truth checking.
    full_match = int(bool(goal.strip()) and goal.strip().casefold() in paragraph.casefold())
    return (full_match, overlap)


def extractive_draft(goal: str, source_paragraphs: dict[str, list[dict]]) -> dict:
    """Source-balanced lexical selection with exact, inspectable paragraph quotes.

    Deterministically chooses at most three relevant paragraphs per source,
    preserving at least one from every non-empty source. Node UUIDs are fresh;
    the selected source/paragraph pairs and ordering are stable.
    """
    tree = root_map(goal[:160])
    root = tree["rootId"]
    query = _terms(goal)
    for source_id, paragraphs in source_paragraphs.items():
        if not paragraphs:
            continue
        # The caller owns source scoping. Sorting is stable under identical input.
        scored = [(_relevance(goal, p["text"], query), p) for p in paragraphs]
        ranked = [p for _, p in sorted(scored, key=lambda item: (
            -item[0][0], -item[0][1], item[1]["ordinal"], item[1]["id"]
        ))]
        topic = uid()
        tree["nodes"].append({"id": topic, "parentId": root, "type": "topic",
            "title": f"来源 {source_id[:8]}（原文摘录）", "note": "", "origin": "ai",
            "verification": "unverified", "evidenceRefs": [], "sortOrder": len(tree["nodes"])})
        for para in ranked[:3]:
            quote = para["text"][:min(110, len(para["text"]))]
            if not quote:
                continue
            tree["nodes"].append({"id": uid(), "parentId": topic, "type": "claim",
                "title": quote[:160], "note": "词面检索的原文摘录，并非模型结论或真实性判断", "origin": "ai",
                "verification": "unverified", "evidenceRefs": [{"sourceId": source_id,
                "paragraphId": para["id"], "start": 0, "end": len(quote),
                "exactQuote": quote, "quoteSha256": sha(quote), "anchorStatus": "anchored"}],
                "sortOrder": len([n for n in tree["nodes"] if n.get("parentId") == topic])})
    return tree


def markdown_export(tree: dict, sources: dict[str, str]) -> str:
    validate_tree(tree)
    nodes = tree["nodes"]
    by_parent: dict[str | None, list] = {}
    for n in nodes:
        by_parent.setdefault(n["parentId"], []).append(n)
    for siblings in by_parent.values():
        siblings.sort(key=lambda n: (n["sortOrder"], n["id"]))
    lines = ["<!-- TraceMap: 引文与人工核验状态可能无法由 Xmind 导入保留 -->"]
    appendix = []

    def inline(text: str) -> str:
        # A node can be user-authored Markdown; do not let its newline create
        # an unintended extra map heading or appendix entry on export.
        safe = re.sub(r"\s+", " ", text)
        return (safe.replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace("#", "＃").replace("`", "＇"))

    def walk(node, depth):
        title = inline(node["title"])
        lines.append(f"{'#' * depth} {title}")
        for ref in node.get("evidenceRefs", []):
            label = f"{inline(sources.get(ref['sourceId'], '已删除来源'))} · {ref['paragraphId'][:10]} · {ref['anchorStatus']}"
            appendix.append(f"- {title}: {label} — {inline(ref['exactQuote'][:160])}")
        for child in by_parent.get(node["id"], []):
            walk(child, depth + 1)

    walk(next(n for n in nodes if n["id"] == tree["rootId"]), 1)
    if appendix:
        lines.extend(["", "---", "", "**证据索引（TraceMap 扩展信息）**", *appendix])
    return "\n".join(lines) + "\n"
