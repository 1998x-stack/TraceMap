from copy import deepcopy
import pytest
from tracemap.core import (canon, split_paragraphs, root_map, verify_ref, validate_tree,
                           apply_ops, purge_source, markdown_export, RuleError, uid)


def test_normalization_and_unicode_codepoints():
    assert canon('Cafe\u0301\r\n😀') == 'Café\n😀'
    src = 'source-A'
    paras1 = split_paragraphs('😀这是引用\r\n\r\n另一个段落', src)
    paras2 = split_paragraphs('😀这是引用\n\n另一个段落', src)
    assert paras1 == paras2
    para = paras1[0]
    ref = {"sourceId": src, "paragraphId": para['id'], "start": 1, "end": 3, "exactQuote": "这是"}
    assert verify_ref(ref, {(src, para['id']): para['text']})['anchorStatus'] == 'anchored'
    with pytest.raises(RuleError, match='不一致'):
        verify_ref({**ref, 'exactQuote': '别的'}, {(src, para['id']): para['text']})


def test_tree_no_cycles_and_depth_limit():
    tree = root_map('research')
    validate_tree(tree)
    previous = tree['rootId']
    for depth in range(4):
        n = {"id": uid(), "parentId": previous, "type": "topic", "title": str(depth),
             "origin": "user", "verification": "unverified", "evidenceRefs": [], "sortOrder": 0}
        tree['nodes'].append(n)
        previous = n['id']
    validate_tree(tree)
    tree['nodes'].append({"id": uid(), "parentId": previous, "type": "topic", "title": "too deep",
                           "origin": "user", "verification": "unverified", "evidenceRefs": [], "sortOrder": 0})
    with pytest.raises(RuleError, match='最大深度'):
        validate_tree(tree)
    tree['nodes'][-1]['parentId'] = tree['nodes'][-1]['id']
    with pytest.raises(RuleError):
        validate_tree(tree)


def test_apply_ops_atomic_protected_ai_scope_and_move_cycle():
    tree = root_map('test')
    a_id, b_id = uid(), uid()
    tree['nodes'] += [
        {"id": a_id, "parentId": tree['rootId'], "type": "claim", "title": "Human",
         "origin": "user", "verification": "unverified", "evidenceRefs": [], "sortOrder": 0},
        {"id": b_id, "parentId": a_id, "type": "question", "title": "AI",
         "origin": "ai", "verification": "unverified", "evidenceRefs": [], "sortOrder": 0},
    ]
    original = deepcopy(tree)
    with pytest.raises(RuleError, match='人工'):
        apply_ops(tree, [{"op": "rename", "nodeId": a_id, "title": "modified"}], {}, ai_target=a_id)
    with pytest.raises(RuleError, match='后代'):
        apply_ops(tree, [{"op": "move", "nodeId": a_id, "parentId": b_id}], {})
    with pytest.raises(RuleError, match='目标子树'):
        apply_ops(tree, [{"op": "add", "parentId": tree['rootId'], "node": {"title": "escape"}}], {}, ai_target=a_id)
    with pytest.raises(RuleError):
        apply_ops(tree, [{"op": "rename", "nodeId": b_id, "title": "Valid"},
                         {"op": "delete", "nodeId": tree['rootId']}], {})
    assert tree == original
    valid = apply_ops(tree, [{"op": "rename", "nodeId": b_id, "title": "Updated"}], {}, ai_target=a_id)
    assert valid['nodes'][-1]['title'] == 'Updated'
    assert tree == original


def test_purge_deleted_source_removes_evidence_subtree_and_export():
    tree = root_map('😀 Research')
    a_id, child_id, independent_id = uid(), uid(), uid()
    a = {"id": a_id, "parentId": tree['rootId'], "title": "Claim", "type": "claim", "origin": "ai",
         "verification": "verified_by_user", "sortOrder": 0, "evidenceRefs": [{
             "sourceId": "S", "paragraphId": "P", "start": 0, "end": 2,
             "exactQuote": "你好", "anchorStatus": "anchored"}]}
    child = {"id": child_id, "parentId": a_id, "title": "Derived child", "type": "question", "origin": "ai",
             "verification": "unverified", "sortOrder": 0, "evidenceRefs": []}
    independent = {"id": independent_id, "parentId": tree['rootId'], "title": "Independent", "type": "question",
                   "origin": "user", "verification": "unverified", "sortOrder": 1, "evidenceRefs": []}
    tree['nodes'].extend([a, child, independent])
    after = purge_source(tree, 'S')
    assert [node['id'] for node in after['nodes']] == [tree['rootId'], independent_id]
    assert tree['nodes'][1]['verification'] == 'verified_by_user'
    md = markdown_export(after, {})
    assert '# 😀 Research' in md and 'Independent' in md
    assert 'Claim' not in md and '你好' not in md and 'Derived child' not in md
