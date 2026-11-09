"""Tests for the optional LLM provider adapter (no network, no real key)."""
import json
import urllib.error

import pytest

from tracemap import llm
from tracemap.core import split_paragraphs
from test_api import h


def _fixture():
    source = "source-1"
    paragraphs = split_paragraphs("产品定价采用订阅制。\n\n免费层用于获客。", source)
    index = {(source, p["id"]): p["text"] for p in paragraphs}
    return source, paragraphs, index


def test_build_tree_keeps_valid_refs_and_drops_hallucinated():
    source, paragraphs, index = _fixture()
    proposed = [
        {"type": "claim", "title": "订阅制定价", "sourceId": source,
         "paragraphId": paragraphs[0]["id"], "exactQuote": "产品定价采用订阅制。"},
        {"type": "claim", "title": "幻觉引用", "sourceId": source,
         "paragraphId": "does-not-exist", "exactQuote": "不存在"},
        {"type": "claim", "title": "跨项目引用", "sourceId": "other-project",
         "paragraphId": paragraphs[0]["id"], "exactQuote": "产品定价采用订阅制。"},
        {"title": "无引用节点"},
        {"type": "topic", "title": "类型被规范化"},
    ]
    tree, dropped = llm.build_tree("定价", proposed, index, {source: "访谈"})

    refs = [r for n in tree["nodes"] for r in n["evidenceRefs"]]
    assert len(refs) == 1
    assert refs[0]["anchorStatus"] == "anchored"
    assert refs[0]["exactQuote"] == "产品定价采用订阅制。"
    assert dropped == 4  # malformed/cross-source/unanchored candidates are discarded
    titles = [node["title"] for node in tree["nodes"]]
    assert "幻觉引用" not in titles
    assert "跨项目引用" not in titles
    assert "无引用节点" not in titles
    assert "类型被规范化" not in titles
    assert "订阅制定价" in titles
    assert all(n["verification"] == "unverified" for n in tree["nodes"])
    # only model-proposed nodes are AI; the single root keeps origin "user"
    assert all(n["origin"] == "ai" for n in tree["nodes"] if n["parentId"] is not None)
    assert any(n["type"] == "topic" for n in tree["nodes"])  # selected source group

def test_build_tree_excludes_valid_anchor_from_unselected_source():
    source, paragraphs, index = _fixture()
    outsider = "unselected-source"
    outsider_paragraph = split_paragraphs("这份资料没有被选择。", outsider)[0]
    index[(outsider, outsider_paragraph["id"])] = outsider_paragraph["text"]
    proposed = [
        {"type": "claim", "title": "范围外的主张", "sourceId": outsider,
         "paragraphId": outsider_paragraph["id"], "exactQuote": outsider_paragraph["text"]},
        {"type": "claim", "title": "选中来源", "sourceId": source,
         "paragraphId": paragraphs[0]["id"], "exactQuote": paragraphs[0]["text"]},
    ]
    tree, dropped = llm.build_tree("来源范围", proposed, index, {source: "访谈"})
    assert dropped == 1
    assert {n["title"] for n in tree["nodes"]}.isdisjoint({"范围外的主张"})
    assert any(n["title"] == "选中来源" for n in tree["nodes"])
    assert len([n for n in tree["nodes"] if n["evidenceRefs"]]) == 1

def test_all_ungrounded_model_candidates_fail_closed(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "test-key")
    documents = [{"sourceId": source, "title": "访谈", "paragraphs": [
        {"id": p["id"], "text": p["text"]} for p in paragraphs]}]
    canned = json.dumps({"nodes": [
        {"title": "想象出来的结论", "sourceId": source,
         "paragraphId": "none", "exactQuote": "invented"}]})
    with pytest.raises(llm.LLMError) as exc:
        llm.draft_from_llm("证据核验", documents, index, {source: "访谈"},
                           chat=lambda *_: (canned, {}))
    assert exc.value.code == "LLM_INVALID_OUTPUT"


