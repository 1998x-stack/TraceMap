"""Adversarial and retrieval regression tests for the G0/G2 development API."""
from copy import deepcopy

import pytest

from tracemap.core import (
    RuleError, apply_ops, extractive_draft, root_map, sha,
    split_paragraphs, uid, validate_tree, verify_ref,
)
from test_api import h


def test_malformed_tree_fields_are_domain_errors():
    original = root_map('subject')
    cases = [
        ('id', []), ('id', {'x': 1}), ('parentId', []),
        ('type', ['claim']), ('origin', {'ai': True}),
        ('verification', []), ('note', {'unsafe': True}),
        ('sortOrder', -1), ('evidenceRefs', [42]),
        ('evidenceRefs', [{'sourceId':'s','paragraphId':'p','exactQuote':'x','start':0,'end':1,'anchorStatus':[]}]),
    ]
    for field, malformed in cases:
        tree = deepcopy(original)
        tree['nodes'][0][field] = malformed
        with pytest.raises(RuleError):
            validate_tree(tree, {})


def test_malformed_references_and_operations_never_escape_as_500():
    source = 'source1'
    para = split_paragraphs('😀分析数据。', source)[0]
    good = dict(sourceId=source, paragraphId=para['id'], start=1, end=3, exactQuote='分析')
    for field, bad in [('sourceId', []), ('paragraphId', {}), ('exactQuote', ['分析']),
                       ('start', True), ('end', 9999), ('quoteSha256', 'bad')]:
        with pytest.raises(RuleError):
            verify_ref({**good, field: bad}, {(source, para['id']): para['text']})
    root = root_map('research')
    for op in [
        {'op':'add', 'parentId':[], 'node':{'title':'bad'}},
        {'op':'add', 'parentId':root['rootId'], 'node':['not-a-dict']},
        {'op':'add', 'parentId':root['rootId'], 'node':{'title':'x','evidenceRefs':{'bad':'type'}}},
        {'op':'move', 'nodeId':{'bad':'id'}, 'parentId':root['rootId']},
        {'op':'verify','nodeId':[], 'verified':True},
    ]:
        with pytest.raises(RuleError):
            apply_ops(root, [op], {})
        assert len(root['nodes']) == 1


def test_ai_cannot_move_ancestor_of_protected_human_descendant():
    tree = root_map('research')
    a, b, human = uid(), uid(), uid()
    tree['nodes'].extend([
        dict(id=a,parentId=tree['rootId'],type='topic',title='AI branch',origin='ai',verification='unverified',evidenceRefs=[],sortOrder=0),
        dict(id=b,parentId=tree['rootId'],type='topic',title='AI target',origin='ai',verification='unverified',evidenceRefs=[],sortOrder=1),
        dict(id=human,parentId=a,type='claim',title='Human insight',origin='user',verification='unverified',evidenceRefs=[],sortOrder=0),
    ])
    before = deepcopy(tree)
    with pytest.raises(RuleError, match='保护'):
        apply_ops(tree,[{'op':'move','nodeId':a,'parentId':b}],{},ai_target=tree['rootId'])
    assert tree==before


def test_source_balanced_goal_relevance_and_determinism():
    primary='source-a'
    secondary='source-b'
    raw=['免责声明。', '日常记录。', '产品定价策略包含免费层和订阅层。', '其他背景。']
    paras=[dict(id=f'p{i}', ordinal=i, text=t) for i,t in enumerate(raw)]
    other=[dict(id='q1',ordinal=0,text='这个产品的定价比较依赖订阅。')]
    sources={primary:paras,secondary:other}
    one=extractive_draft('产品定价策略',sources)
    two=extractive_draft('产品定价策略',sources)
    # IDs vary per execution, but selected exact quotations and order must remain stable.
    refs=lambda tree:[(r['sourceId'],r['paragraphId']) for n in tree['nodes'] for r in n.get('evidenceRefs',[])]
    assert refs(one)==refs(two)
    assert (primary,'p2') in refs(one)
    assert (secondary,'q1') in refs(one)
    assert len(one['nodes'])<=120


def test_malformed_api_request_returns_4xx_without_revision(client,headers,create_project):
    pid=create_project('hardening')['id']
    root=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['rootId']
    for i,op in enumerate([
        {'op':'add','parentId':[], 'node':{'title':'x'}},
        {'op':'add','parentId':root,'node':[1,2]},
        {'op':'add','parentId':root,'node':{'title':'x','evidenceRefs':[{'sourceId':[], 'paragraphId':'x'}]}},
    ]):
        response=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[op]},headers=h(headers,0,f'malformed-{i:03d}'))
        assert response.status_code in (400,422), response.text
        assert response.json()['error']['code']=='SCHEMA_INVALID' or response.json()['error']['code']=='QUOTE_ANCHOR_INVALID'
    assert client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['revision']==0


