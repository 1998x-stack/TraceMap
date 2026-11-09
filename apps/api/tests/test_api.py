import uuid


def h(headers, revision=None, key=None):
    d = dict(headers)
    if revision is not None:
        d['If-Match'] = f'"rev-{revision}"'
    if key:
        d['Idempotency-Key'] = key
    return d


def post_text(client, headers, pid, revision, text='😀结论需要核验。\n\n第二段资料。', key='source-00001'):
    r = client.post(f'/api/v1/projects/{pid}/sources/text',
                    json={'title':'资料 A','text':text,'format':'text'},headers=h(headers,revision,key))
    return r


def test_auth_and_project_isolation(client, headers, create_project):
    unauth = client.get('/api/v1/projects')
    assert unauth.status_code == 401
    p = create_project()
    assert p['revision'] == 0
    other = client.get(f"/api/v1/projects/{p['id']}", headers={'Authorization':'Bearer dev-bob'})
    assert other.status_code == 404
    listing = client.get('/api/v1/projects',headers=headers).json()
    assert len(listing['items']) == 1
    assert listing['items'][0]['id'] == p['id']


def test_source_quotes_verified_revision_idempotency_and_delete(client,headers,create_project):
    pid = create_project()['id']
    r = post_text(client, headers, pid,0)
    assert r.status_code == 202, r.text
    assert r.json()['revision'] == 1
    sid = r.json()['sourceId']
    assert client.get(f"/api/v1/projects/{pid}/sources/{sid}/paragraphs",headers=headers).status_code == 200
    p = client.get(f"/api/v1/projects/{pid}/sources/{sid}/paragraphs",headers=headers).json()['items'][0]
    assert p['text'].startswith('😀结论')
    root = client.get(f"/api/v1/projects/{pid}/map",headers=headers).json()['rootId']
    op = {'operations':[{'op':'add','parentId':root,'node':{
       'type':'claim','title':'证据核验','evidenceRefs':[{'sourceId':sid,'paragraphId':p['id'],
                            'start':1,'end':3,'exactQuote':'结论'}]}}]}
    r = client.post(f"/api/v1/projects/{pid}/nodes/ops",json=op,headers=h(headers,1,'add-node-123'))
    assert r.status_code == 200, r.text
    assert r.json()['revision'] == 2
    rerequest = client.post(f"/api/v1/projects/{pid}/nodes/ops",json=op,headers=h(headers,1,'add-node-123'))
    assert rerequest.status_code == 200 and rerequest.json()==r.json()
    wrong = client.post(f"/api/v1/projects/{pid}/nodes/ops",json={'operations':[]},headers=h(headers,1,'add-node-123'))
    assert wrong.status_code == 409 and wrong.json()['error']['code']=='IDEMPOTENCY_KEY_REUSED'
    before = client.get(f"/api/v1/projects/{pid}/map",headers=headers).json()
    target=before['nodes'][-1]['id']
    verified = client.post(f"/api/v1/projects/{pid}/nodes/ops",json={'operations':[{'op':'verify','nodeId':target,'verified':True}]},
                           headers=h(headers,2,'verify-node-111'))
    assert verified.status_code == 200, verified.text
    assert verified.json()['revision']==3
    stale=client.post(f"/api/v1/projects/{pid}/nodes/ops",json={'operations':[{'op':'rename','nodeId':target,'title':'stale'}]},
                      headers=h(headers,2,'stale-node-111'))
    assert stale.status_code==409
    dele=client.delete(f"/api/v1/projects/{pid}/sources/{sid}",headers=h(headers,3,'delete-src-111'))
    assert dele.status_code==200 and dele.json()['revision']==4
    now=client.get(f"/api/v1/projects/{pid}/map",headers=headers).json()
    assert len(now['nodes']) == 1  # the source-backed claim subtree is purged
    assert client.get(f"/api/v1/projects/{pid}/sources/{sid}/paragraphs",headers=headers).status_code==404


