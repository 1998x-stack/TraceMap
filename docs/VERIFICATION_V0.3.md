# TraceMap — 后端/算法优化测试与证据 v0.3

> 日期：2026-11-09。本文件只报告当前实际执行的检验；GitHub Actions 在最终提交之后的结果需以对应的 run 为准。

## 1. 测试方法：先复现再修复

新增 `apps/api/tests/test_hardening.py`。初次在旧实现下执行：6 项测试中**5 失败、1 通过**；失败点分别是畸形 Node ID、畸形 EvidenceRef、AI Move 包含人工后代、API 被恶意 JSON 触发 `TypeError` 500、历史审计路由不存在。随后修复纯领域规则与 API，并复测通过。

执行命令：

```bash
python -m pip install -e './apps/api[test]'
python -m compileall -q apps/api/tracemap
python -m pytest -q apps/api/tests
python scripts/benchmark_domain.py
```

## 2. 增量验收矩阵

| 场景 | 可复现测试 | 预期 |
|---|---|---|
| 节点 ID/类型/父 ID 为数组、字典、布尔值 | `test_malformed_tree_fields_are_domain_errors` | `422 SCHEMA_INVALID`，无 500 |
| 引用 ID、quote、offset、hash 异常 | `test_malformed_references_and_operations_never_escape_as_500` | 引文无效，拒绝伪 anchored |
| AI Move 子树含人工节点 | `test_ai_cannot_move_ancestor_of_protected_human_descendant` | `PATCH_PROTECTED_NODE`，原图无变更 |
| Patch 越界、环、节点深度、引用伪造 | 既有 `test_core.py`、`test_api.py` | 原子拒绝，不修改 revision |
| 多来源相关段落不在前三段 | `test_source_balanced_goal_relevance_and_determinism` | 选中相关段落，保留每个来源 |
| 历史记录与删除来源 | `test_deleted_source_has_immutable_audit_record` | `source_add`/`source_delete` 可审计，不误恢复来源 |
| 跨用户读取历史 | 同上 | 返回 404 |
| 幂等重放与过期 revision | `test_source_upload_idempotency_stale_versions_and_audit_privacy` | 恰一次创建，冲突 409，历史接口无原文 |
| 已核验主张重新命名/移动 | `test_verified_claim_is_invalidated_on_manual_semantic_edits` | 旧核验自动撤回 |
| API rename 后 undo | `test_api_verified_claim_changes_invalidate_then_undo_restores` | revision 前进，恢复原始核验状态 |
| Markdown 注入 | `test_anchor_hash_and_export_do_not_inject_extra_headers` | 来源或标题不能产生意外标题/HTML |
| 演示生成元数据 + 引文哈希 | `test_generation_metadata_and_source_balanced_selection_api` | 草稿只读、哈希正确、优先目标段落 |
| 非开发环境及远程客户端访问 | `test_dev_api_fails_closed_for_non_development_environments_and_remote_clients` | 非 development 启动失败、非 loopback 拒绝 403 |
| Chrome 桌面与手机研究闭环 | 既有 `apps/web/e2e/` | GitHub CI 真实浏览器执行（非本地 Python 单元测试） |

## 3. 合成词面检索微基准

运行 `python scripts/benchmark_domain.py`。固定 5 来源、每来源 50 段，研究目标相关原文在各来源第 43 段，执行 120 次规则生成及树校验。脚本对结构、引用哈希和抽取结果有自检。测量结果只代表**合成数据的本机 CPU 开销**；不是 LLM 质量评测、实际多文档召回率、HTTP p95、部署延迟或 Xmind 兼容验证。

## 4. 路由契约一致性检查

`python scripts/export_openapi.py --check` 将实际 FastAPI `/openapi.json` 的结构与 [`packages/contracts/openapi.generated.json`](../packages/contracts/openapi.generated.json) 比较；新加/删除路径后若忘记更新契约，CI 失败。当前共 **19 个实际路径模板**。这不意味着所有响应 DTO 已完整声明，不能与未来产品的设计 OpenAPI 混为一谈。

## 5. 尚未通过/不能覆盖的门槛

- 真实多用户正式认证、生产环境 IDOR 红队和完整 GDPR/隐私数据生命周期。
- PostgreSQL 双事务竞争、故障恢复、异步 Worker 重试与死信处理。
- PDF 解压炸弹与资源受限隔离容器测试。
- LLM provider、引用召回率、事实准确率、跨文档冲突发现、提示注入对抗黄金集。
- 真实 Xmind 导入矩阵、正式性能 SLO、真实用户实验。

请把上述列为开放事项，不要因为 SQLite 本地测试或浏览器 UI 测试绿色就标记 G1–G5 全部完成。
