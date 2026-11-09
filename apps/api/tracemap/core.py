"""Pure domain rules: tree, references, patches, and deterministic evidence extraction.

The extractive demonstration logic in this module is NOT a language model.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import re
import unicodedata
import uuid

TYPES = {"topic", "claim", "evidence", "counterpoint", "question", "decision"}
ORIGINS = {"user", "ai"}
MAX_NODES = 120
MAX_DEPTH = 5
MAX_SOURCES = 5
MAX_TOTAL_CHARS = 80_000
MAX_FILE_BYTES = 10 * 1024 * 1024


class RuleError(Exception):
    def __init__(self, code: str, message: str, status: int = 422):
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


def uid() -> str:
    return str(uuid.uuid4())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canon(text: str) -> str:
    return unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))


def split_paragraphs(text: str, source_id: str, page_no: int | None = None):
    """Stable per-source paragraph IDs, without silently discarding source text."""
    text = canon(text)
    chunks = []
    for part in re.split(r"\n\s*\n", text):
        part = part.strip("\n")
        if not part.strip():
            continue
        for pos in range(0, len(part), 1200):
            piece = part[pos:pos + 1200]
            ordinal = len(chunks)
            identifier = sha(f"{source_id}\0v1\0{ordinal}\0{piece}")[:32]
            chunks.append({"id": identifier, "ordinal": ordinal, "pageNo": page_no,
                           "text": piece, "textSha256": sha(piece)})
    return chunks


def root_map(title: str):
    return {"rootId": (root := uid()), "nodes": [{"id": root, "parentId": None,
        "type": "topic", "title": title[:160], "note": "", "origin": "user",
        "verification": "unverified", "evidenceRefs": [], "sortOrder": 0}]}


def verify_ref(ref: dict, paragraphs: dict):
    if not isinstance(ref, dict):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用必须是结构化对象")
    para = paragraphs.get((ref.get("sourceId"), ref.get("paragraphId")))
    if not para:
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用段落不存在或不属于当前项目")
    start, end = ref.get("start"), ref.get("end")
    if not isinstance(start, int) or isinstance(start, bool) or not isinstance(end, int) or isinstance(end, bool) or start < 0 or end <= start or end > len(para):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用 Unicode 偏移无效")
    if para[start:end] != ref.get("exactQuote"):
        raise RuleError("QUOTE_ANCHOR_INVALID", "引用文本与原文不一致")
    return {"sourceId": ref["sourceId"], "paragraphId": ref["paragraphId"],
            "start": start, "end": end, "exactQuote": ref["exactQuote"], "anchorStatus": "anchored"}


def validate_tree(tree: dict, paragraphs: dict | None = None):
    if not isinstance(tree, dict) or not isinstance(tree.get("nodes"), list):
        raise RuleError("SCHEMA_INVALID", "地图数据格式错误")
    nodes = tree["nodes"]
    if not nodes or len(nodes) > MAX_NODES:
        raise RuleError("SCHEMA_INVALID", "地图节点数必须在 1–120 之间")
    by_id = {n.get("id"): n for n in nodes if isinstance(n, dict)}
    if len(by_id) != len(nodes) or None in by_id:
        raise RuleError("SCHEMA_INVALID", "节点 ID 重复或无效")
    roots = [n for n in nodes if n.get("parentId") is None]
    if len(roots) != 1 or roots[0].get("id") != tree.get("rootId"):
        raise RuleError("SCHEMA_INVALID", "必须为单根树")
    for n in nodes:
        if n.get("type") not in TYPES or n.get("origin") not in ORIGINS:
            raise RuleError("SCHEMA_INVALID", "节点类型或来源不受支持")
        if not isinstance(n.get("title"), str) or not (1 <= len(n["title"]) <= 160):
            raise RuleError("SCHEMA_INVALID", "节点标题需为 1–160 字符")
        if n.get("verification") not in {"unverified", "verified_by_user"}:
            raise RuleError("SCHEMA_INVALID", "核验状态无效")
        if n.get("parentId") is not None and n["parentId"] not in by_id:
            raise RuleError("SCHEMA_INVALID", "父节点不存在")
        if not isinstance(n.get("sortOrder"), int) or isinstance(n["sortOrder"], bool):
            raise RuleError("SCHEMA_INVALID", "节点排序参数错误")
        if not isinstance(n.get("evidenceRefs"), list):
            raise RuleError("SCHEMA_INVALID", "引用列表格式无效")
        for r in n["evidenceRefs"]:
            if not isinstance(r, dict):
                raise RuleError("SCHEMA_INVALID", "引用必须是结构化对象")
            if r.get("anchorStatus") == "anchored" and paragraphs is not None:
                verify_ref(r, paragraphs)
            elif r.get("anchorStatus") not in {"anchored", "unverified", "invalid", "source_deleted"}:
                raise RuleError("SCHEMA_INVALID", "无效的锚点状态")
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
        next_set = result | found
        if next_set == result:
            return result
        result = next_set


def apply_ops(tree: dict, operations: list[dict], paragraphs: dict, *, ai_target: str | None = None):
    if not isinstance(operations, list) or not 1 <= len(operations) <= 40:
        raise RuleError("SCHEMA_INVALID", "一次操作必须包含 1–40 条命令")
    draft = deepcopy(tree)
    original_nodes = draft["nodes"]
    allowed_original = descendants(original_nodes, ai_target) if ai_target else None
    if ai_target and ai_target not in {n["id"] for n in original_nodes}:
        raise RuleError("SCHEMA_INVALID", "Patch 目标节点不存在")
    allowed = set(allowed_original or [])
    for operation in operations:
        if not isinstance(operation, dict):
            raise RuleError("SCHEMA_INVALID", "操作必须是结构化对象")
        action = operation.get("op")
        by_id = {n["id"]: n for n in draft["nodes"]}
        target_id = operation.get("nodeId")
        if ai_target and action != "add":
            if target_id not in allowed:
                raise RuleError("PATCH_OUT_OF_SCOPE", "AI 修改超出了目标子树")
            node = by_id.get(target_id)
            if node and (node["origin"] != "ai" or node["verification"] == "verified_by_user"):
                raise RuleError("PATCH_PROTECTED_NODE", "AI 不可修改人工或已核验节点")
        if action == "add":
            parent_id = operation.get("parentId")
            if parent_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "父节点不存在")
            if ai_target and parent_id not in allowed:
                raise RuleError("PATCH_OUT_OF_SCOPE", "AI 新增节点超出目标子树")
            payload = operation.get("node") or {}
            node_id = payload.get("id") or uid()
            if node_id in by_id:
                raise RuleError("SCHEMA_INVALID", "节点 ID 重复")
            if ai_target and payload.get("verification", "unverified") != "unverified":
                raise RuleError("PATCH_PROTECTED_NODE", "AI 不能标记人工核验")
            refs = [verify_ref(r, paragraphs) for r in payload.get("evidenceRefs", [])]
            item = {"id": node_id, "parentId": parent_id, "title": payload.get("title", ""),
                    "note": payload.get("note", ""), "type": payload.get("type", "question"),
                    "origin": "ai" if ai_target else "user", "verification": "unverified",
                    "evidenceRefs": refs, "sortOrder": len([n for n in draft["nodes"] if n.get("parentId") == parent_id])}
            draft["nodes"].append(item)
            if ai_target:
                allowed.add(node_id)
        elif action == "rename":
            if target_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "编辑目标不存在")
            by_id[target_id]["title"] = operation.get("title", "")
            if not ai_target:
                by_id[target_id]["origin"] = "user"
        elif action == "move":
            node = by_id.get(target_id)
            new_parent = operation.get("parentId")
            if not node or target_id == draft["rootId"] or new_parent not in by_id:
                raise RuleError("SCHEMA_INVALID", "移动目标无效")
            if new_parent in descendants(draft["nodes"], target_id):
                raise RuleError("SCHEMA_INVALID", "禁止将节点移动到自身后代")
            if ai_target and new_parent not in allowed:
                raise RuleError("PATCH_OUT_OF_SCOPE", "AI 移动越界")
            node["parentId"] = new_parent
            node["sortOrder"] = len([n for n in draft["nodes"] if n.get("parentId") == new_parent])
        elif action == "delete":
            if target_id == draft["rootId"] or target_id not in by_id:
                raise RuleError("SCHEMA_INVALID", "不能删除根节点或不存在的节点")
            subtree = descendants(draft["nodes"], target_id)
            if ai_target:
                for n in draft["nodes"]:
                    if n["id"] in subtree and (n["id"] not in allowed or n["origin"] != "ai" or n["verification"] == "verified_by_user"):
                        raise RuleError("PATCH_PROTECTED_NODE", "AI 不可删除保护节点")
            draft["nodes"] = [n for n in draft["nodes"] if n["id"] not in subtree]
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
            ref = verify_ref(operation.get("reference") or {}, paragraphs)
            node["evidenceRefs"].append(ref)
            node["verification"] = "unverified"
        else:
            raise RuleError("SCHEMA_INVALID", f"未知操作类型：{action}")
        validate_tree(draft, paragraphs)
    return draft


def degrade_source(tree: dict, source_id: str) -> dict:
    copy = deepcopy(tree)
    for n in copy["nodes"]:
        touched = False
        for ref in n["evidenceRefs"]:
            if ref.get("sourceId") == source_id:
                ref["anchorStatus"] = "source_deleted"
                touched = True
        if touched:
            n["verification"] = "unverified"
    return copy


def extractive_draft(goal: str, source_paragraphs: dict[str, list[dict]]):
    """Deterministic demo, not an LLM or factual inference engine."""
    tree = root_map(goal[:160])
    root = tree["rootId"]
    for source_id, paragraphs in source_paragraphs.items():
        if not paragraphs:
            continue
        topic = uid()
        tree["nodes"].append({"id": topic, "parentId": root, "type": "topic",
          "title": f"来源 {source_id[:8]}（原文摘录）", "note": "", "origin": "ai",
          "verification": "unverified", "evidenceRefs": [], "sortOrder": len(tree["nodes"])})
        for para in paragraphs[:3]:
            quote = para["text"][:min(110, len(para["text"]))]
            tree["nodes"].append({"id": uid(), "parentId": topic, "type": "claim",
             "title": quote[:160], "note": "原文片段，不代表模型推断的结论", "origin": "ai",
             "verification": "unverified", "evidenceRefs": [{"sourceId": source_id,
             "paragraphId": para["id"], "start": 0, "end": len(quote),
             "exactQuote": quote, "anchorStatus": "anchored"}], "sortOrder": para["ordinal"]})
    return tree


def markdown_export(tree: dict, sources: dict[str, str]):
    validate_tree(tree)
    nodes = tree["nodes"]
    by_parent: dict[str | None, list] = {}
    for n in nodes:
        by_parent.setdefault(n["parentId"], []).append(n)
    for siblings in by_parent.values():
        siblings.sort(key=lambda n: (n["sortOrder"], n["id"]))
    lines = ["<!-- TraceMap: 引文与人工核验状态可能无法由 Xmind 导入保留 -->"]
    appendix = []
    def walk(node, depth):
        title = node["title"].replace("\n", " ").replace("\r", " ").replace("#", "＃")
        lines.append(f"{'#' * depth} {title}")
        for r in node.get("evidenceRefs", []):
            label = f"{sources.get(r['sourceId'], '已删除来源')} · {r['paragraphId'][:10]} · {r['anchorStatus']}"
            appendix.append(f"- {title}: {label} — {r['exactQuote'][:160]}")
        for child in by_parent.get(node["id"], []):
            walk(child, depth + 1)
    walk(next(n for n in nodes if n["id"] == tree["rootId"]), 1)
    if appendix:
        lines.extend(["", "---", "", "**证据索引（TraceMap 扩展信息）**", *appendix])
    return "\n".join(lines) + "\n"