def test_draft_from_llm_injects_transport_and_labels(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "test-key")
    canned = json.dumps({"nodes": [
        {"type": "claim", "title": "候选", "sourceId": source,
         "paragraphId": paragraphs[0]["id"], "exactQuote": paragraphs[0]["text"]},
    ]})

    def fake_chat(messages, config):
        assert messages[0]["role"] == "system"
        assert llm.UNTRUSTED_OPEN in messages[1]["content"]  # documents are data
        assert "Authorization" not in json.dumps(messages)
        return canned, {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    documents = [{"sourceId": source, "title": "访谈",
                  "paragraphs": [{"id": p["id"], "ordinal": p["ordinal"], "text": p["text"]} for p in paragraphs]}]
    out = llm.draft_from_llm("目标", documents, index, {source: "访谈"}, chat=fake_chat)

    assert len(out["tree"]["nodes"]) >= 2
    assert out["usage"]["total_tokens"] == 15
    assert out["provider"]["api"] == "openai-completions"
    blob = json.dumps(out, ensure_ascii=False, default=str)
    assert "test-key" not in blob and "api_key" not in blob.lower()


def test_draft_from_llm_requires_a_key(monkeypatch):
    monkeypatch.delenv("TRACEMAP_LLM_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY_FILE", "/nonexistent/key-file")
    source, paragraphs, index = _fixture()
    with pytest.raises(llm.LLMError) as exc:
        llm.draft_from_llm("g", [], index, {})
    assert exc.value.code == "LLM_NOT_CONFIGURED" and exc.value.status == 503


def test_extract_json_object_tolerates_fences_and_prose():
    assert llm.extract_json_object('```json\n{"nodes": []}\n```') == {"nodes": []}
    assert llm.extract_json_object('here you go: {"a": 1} thanks') == {"a": 1}
    with pytest.raises(llm.LLMError) as exc:
        llm.extract_json_object("no json at all")
    assert exc.value.code == "LLM_INVALID_OUTPUT"


def test_chat_maps_upstream_and_network_failures(monkeypatch):
    config = {"base_url": "http://127.0.0.1:1", "model": "m", "timeout": 1,
              "max_tokens": 16, "api_key": "secret-key"}
    messages = [{"role": "user", "content": "hi"}]

    def http_error(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 500, "boom", {}, None)

    monkeypatch.setattr(llm.urllib.request, "urlopen", http_error)
    with pytest.raises(llm.LLMError) as exc:
        llm._chat(messages, config)
    assert (exc.value.code, exc.value.status) == ("LLM_UPSTREAM_ERROR", 502)
    assert "secret-key" not in exc.value.message

    def net_error(request, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(llm.urllib.request, "urlopen", net_error)
    with pytest.raises(llm.LLMError) as exc2:
        llm._chat(messages, config)
    assert (exc2.value.code, exc2.value.status) == ("LLM_UNAVAILABLE", 503)


def test_generate_endpoint_uses_llm_when_enabled(client, headers, create_project, monkeypatch):
    pid = create_project("llm test")["id"]
    source = client.post(f"/api/v1/projects/{pid}/sources/text",
                         json={"title": "访谈", "text": "产品定价采用订阅制。\n\n免费层用于获客。", "format": "text"},
                         headers=h(headers, 0, "llm-source-0001"))
    sid = source.json()["sourceId"]
    paragraph = client.get(f"/api/v1/projects/{pid}/sources/{sid}/paragraphs", headers=headers).json()["items"][0]

    monkeypatch.setenv("TRACEMAP_GENERATION_MODE", "llm")
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "test-key")
    canned = json.dumps({"nodes": [{"type": "claim", "title": "模型候选", "sourceId": sid,
                                    "paragraphId": paragraph["id"], "exactQuote": paragraph["text"]}]})
    monkeypatch.setattr(llm, "_chat", lambda messages, config: (canned, {"total_tokens": 7}))

    response = client.post(f"/api/v1/projects/{pid}/generate",
                           json={"goal": "定价研究", "sourceIds": [sid]},
                           headers=h(headers, 1, "llm-generate-0001"))
    assert response.status_code == 202, response.text
    assert response.json()["generationMode"] == "llm"
    assert response.json()["provider"]["model"]

    # the model must never modify the live map
    assert client.get(f"/api/v1/projects/{pid}/map", headers=headers).json()["revision"] == 1
    draft = client.get(f"/api/v1/projects/{pid}/generation-drafts/{response.json()['draftId']}",
                       headers=headers).json()
    assert draft["generationMode"] == "llm"
    assert all(n["verification"] == "unverified" for n in draft["map"]["nodes"])
    assert all(n["origin"] == "ai" for n in draft["map"]["nodes"] if n["parentId"] is not None)


def test_health_reports_generation_provider(client, monkeypatch):
    monkeypatch.setenv("TRACEMAP_GENERATION_MODE", "llm")
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "k")
    body = client.get("/health").json()
    assert body["generationProvider"] == "llm" and body["llmConfigured"] is True
    monkeypatch.setenv("TRACEMAP_GENERATION_MODE", "extractive")
    monkeypatch.delenv("TRACEMAP_LLM_API_KEY", raising=False)
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY_FILE", "/nonexistent/key")
    body = client.get("/health").json()
    assert body["generationProvider"] == "extractive_demo" and body["llmConfigured"] is False


class _FakeResponse:
    def __init__(self, body: bytes): self._body = body
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self): return self._body