def test_draft_never_writes_without_commit_and_undo(client,headers,create_project):
    pid=create_project()['id']
    added=post_text(client,headers,pid,0,key='source-second-123')
    sid=added.json()['sourceId']
    req={'goal':'可信研究','sourceIds':[sid], 'language':'zh-CN'}
    generation=client.post(f'/api/v1/projects/{pid}/generate',json=req,headers=h(headers,1,'generate-0001'))
    assert generation.status_code==202,generation.text
    draft_id=generation.json()['draftId']
    j=client.get(f"/api/v1/jobs/{generation.json()['jobId']}",headers=headers)
    assert j.json()['status']=='completed'
    preview=client.get(f"/api/v1/projects/{pid}/generation-drafts/{draft_id}",headers=headers).json()
    assert preview['generationMode']=='extractive_demo'
    assert len(preview['map']['nodes'])>=3
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])==1
    accepted=client.post(f"/api/v1/projects/{pid}/generation-drafts/{draft_id}/commit",headers=h(headers,1,'commit-draft1'))
    assert accepted.status_code==200,accepted.text
    assert accepted.json()['revision']==2
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])>=3
    bad_commit=client.post(f"/api/v1/projects/{pid}/generation-drafts/{draft_id}/commit",headers=h(headers,2,'commit-draft2'))
    assert bad_commit.status_code==409
    undone=client.post(f"/api/v1/projects/{pid}/undo",headers=h(headers,2,'undo-gen-123'))
    assert undone.status_code==200,undone.text
    assert undone.json()['revision']==3
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])==1


def test_patch_preview_confirm_and_conflict(client,headers,create_project):
    pid=create_project()['id']
    root=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['rootId']
    req={'targetNodeId':root,'baseRevision':0,'operation':'challenge'}
    proposal=client.post(f'/api/v1/projects/{pid}/patches',json=req,headers=h(headers,key='patch-prop-111'))
    assert proposal.status_code==202, proposal.text
    patchid=proposal.json()['patchId']
    view=client.get(f'/api/v1/projects/{pid}/patches/{patchid}',headers=headers).json()
    opid=view['proposedOps'][0]['opId']
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])==1
    bad=client.post(f'/api/v1/projects/{pid}/patches/{patchid}/apply',json={'acceptedOpIds':['unknown']},headers=h(headers,0,'patch-apply-bad'))
    assert bad.status_code==422
    r=client.post(f'/api/v1/projects/{pid}/patches/{patchid}/apply',json={'acceptedOpIds':[opid]},headers=h(headers,0,'patch-apply-111'))
    assert r.status_code==200,r.text
    assert r.json()['revision']==1
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])==2
    stale=client.post(f'/api/v1/projects/{pid}/patches/{patchid}/apply',json={'acceptedOpIds':[opid]},headers=h(headers,0,'patch-apply-222'))
    assert stale.status_code==409
    # The generated child can be edited by a future AI patch only when scoped to it.
    second=client.post(f'/api/v1/projects/{pid}/patches',json={'targetNodeId':root,'baseRevision':1,'operation':'condense'},headers=h(headers,key='patch-condense-111'))
    assert second.status_code==501


def test_invalid_reference_rollback_and_quotas(client,headers,create_project):
    pid=create_project()['id']
    src=post_text(client,headers,pid,0,key='source-quote-11')
    sid=src.json()['sourceId']
    para=client.get(f'/api/v1/projects/{pid}/sources/{sid}/paragraphs',headers=headers).json()['items'][0]
    root=client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['rootId']
    response=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[
       {'op':'add','parentId':root,'node':{'title':'okay','type':'question'}},
       {'op':'add','parentId':root,'node':{'title':'fake','type':'claim','evidenceRefs':[
          {'sourceId':sid,'paragraphId':para['id'],'start':1,'end':3,'exactQuote':'假话'}]}}]},
       headers=h(headers,1,'invalid-quote-111'))
    assert response.status_code==422, response.text
    assert response.json()['error']['code']=='QUOTE_ANCHOR_INVALID'
    assert len(client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['nodes'])==1
    for i in range(4):
        p=client.get(f'/api/v1/projects/{pid}',headers=headers).json()
        r=post_text(client,headers,pid,p['revision'], text=f'内容 {i}',key=f'more-source-{i:03d}')
        assert r.status_code==202,r.text
    p=client.get(f'/api/v1/projects/{pid}',headers=headers).json()
    too_many=post_text(client,headers,pid,p['revision'],text='extra',key='sixth-source-111')
    assert too_many.status_code==429