def test_deleted_source_has_immutable_audit_record(client, headers, create_project):
    pid=create_project('source audit')['id']
    source=client.post(f'/api/v1/projects/{pid}/sources/text',json={'title':'demo','text':'研究材料','format':'text'},headers=h(headers,0,'audit-source-00001'))
    assert source.status_code==202
    sid=source.json()['sourceId']
    deleted=client.delete(f'/api/v1/projects/{pid}/sources/{sid}',headers=h(headers,1,'audit-delete-00001'))
    assert deleted.status_code==200
    history=client.get(f'/api/v1/projects/{pid}/history',headers=headers)
    assert history.status_code==200
    types=[x['kind'] for x in history.json()['items']]
    assert 'source_add' in types and 'source_delete' in types
    # Deletion cannot be undone by restoring stale map anchors.
    undo=client.post(f'/api/v1/projects/{pid}/undo',headers=h(headers,2,'audit-undo-00001'))
    assert undo.status_code==409
    other=client.get(f'/api/v1/projects/{pid}/history',headers={'Authorization':'Bearer dev-bob'})
    assert other.status_code==404


def test_verified_claim_is_invalidated_on_manual_semantic_edits():
    source = 'src'
    para = split_paragraphs('研究结论。',source)[0]
    tree = root_map('study')
    root=tree['rootId']
    a,b=uid(),uid()
    anchor=verify_ref(dict(sourceId=source,paragraphId=para['id'],start=0,end=4,exactQuote='研究结论'),{(source,para['id']):para['text']})
    tree['nodes'].extend([
        dict(id=a,parentId=root,type='claim',title='研究结论',origin='user',verification='verified_by_user',evidenceRefs=[anchor],sortOrder=0),
        dict(id=b,parentId=root,type='topic',title='新的背景',origin='user',verification='unverified',evidenceRefs=[],sortOrder=1),
    ])
    paragraphs={(source,para['id']):para['text']}
    renamed=apply_ops(tree,[{'op':'rename','nodeId':a,'title':'相反的研究结论'}],paragraphs)
    assert renamed['nodes'][1]['verification']=='unverified'
    moved=apply_ops(tree,[{'op':'move','nodeId':a,'parentId':b}],paragraphs)
    assert moved['nodes'][1]['verification']=='unverified'
    assert tree['nodes'][1]['verification']=='verified_by_user'


def test_anchor_hash_and_export_do_not_inject_extra_headers():
    source='s'; para=split_paragraphs('😀证据',source)[0]
    evidence=verify_ref({'sourceId':source,'paragraphId':para['id'],
                         'start':1,'end':3,'exactQuote':'证据',
                         'quoteSha256':sha('证据')},{(source,para['id']):para['text']})
    assert evidence['quoteSha256']==sha('证据')
    from tracemap.core import markdown_export
    t=root_map('Main')
    t['nodes'].append(dict(id=uid(),parentId=t['rootId'],type='claim',title='<script>bad</script>',origin='user',verification='unverified',evidenceRefs=[evidence],sortOrder=0))
    md=markdown_export(t,{'s':'Sourced\n## injected'})
    assert '## injected' not in md
    assert '<script>' not in md
    assert '&lt;script&gt;' in md


def test_id_payload_with_invalid_id_is_not_silently_regenerated():
    t=root_map('Topic')
    for invalid in [[],{},None,0,'']:
        with pytest.raises(RuleError):
            apply_ops(t,[{'op':'add','parentId':t['rootId'],'node':{'id':invalid,'title':'Added'}}],{})


def test_source_upload_idempotency_stale_versions_and_audit_privacy(client, headers, create_project):
    pid=create_project('idem-audit')['id']
    endpoint=f'/api/v1/projects/{pid}/sources/text'
    data={'title':'user-supplied','text':'SENSITIVE_LITERAL_123','format':'text'}
    first=client.post(endpoint,json=data,headers=h(headers,0,'audit-once-12345'))
    assert first.status_code==202,first.text
    replay=client.post(endpoint,json=data,headers=h(headers,0,'audit-once-12345'))
    assert replay.status_code==202 and replay.json()==first.json()
    assert len(client.get(f'/api/v1/projects/{pid}/sources',headers=headers).json()['items'])==1
    conflict=client.post(endpoint,json={**data,'text':'changed'},headers=h(headers,0,'audit-once-12345'))
    assert conflict.status_code==409 and conflict.json()['error']['code']=='IDEMPOTENCY_KEY_REUSED'
    stale=client.post(endpoint,json=data,headers=h(headers,0,'audit-stale-12345'))
    assert stale.status_code==409 and stale.json()['error']['code']=='REVISION_CONFLICT'
    history=client.get(f'/api/v1/projects/{pid}/history',headers=headers)
    assert history.status_code==200
    assert len(history.json()['items'])==1
    assert 'SENSITIVE_LITERAL_123' not in history.text
    assert history.json()['items'][0]['kind']=='source_add'


