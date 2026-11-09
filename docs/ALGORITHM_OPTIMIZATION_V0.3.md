# TraceMap — 算法与证据安全优化设计 v0.3

> **状态：已实现的规则引擎优化 + 待验证的 LLM 方案。** 更新：2026-11-09。实现：[`apps/api/tracemap/core.py`](../apps/api/tracemap/core.py)；验证：[`test_hardening.py`](../apps/api/tests/test_hardening.py)。
>
> 不要把此版本的词面检索、引用精确定位和规则型 Patch 称为“LLM 已上线”“事实查证”“语义检索”或“真实模型质量达标”。

## 1. 问题与质量目标

TraceMap 的独特价值不在“多画节点”，而在**每个可核验的断言都可回到用户来源、每次模型建议都可预览、人工结论不会被静默改写**。因此需要区分：

| 检查层 | 技术含义 | 能否证明来源可信 |
|---|---|---|
| `anchorStatus=anchored` | `sourceId + paragraphId + [start,end)` 定位成功，原文 Unicode 切片与引用文本完全一致 | **不能** |
| `quoteSha256` | 当前引文文本的 SHA-256，拒绝不一致的客户端校验值 | **不能** |
| `verification=verified_by_user` | 用户明确主动核验该节点的判断；编辑/移动语义后撤回 | 只能说明用户做过核验，**不能替代外部事实查证** |
| `PatchProposal` | 尚未提交的候选操作 | 不代表自动执行、也不代表正确 |