def test_project_delete_and_no_idor(client,headers,create_project):
    pid=create_project()['id']
    src=post_text(client,headers,pid,0)
    assert src.status_code==202
    forbidden=client.get(f'/api/v1/projects/{pid}/sources',headers={'Authorization':'Bearer dev-bob'})
    assert forbidden.status_code==404
    forbidden_mutation=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':[]},headers=h({'Authorization':'Bearer dev-bob'},1,'bob-op-111'))
    assert forbidden_mutation.status_code==404 or forbidden_mutation.status_code==422
    removed=client.delete(f'/api/v1/projects/{pid}',headers=h(headers,1,'delete-proj-111'))
    assert removed.status_code==202, removed.text
    assert client.get(f'/api/v1/projects/{pid}',headers=headers).status_code==404


def test_export_md_and_json(client,headers,create_project):
    pid=create_project()['id']
    source=post_text(client,headers,pid,0)
    sid=source.json()['sourceId']
    generated=client.post(f'/api/v1/projects/{pid}/generate',json={'goal':'研究题目','sourceIds':[sid]},headers=h(headers,1,'gen-export-111'))
    did=generated.json()['draftId']
    client.post(f'/api/v1/projects/{pid}/generation-drafts/{did}/commit',headers=h(headers,1,'commit-export-1'))
    md=client.get(f'/api/v1/projects/{pid}/export?format=md',headers=headers)
    assert md.status_code==200 and md.text.startswith('<!-- TraceMap:')
    assert '# 研究题目' in md.text and '## 来源' in md.text and '### 😀结论' in md.text
    js=client.get(f'/api/v1/projects/{pid}/export?format=json',headers=headers)
    assert js.json()['revision']==2
    assert len(js.json()['map']['nodes'])>=3


def test_invalid_operation_shape_does_not_crash(client,headers,create_project):
    pid=create_project()['id']
    for ops in [[123],[{'op':'add','parentId':'nonexistent','node':{'title':'x'}}]]:
        r=client.post(f'/api/v1/projects/{pid}/nodes/ops',json={'operations':ops},headers=h(headers,0,'bad-op-'+str(ops[0])[:25]))
        assert r.status_code==422,r.text
        assert r.json()['error']['code']=='SCHEMA_INVALID'
    assert client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['revision']==0


def test_upload_scanned_pdf_fails_without_ghost_source(client,headers,create_project):
    from io import BytesIO
    from pypdf import PdfWriter
    pid=create_project()['id']
    writer=PdfWriter();writer.add_blank_page(width=320,height=400)
    data=BytesIO();writer.write(data)
    response=client.post(f'/api/v1/projects/{pid}/sources',headers=h(headers,0,'blank-pdf-00001'),
                         files={'file':('scan.pdf', data.getvalue(),'application/pdf')})
    assert response.status_code==422,response.text
    assert response.json()['error']['code']=='NO_EXTRACTABLE_TEXT'
    assert client.get(f'/api/v1/projects/{pid}/sources',headers=headers).json()['items']==[]
    assert client.get(f'/api/v1/projects/{pid}/map',headers=headers).json()['revision']==0


def test_cross_project_reference_rejected(client,headers,create_project):
    a=create_project('Project A')
    b=create_project('Project B')
    src=post_text(client,headers,a['id'],0,key='source-project-a-1')
    assert src.status_code==202
    sid=src.json()['sourceId']
    para=client.get(f"/api/v1/projects/{a['id']}/sources/{sid}/paragraphs",headers=headers).json()['items'][0]
    root=client.get(f"/api/v1/projects/{b['id']}/map",headers=headers).json()['rootId']
    r=client.post(f"/api/v1/projects/{b['id']}/nodes/ops",json={'operations':[{'op':'add','parentId':root,'node':{
       'type':'claim','title':'stolen evidence','evidenceRefs':[{'sourceId':sid,'paragraphId':para['id'],
                                                               'start':1,'end':3,'exactQuote':'结论'}]}}]},
       headers=h(headers,0,'cross-project-111'))
    assert r.status_code==422,r.text
    assert client.get(f"/api/v1/projects/{b['id']}/map",headers=headers).json()['revision']==0


