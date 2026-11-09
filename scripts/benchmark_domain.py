"""Reproducible synthetic *microbenchmark* for extraction, not model accuracy.

Run from repo root: PYTHONPATH=apps/api python scripts/benchmark_domain.py
The data is artificial, the clock is machine-dependent, and timing is not a
production latency SLO or a user-study result.
"""
from __future__ import annotations

import json
from pathlib import Path
import statistics
import sys
from time import perf_counter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps" / "api"))
from tracemap.core import extractive_draft, validate_tree, sha  # noqa: E402


def sample():
    sources: dict[str, list[dict]] = {}
    for i in range(5):
        paragraphs = []
        for k in range(50):
            text = (f"第{k}段普通背景材料，来源{i}。" if k != 42
                    else f"来源{i}产品定价策略包含订阅和免费层，需人工核验真实性。")
            paragraphs.append({"id": f"p{i:02d}-{k:02d}", "ordinal": k, "text": text})
        sources[f"src{i}"] = paragraphs
    return sources


def main():
    sources = sample()
    paragraphs = {(sid, p["id"]): p["text"] for sid, ps in sources.items() for p in ps}
    durations = []
    for _ in range(120):
        t0 = perf_counter()
        tree = extractive_draft("产品定价策略", sources)
        validate_tree(tree, paragraphs)
        durations.append(1000 * (perf_counter() - t0))
    selected = [(ref["sourceId"],ref["paragraphId"])
                for node in tree["nodes"] for ref in node["evidenceRefs"]]
    correct_by_source = sum((f"src{i}",f"p{i:02d}-42") in selected for i in range(5))
    assert correct_by_source == 5
    assert len(tree["nodes"]) <= 120
    assert all(n["verification"] == "unverified" for n in tree["nodes"])
    assert all(ref["quoteSha256"] == sha(ref["exactQuote"])
               for n in tree["nodes"] for ref in n["evidenceRefs"])
    values = sorted(durations)
    result = {
        "kind": "synthetic_lexical_microbenchmark_not_model_accuracy",
        "source_count": len(sources), "paragraph_count": sum(map(len,sources.values())),
        "iterations": len(durations), "selected_nodes": len(tree["nodes"]),
        "golden_relevant_paragraphs_found": correct_by_source,
        "golden_relevant_paragraphs_total": 5,
        "median_ms": round(statistics.median(durations), 3),
        "p95_ms": round(values[int(len(values)*.95)-1], 3),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