def test_api_verified_claim_changes_invalidate_then_undo_restores(client,headers,create_project):
    pid=create_project('verification')['id']
    src=client.post(f'/api/v1/projects/{pid}/sources/text',json={'title':'c','text':'研究结论','format':'text'},headers=h(headers,0,'verify-source-123'))
    sid=src.json()['sourceId']
    para=client.get(f'/api/v1/projects/{pid}/sources/{sid}/paragraphs',headers=headers).json()['items'][0]
    root=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['rootId']
    added=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[{'op':'add','parentId':root,'node':{'type':'claim','title':'研究结论','evidenceRefs':[
        {'sourceId':sid,'paragraphId':para['id'],'start':0,'end':4,'exactQuote':'研究结论'}]}}]},headers=h(headers,1,'verify-add-123'))
    assert added.status_code==200,added.text
    claim=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'][-1]['id']
    verified=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[{'op':'verify','nodeId':claim,'verified':True}]},headers=h(headers,2,'verify-flag-123'))
    assert verified.status_code==200
    rename=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[{'op':'rename','nodeId':claim,'title':'另一种结论'}]},headers=h(headers,3,'verify-rename-123'))
    assert rename.status_code==200,rename.text
    changed=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()
    assert changed['nodes'][-1]['verification']=='unverified'
    undone=client.post(f'/api/v1/projects/{pid}/undo',headers=h(headers,4,'verify-undo-123'))
    assert undone.status_code==200
    restored=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()
    assert restored['nodes'][-1]['verification']=='verified_by_user'
    assert restored['nodes'][-1]['title']=='研究结论'
    assert client.get(f'/api/v1/projects/{pid}/history',headers=headers).json()['items'][0]['kind']=='undo'


def test_generation_metadata_and_source_balanced_selection_api(client,headers,create_project):
    pid=create_project('ranking')['id']
    text='无关的说明。\n\n另一个无关段落。\n\n产品定价策略是订阅制。\n\n通用信息。'
    src=client.post(f'/api/v1/projects/{pid}/sources/text',json={'title':'pricing','text':text,'format':'text'},headers=h(headers,0,'rank-source-12345'))
    sid=src.json()['sourceId']
    para=client.get(f'/api/v1/projects/{pid}/sources/{sid}/paragraphs',headers=headers).json()['items']
    refid=next(p['id'] for p in para if '定价策略' in p['text'])
    created=client.post(f'/api/v1/projects/{pid}/generate',json={'goal':'定价策略','sourceIds':[sid]},headers=h(headers,1,'rank-generate-123'))
    assert created.status_code==202,created.text
    assert created.json()['selectionPolicy']=='lexical_v2_source_balanced'
    draft=client.get(f'/api/v1/projects/{pid}/generation-drafts/{created.json()["draftId"]}',headers=headers).json()
    refs=[r for n in draft['map']['nodes'] for r in n.get('evidenceRefs',[])]
    assert refs[0]['paragraphId']==refid
    assert all(r['quoteSha256']==sha(r['exactQuote']) for r in refs)
    assert client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['revision']==1


def test_dev_api_fails_closed_for_non_development_environments_and_remote_clients(tmp_path,monkeypatch):
    from fastapi.testclient import TestClient
    from tracemap.main import create_app
    for env in ['production','staging','Development','prod']:
        monkeypatch.setenv('TRACEMAP_ENV',env)
        with pytest.raises(RuntimeError):
            create_app(f"sqlite:///{tmp_path / 'unused.db'}")
    monkeypatch.setenv('TRACEMAP_ENV','development')
    app=create_app(f"sqlite:///{tmp_path / 'local.db'}")
    with TestClient(app,client=('203.0.113.7',50001)) as remote:
        response=remote.get('/health')
        assert response.status_code==403
        assert response.json()['error']['code']=='DEV_LOCAL_ONLY'
    with TestClient(app) as local:
        assert local.get('/health').status_code==200
    app.state.engine.dispose()