def build_text_layer_pdf(pages):
    """Build a minimal, valid multi-page PDF with an extractable text layer.

    ``pages`` is a list of pages; each page is a list of text lines. This lets a
    test exercise the real pypdf parsing path without committing a binary asset.
    """
    assert pages
    objs = {1: b"<< /Type /Catalog /Pages 2 0 R >>",
            3: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for k, lines in enumerate(pages):
        content = "BT /F1 14 Tf 72 720 Td 18 TL\n" + "\n".join(f"({t}) Tj T*" for t in lines) + "\nET"
        stream = content.encode("latin-1")
        content_num, page_num = 4 + 2 * k, 5 + 2 * k
        kids.append(f"{page_num} 0 R")
        objs[content_num] = (b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
        objs[page_num] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                          f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_num} 0 R >>").encode()
    objs[2] = ("<< /Type /Pages /Kids [" + " ".join(kids) + f"] /Count {len(pages)} >>").encode()
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(objs):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode() + objs[num] + b"\nendobj\n"
    size = max(objs) + 1
    xref = len(out)
    out += f"xref\n0 {size}\n".encode() + b"0000000000 65535 f \n"
    for num in range(1, size):
        out += f"{offsets[num]:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def test_text_layer_pdf_parsed_with_page_numbers(client, headers, create_project):
    pid = create_project('pdf happy path')['id']
    data = build_text_layer_pdf([["Page one evidence line."], ["Page two findings here."]])
    response = client.post(f'/api/v1/projects/{pid}/sources',
                           headers=h(headers, 0, 'pdf-happy-0001'),
                           files={'file': ('report.pdf', data, 'application/pdf')})
    assert response.status_code == 202, response.text
    sid = response.json()['sourceId']
    assert response.json()['revision'] == 1
    sources = client.get(f'/api/v1/projects/{pid}/sources', headers=headers).json()['items']
    assert len(sources) == 1 and sources[0]['kind'] == 'pdf'
    assert sources[0]['extractedCharCount'] > 0
    items = client.get(f'/api/v1/projects/{pid}/sources/{sid}/paragraphs', headers=headers).json()['items']
    assert items, 'expected extracted paragraphs'
    pages = {p['pageNo'] for p in items}
    assert pages == {1, 2}, f'page mapping wrong: {pages}'
    text = ' '.join(p['text'] for p in items)
    assert 'Page one evidence line' in text and 'Page two findings here' in text


def test_upload_rejects_extension_magic_mismatch_and_binary(client, headers, create_project):
    pid = create_project('pdf rejects')['id']
    cases = [
        ('report.pdf', b'not a pdf at all', 'application/pdf', 'UNSUPPORTED_MEDIA_TYPE'),
        ('notes.txt', b'%PDF-1.4 fake', 'text/plain', 'UNSUPPORTED_MEDIA_TYPE'),
        ('data.bin', b'\x00\x01\x02binary', 'application/octet-stream', 'UNSUPPORTED_MEDIA_TYPE'),
    ]
    for i, (name, payload, mime, code) in enumerate(cases):
        r = client.post(f'/api/v1/projects/{pid}/sources',
                        headers=h(headers, 0, f'pdf-mismatch-{i:04d}'),
                        files={'file': (name, payload, mime)})
        assert r.status_code == 415, r.text
        assert r.json()['error']['code'] == code, r.text
    # none of the rejected uploads may leave a ghost source or bump the revision
    assert client.get(f'/api/v1/projects/{pid}/sources', headers=headers).json()['items'] == []
    assert client.get(f'/api/v1/projects/{pid}/map', headers=headers).json()['revision'] == 0