**P0 红线**：同项目引用、无环单根树、最多 120 节点/5 层、AI 不写人工保护节点、校验失败零局部提交。指标建议继续按 [PRD](https://github.com/1998x-stack/projects/blob/main/projects/knowledge/llm-xmind/reports/prd-mvp-v1.0.md) 做真实数据验证。

## 2. 规范化、段落切分和可复现锚点

1. 先对文字做 `CRLF / CR → LF`、Unicode NFC。拒绝含孤立 surrogate 的无效 Unicode 字符串，避免在 UTF-8 编码/哈希处升级为 500 错误。
2. 分段基于空行；单段不超过 1200 Unicode **码点**。段落稳定 ID：`sha256(sourceId + '\0v1\0' + ordinal + '\0' + canonicalText)[:32]`。PDF 在保存时以**全文件连续 ordinal** 重键，避免跨页 ID 重复；附原始 `pageNo`。
3. 保存 `textSha256`，引用格式为 `{sourceId,paragraphId,start,end,exactQuote,quoteSha256,anchorStatus}`。
4. 输入引用由服务端强制校验 `start`/`end` 为非布尔整数、`0 ≤ start < end ≤ len(paragraph)`、引用文本必须为当前同项目原文切片；对于无对应段落、伪造哈希、越界或不一致者返回 `422 QUOTE_ANCHOR_INVALID`。
5. JS UTF-16 与 Python Unicode 码点不同。浏览器在高亮 Emoji/组合字符前仍须做码点→UTF-16 映射；算法通过并不替代前端定位测试。

**性质**：原始段落没有“近似匹配时自动补引文”的隐式回退。无法精确定位就不能显示成 anchored。

## 3. 资料排序：词面相关性 + 来源平衡

### v0.2 的不足

旧版只取每个来源的前 3 段；当研究目标与第 4 段之后的信息更相关时，该段必然被漏掉。这不是“模型幻觉”，但会误导用户以为资料已被充分覆盖。

### v0.3 已实现

```text
输入：goal + 已由 API 校验所属项目的 source_paragraphs
规范化：NFC、大小写归一
Token：中文字符双字片段；英文和数字词
rank(para) = (是否包含完整 goal, 与 goal 词项出现次数的截断重合)
同分排序：(段落 ordinal, paragraphId)
每个非空 source 最多提取 3 个候选，且至少保留一个
输出：每个来源独立主题节点 + 原文摘录主张节点 + 精确 anchored 引用
```

实现常量：`EXTRACTIVE_SELECTION_POLICY=lexical_v2_source_balanced`，并写入只读生成草稿的元数据。由于当前最多 5 个来源、每来源 3 个摘录，最大节点数为 1 + 5×(1+3) = **21**，低于结构上限 120。排序稳定是指**段落选择及顺序稳定**；每次草稿分配新 UUID，不声称完整 JSON 字节相同。

**复杂度**：若源数量为 S、每源 P 个段落，评分约 O(总文字量 + P×token 数)；每源排序 O(P log P)。首版上限 80,000 码点；不需要向量库、embedding 成本或无意义的全表向量搜索。

**限制**：字词重合不等于语义相似、蕴含或真假；中文同义词、否定句、跨文档冲突仍可能错排。单纯“引用可定位”绝不能被产品话术升级为“事实准确”。

## 4. 树操作与 Patch 的安全边界

入口 `apply_ops(tree, operations, project_paragraphs, ai_target?)` 在**纯函数的深拷贝**上逐条操作并在每一步校验，函数返回后才可交由数据库事务提交。

- 首先对整棵树进行严格 Schema 检查；`id/parentId/type/verification/sortOrder/evidenceRefs` 的恶意 JSON 类型不得触发 `TypeError`/`KeyError` 500。
- 每批最多 40 个操作；未知操作拒绝。`add` 只创建服务端规范化的 origin/verification，不能伪造人工核验状态；`attach_evidence` 必须由服务端重新验证引文。
- AI 修改仅允许 `ai_target` 子树。移动或删除一个 AI 节点时，**必须遍历其全部后代**，拒绝包含 `origin=user` 或 `verification=verified_by_user` 的保护节点。
- 用户主动 `rename` 导致主张文本变化或 `move` 使节点上下文变化时，其核验状态撤回为 `unverified`。未变更标题不会无故撤销。服务端 undo 能恢复上一个完整已提交快照。
- 修改提议为只读对象，`acceptedOpIds` 由用户显式提交；应用前再次校验所选操作与全局 revision，且数据库事务为 all-or-nothing。

**关键取舍**：即使模型输出结构符合 JSON Schema，也不代表其修改应被批准。所有授权、证据、保护节点、树结构约束不能由 prompt 替代。

## 5. 输出与保真度

Markdown 仍使用 `#`—`#####` 层级，按 `sortOrder/id` 进行确定性同级排序；来源索引置于正文后，引用正文控制换行与 HTML 特殊字符，阻止用户输入制造额外的 Markdown 标题或 HTML 标签。JSON 可导出当前正式地图和 revision。

**尚待验证**：Xmind Web/Windows/macOS 实际 Markdown 导入，特别是多级结构、特殊字符和证据附录；不能用 Markdown 单元测试替代端到端兼容性证明。

## 6. 可复现合成基准与风险说明

执行：

```bash
PYTHONPATH=apps/api python scripts/benchmark_domain.py
PYTHONPATH=apps/api pytest -q apps/api/tests
```

合成集固定 **5 来源 × 50 段**，每个来源的目标相关段落刻意放在 **第 43 段**；旧“前三段”基线将遗漏全部 5 个示例段，新策略在构造样本上检出 **5/5**。此数字是**合成选择验证**，不是文档准确率、召回率或真实用户收益。脚本打印 120 次本地测量的 median/p95，仅衡量规则引擎 + 树校验耗时，不包含 PDF、HTTP、数据库、网络、模型或渲染。

## 7. 后续 G3 真正 LLM 的进入条件

1. 建立至少包含中英混合、Emoji、来源相互矛盾、OCR 失败和提示注入的黄金集；由人工预标注事实、段落及目标引用。
2. 引入可替换 provider adapter + 令牌/成本/超时上限，生成只读候选结构；模型输出统一 Schema，最多一次受控修复。
3. 对比「原始按顺序」「词面平衡检索」「真正模型候选→树」的覆盖、引用正确率、冲突召回、延迟和成本；不能只比较生成速度。
4. 若 `quoteSha256`、sourceId 或精确锚点校验失败，自动降级未核验/拒绝写入，**不得虚构替代引文**。
5. 没有用户确认就没有正式地图更新。模型输出含来源文字的工具/系统指令均视作不可信内容。