def test_oversized_if_match_revision_is_rejected_without_500(client, headers, create_project):
    """GT-0006: a huge If-Match revision must be a 400, never a 500 OverflowError.

    Before the fix, int() parsed an unbounded integer and the CAS ``UPDATE ...
    WHERE revision = :expected`` raised ``OverflowError: Python int too large to
    convert to SQLite INTEGER``.
    """
    pid = create_project('revision bounds')['id']
    source = client.post(f'/api/v1/projects/{pid}/sources/text',
                         json={'title': 's', 'text': '研究材料', 'format': 'text'},
                         headers=h(headers, 0, 'bound-source-0001'))
    assert source.status_code == 202, source.text
    root = client.get(f'/api/v1/projects/{pid}/map', headers=headers).json()['rootId']
    ops = {'operations': [{'op': 'rename', 'nodeId': root, 'title': 'x'}]}
    huge = '"rev-999999999999999999999"'

    r = client.post(f'/api/v1/projects/{pid}/nodes/ops', json=ops,
                    headers={**headers, 'If-Match': huge, 'Idempotency-Key': 'bound-ops-1000'})
    assert r.status_code == 400 and r.json()['error']['code'] == 'BAD_REQUEST', r.text

    r = client.post(f'/api/v1/projects/{pid}/undo',
                    headers={**headers, 'If-Match': huge, 'Idempotency-Key': 'bound-undo-0001'})
    assert r.status_code == 400, r.text

    r = client.delete(f'/api/v1/projects/{pid}',
                      headers={**headers, 'If-Match': huge, 'Idempotency-Key': 'bound-del-0001'})
    assert r.status_code == 400, r.text

    # The largest accepted revision simply conflicts (409, no 500).
    r = client.post(f'/api/v1/projects/{pid}/nodes/ops', json=ops,
                    headers={**headers, 'If-Match': '"rev-9007199254740991"', 'Idempotency-Key': 'bound-ops-max1'})
    assert r.status_code == 409 and r.json()['error']['code'] == 'REVISION_CONFLICT', r.text

    # One beyond the accepted range is rejected as a bad request.
    r = client.post(f'/api/v1/projects/{pid}/nodes/ops', json=ops,
                    headers={**headers, 'If-Match': '"rev-9007199254740992"', 'Idempotency-Key': 'bound-ops-max2'})
    assert r.status_code == 400, r.text

    # Project and map are unchanged by all of the above.
    assert client.get(f'/api/v1/projects/{pid}', headers=headers).json()['revision'] == 1


def test_storage_error_status_mapping_is_pure_and_safe():
    """GT-0020: unexpected/storage errors map to a structured, non-leaking body."""
    import sqlalchemy
    from sqlalchemy.exc import OperationalError, SQLAlchemyError
    from tracemap.main import storage_error_status

    locked = OperationalError("SELECT 1", {}, Exception("database is locked"))
    status, code, message, retryable = storage_error_status(locked)
    assert (status, code, retryable) == (503, "STORAGE_BUSY", True)
    assert "locked" not in message.lower() and "select" not in message.lower()

    status, code, _message, retryable = storage_error_status(SQLAlchemyError("driver blew up"))
    assert (status, code, retryable) == (500, "STORAGE_ERROR", False)

    status, code, _message, retryable = storage_error_status(ValueError("secret detail"))
    assert (status, code, retryable) == (500, "INTERNAL_ERROR", False)


def test_locked_database_returns_structured_retryable_error(tmp_path, monkeypatch):
    import sqlite3
    from fastapi.testclient import TestClient
    from tracemap.main import create_app

    monkeypatch.setenv("TRACEMAP_SQLITE_TIMEOUT", "0")  # fail fast instead of waiting 20 s
    app = create_app(f"sqlite:///{tmp_path / 'locked.db'}")
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            headers = {"Authorization": "Bearer dev-alice"}
            pid = client.post("/api/v1/projects", json={"title": "lock", "goal": "g"},
                              headers={**headers, "Idempotency-Key": "lock-create-0001"}).json()["id"]
            root = client.get(f"/api/v1/projects/{pid}/map", headers=headers).json()["rootId"]

            lock = sqlite3.connect(tmp_path / "locked.db", timeout=0)
            lock.execute("BEGIN EXCLUSIVE")
            try:
                response = client.post(f"/api/v1/projects/{pid}/nodes/ops",
                    json={"operations": [{"op": "rename", "nodeId": root, "title": "x"}]},
                    headers={**headers, "If-Match": '"rev-0"', "Idempotency-Key": "lock-op-0001"})
                assert response.status_code == 503, response.text
                body = response.json()
                assert body["error"]["code"] == "STORAGE_BUSY"
                assert body["error"]["retryable"] is True
                assert "locked" not in response.text.lower()
                assert "sqlite" not in response.text.lower()
            finally:
                lock.rollback()
                lock.close()

            # The database must be usable again once the lock is released.
            ok = client.post(f"/api/v1/projects/{pid}/nodes/ops",
                json={"operations": [{"op": "rename", "nodeId": root, "title": "y"}]},
                headers={**headers, "If-Match": '"rev-0"', "Idempotency-Key": "lock-op-0002"})
            assert ok.status_code == 200, ok.text
    finally:
        app.state.engine.dispose()