def test_chat_detects_truncated_output(monkeypatch):
    body = json.dumps({"choices": [{"message": {"content": '{"nodes": ['}, "finish_reason": "length"}],
                       "usage": {}}).encode()
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout=None: _FakeResponse(body))
    config = {"base_url": "http://127.0.0.1:1", "model": "m", "timeout": 1, "max_tokens": 16, "api_key": "k"}
    with pytest.raises(llm.LLMError) as exc:
        llm._chat([{"role": "user", "content": "x"}], config)
    assert (exc.value.code, exc.value.status) == ("LLM_OUTPUT_TRUNCATED", 502)


def test_draft_from_llm_retries_truncation(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "k")
    canned = json.dumps({"nodes": [{"type": "claim", "title": "重试成功", "sourceId": source,
                                    "paragraphId": paragraphs[0]["id"], "exactQuote": paragraphs[0]["text"]}]})
    calls = {"n": 0}

    def flaky(messages, config):
        calls["n"] += 1
        if calls["n"] == 1:
            raise llm.LLMError("LLM_OUTPUT_TRUNCATED", "truncated", 502)
        return canned, {"total_tokens": 3}

    documents = [{"sourceId": source, "title": "访谈",
                  "paragraphs": [{"id": p["id"], "ordinal": p["ordinal"], "text": p["text"]} for p in paragraphs]}]
    out = llm.draft_from_llm("目标", documents, index, {source: "访谈"}, chat=flaky)
    assert calls["n"] == 2
    assert len(out["tree"]["nodes"]) >= 2

def test_draft_from_llm_escalates_token_budget_after_truncation(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "k")
    monkeypatch.setenv("TRACEMAP_LLM_MAX_TOKENS", "4096")
    monkeypatch.setenv("TRACEMAP_LLM_RETRY_MAX_TOKENS", "12000")
    canned = json.dumps({"nodes": [{"type": "claim", "title": "预算提升后成功", "sourceId": source,
                                    "paragraphId": paragraphs[0]["id"], "exactQuote": paragraphs[0]["text"]}]})
    budgets = []

    def flaky(messages, config):
        budgets.append(config["max_tokens"])
        if len(budgets) == 1:
            raise llm.LLMError("LLM_OUTPUT_TRUNCATED", "truncated", 502)
        return canned, {"total_tokens": 5}

    documents = [{"sourceId": source, "title": "访谈",
                  "paragraphs": [{"id": p["id"], "ordinal": p["ordinal"], "text": p["text"]} for p in paragraphs]}]
    result = llm.draft_from_llm("目标", documents, index, {source: "访谈"}, chat=flaky)
    assert budgets == [4096, 8192]
    assert result["usage"]["total_tokens"] == 5


def test_draft_from_llm_caps_escalated_budget_and_returns_actionable_error(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "k")
    monkeypatch.setenv("TRACEMAP_LLM_MAX_TOKENS", "10000")
    monkeypatch.setenv("TRACEMAP_LLM_RETRY_MAX_TOKENS", "12000")
    budgets = []

    def always_truncated(messages, config):
        budgets.append(config["max_tokens"])
        raise llm.LLMError("LLM_OUTPUT_TRUNCATED", "truncated", 502)

    documents = [{"sourceId": source, "title": "访谈",
                  "paragraphs": [{"id": p["id"], "ordinal": p["ordinal"], "text": p["text"]} for p in paragraphs]}]
    with pytest.raises(llm.LLMError) as exc:
        llm.draft_from_llm("目标", documents, index, {source: "访谈"}, chat=always_truncated)
    assert budgets == [10000, 12000]
    assert exc.value.code == "LLM_OUTPUT_TRUNCATED"
    assert "12000 tokens" in exc.value.message
    assert "TRACEMAP_LLM_RETRY_MAX_TOKENS" in exc.value.message


def test_draft_from_llm_does_not_repeat_same_truncation_budget(monkeypatch):
    source, paragraphs, index = _fixture()
    monkeypatch.setenv("TRACEMAP_LLM_API_KEY", "k")
    monkeypatch.setenv("TRACEMAP_LLM_MAX_TOKENS", "8192")
    monkeypatch.setenv("TRACEMAP_LLM_RETRY_MAX_TOKENS", "8192")
    budgets = []

    def always_truncated(messages, config):
        budgets.append(config["max_tokens"])
        raise llm.LLMError("LLM_OUTPUT_TRUNCATED", "truncated", 502)

    documents = [{"sourceId": source, "title": "访谈",
                  "paragraphs": [{"id": p["id"], "ordinal": p["ordinal"], "text": p["text"]} for p in paragraphs]}]
    with pytest.raises(llm.LLMError) as exc:
        llm.draft_from_llm("目标", documents, index, {source: "访谈"}, chat=always_truncated)
    assert budgets == [8192]
    assert exc.value.code == "LLM_OUTPUT_TRUNCATED"
    assert "8192 tokens" in exc.value.message
