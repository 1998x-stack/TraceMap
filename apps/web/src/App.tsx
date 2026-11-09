import React,{useCallback,useEffect,useMemo,useState} from 'react';
import ReactFlow,{Background,Controls,MiniMap,type NodeMouseHandler} from '@xyflow/react';
import {Api,ApiError,type Project,type Source,type MapDocument,type MapNode,type EvidenceRef,type Paragraph,type GenerationDraft,type PatchProposal} from './api';
import {layout,sliceCodepoints} from './layout';

const api=new Api('dev-alice');
const typeLabels:Record<string,string>={topic:'主题',claim:'主张',evidence:'依据',counterpoint:'反例',question:'问题',decision:'决策'};
const emptyIcon='◇';
function getError(err:unknown){return err instanceof ApiError?`${err.code} · ${err.message}`:err instanceof Error?err.message:String(err);}

export default function App(){
  const [projects,setProjects]=useState<Project[]>([]);
  const [active,setActive]=useState<Project|null>(null);
  const [tree,setTree]=useState<MapDocument|null>(null);
  const [sources,setSources]=useState<Source[]>([]);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [paragraphs,setParagraphs]=useState<Paragraph[]>([]);
  const [openedRef,setOpenedRef]=useState<EvidenceRef|null>(null);
  const [projectTitle,setProjectTitle]=useState('');
  const [projectGoal,setProjectGoal]=useState('');
  const [sourceTitle,setSourceTitle]=useState('');
  const [sourceText,setSourceText]=useState('');
  const [draft,setDraft]=useState<GenerationDraft|null>(null);
  const [patch,setPatch]=useState<PatchProposal|null>(null);
  const [accepted,setAccepted]=useState<Set<string>>(new Set());
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [editTitle,setEditTitle]=useState('');
  const [newChild,setNewChild]=useState('');
  const [panel,setPanel]=useState<'detail'|'source'>('detail');

  const refreshList=useCallback(async()=>{setProjects((await api.listProjects()).items);},[]);
  const load=useCallback(async(p:Project)=>{
    const [latest,map,src]=await Promise.all([api.project(p.id),api.map(p.id),api.sources(p.id)]);
    setActive(latest);setTree(map);setSources(src.items);
    setSelectedId(old=>old&&map.nodes.some(n=>n.id===old)?old:map.rootId);
    setPatch(null);setDraft(null);setOpenedRef(null);setParagraphs([]);
  },[]);
  useEffect(()=>{refreshList().catch(e=>setError(getError(e)));},[refreshList]);
  const selected=tree?.nodes.find(n=>n.id===selectedId)||null;
  const graph=useMemo(()=>tree?layout(tree):{nodes:[],edges:[]},[tree]);
  useEffect(()=>{setEditTitle(selected?.title||'');},[selected?.id,selected?.title]);
  async function run(action:()=>Promise<unknown>,message:string){
    setBusy(true);setError('');setNotice('');
    try{await action();setNotice(message);}catch(e){setError(getError(e));if(e instanceof ApiError&&e.status===409&&active){
      // Do not discard user form content on conflict; only refresh canonical map.
      const fresh=await api.map(active.id).catch(()=>null);if(fresh)setTree(fresh);
      setNotice('版本冲突：已刷新服务器版本，请重新审阅后提交。');
    }}finally{setBusy(false);}
  }
  async function reload(){if(!active)return;const p=await api.project(active.id);setActive(p);setTree(await api.map(active.id));setSources((await api.sources(active.id)).items);await refreshList();}
  const mutate=(ops:unknown[],msg:string)=>{if(!active||!tree)return;
    void run(async()=>{await api.edit(active.id,tree.revision,ops);await reload();},msg);
  };
  function openRef(ref:EvidenceRef){if(!active)return;setOpenedRef(ref);setPanel('source');setParagraphs([]);
    api.paragraphs(active.id,ref.sourceId).then(r=>setParagraphs(r.items)).catch(e=>setError(getError(e)));
  }
  const nodeClick:NodeMouseHandler=(_event,node)=>{setSelectedId(node.id);setPanel('detail');setOpenedRef(null);};
  const source=openedRef?sources.find(s=>s.id===openedRef.sourceId):null;
  const paragraph=openedRef?paragraphs.find(p=>p.id===openedRef.paragraphId):null;
  const visualHighlight=openedRef&&paragraph?sliceCodepoints(paragraph.text,openedRef.start,openedRef.end):null;
  return <div className="workspace">
    <aside className="rail">
      <div className="brand"><div className="brand-icon">T<span>.</span></div><div><strong>TraceMap</strong><small>Research OS · alpha</small></div></div>
      <div className="rail-label">WORKSPACE <span>{projects.length} 项目</span></div>
      <div className="project-list">{projects.map(p=><button key={p.id} className={'project-link '+(p.id===active?.id?'active':'')} onClick={()=>void run(()=>load(p),'已载入研究项目')}>
        <span className="project-glyph">◈</span><span className="project-link-text"><strong>{p.title}</strong><small>rev {p.revision} · {new Date(p.updatedAt).toLocaleDateString()}</small></span>
      </button>)}</div>
      <form className="new-project" onSubmit={e=>{e.preventDefault();if(!projectTitle.trim())return;void run(async()=>{const p=await api.createProject(projectTitle.trim(),projectGoal);setProjectTitle('');setProjectGoal('');await refreshList();await load(p);},'新项目已创建');}}>
        <label htmlFor="project-title">NEW PROJECT</label>
        <input id="project-title" placeholder="项目名称" maxLength={80} value={projectTitle} onChange={e=>setProjectTitle(e.target.value)}/>
        <input aria-label="研究目标" placeholder="研究目标（可选）" value={projectGoal} onChange={e=>setProjectGoal(e.target.value)}/>
        <button type="submit" className="button button-outline" disabled={busy||!projectTitle.trim()}>＋ 创建研究项目</button>
      </form>
      <div className="rail-bottom"><div className="dev-led"/>DEV MODE · dev-alice<br/><small>仅本机开发认证，禁止公网部署</small></div>
    </aside>
    <main className="main">
      <header className="topbar"><div className="breadcrumb">1998X <span>/</span> TraceMap <span>/</span> {active?.title||'Overview'}</div><div className="top-actions"><span className="revision">{tree?`↻ Revision ${tree.revision}`:'未选择项目'}</span>
       {active&&tree&&<><button className="button button-quiet" onClick={()=>void run(async()=>{await api.undo(active.id,tree.revision);await reload();},'最近一次地图变更已撤销')} disabled={busy}>↶ 撤销</button>
        <button className="button button-quiet" onClick={()=>void run(()=>api.download(active.id,'json'),'JSON 已导出')} disabled={busy}>JSON</button>
        <button className="button button-primary" onClick={()=>void run(()=>api.download(active.id,'md'),'Markdown 已导出')} disabled={busy}>导出 Markdown ↗</button></>}</div></header>
      <div className="dev-banner">演示阶段 · 本版本采用确定性原文摘录与规则建议，<b>没有连接真实 LLM</b>。目前只支持本机开发使用，不适合上传敏感资料。</div>
      {(error||notice)&&<div role={error?'alert':'status'} className={'feedback '+(error?'bad':'good')}><span>{error||notice}</span><button onClick={()=>{setError('');setNotice('');}} aria-label="关闭提示">×</button></div>}
      {!active||!tree?<div className="welcome"><div className="eyebrow">RESEARCH WORKSPACE / V0.1</div><h1>让每个结论，<br/><span>都有迹可循。</span></h1><p>上传原始资料，构建可追溯的研究地图。选择左侧的项目，或创建第一项研究。</p><div className="welcome-line"><span>01 Sources</span><span>02 Traceable nodes</span><span>03 Review changes</span></div></div>:
      <div className="studio">
        <section className="source-panel"><div className="panel-head"><div><div className="eyebrow">01 / MATERIALS</div><h2>研究资料 <span>{sources.length}/5</span></h2></div></div>
          {sources.length===0?<div className="empty-sources">{emptyIcon}<p>导入资料后即可生成有原文依据的草稿导图。</p></div>:<div className="source-list">{sources.map((s,index)=><button key={s.id} className="source-item" onClick={()=>{if(!active)return;setPanel('source');setOpenedRef(null);api.paragraphs(active.id,s.id).then(x=>setParagraphs(x.items));}}>
          <div className="source-number">{String(index+1).padStart(2,'0')}</div><div><strong>{s.title}</strong><small>{s.kind.toUpperCase()} · {s.extractedCharCount} 字符</small></div><span className="source-dot"/></button>)}</div>}
          <form className="source-form" onSubmit={e=>{e.preventDefault();if(!sourceText.trim())return;void run(async()=>{await api.addText(active.id,tree.revision,sourceTitle.trim()||'未命名材料',sourceText);setSourceText('');setSourceTitle('');await reload();},'资料已解析并保存');}}>
            <h3>添加一份资料</h3><input aria-label="来源标题" placeholder="来源名称" value={sourceTitle} maxLength={200} onChange={e=>setSourceTitle(e.target.value)}/>
            <textarea aria-label="来源正文" placeholder="粘贴研究材料、竞品介绍或访谈摘要……" value={sourceText} rows={5} onChange={e=>setSourceText(e.target.value)}/>
            <button className="button button-secondary" type="submit" disabled={busy||!sourceText.trim()||sources.length>=5}>＋ 添加文本来源</button>
            <label className="file-upload">↑ 上传 PDF / MD / TXT<input type="file" accept=".pdf,.md,.txt" disabled={busy||sources.length>=5} onChange={e=>{const file=e.target.files?.[0];e.target.value='';if(!file)return;void run(async()=>{await api.upload(active.id,tree.revision,file);await reload();},'文件已解析并保存');}}/></label>
            <small>每项目最多 5 份资料，总计 80,000 字符</small>
          </form>
        </section>
        <section className="map-panel"><div className="map-head"><div><div className="eyebrow">02 / REASONING CANVAS</div><h2>{active.title}</h2></div><div className="map-actions"><span className="node-count">{tree.nodes.length} NODES</span>
          <button className="button button-primary" onClick={()=>void run(async()=>{
            const job=await api.generate(active.id,tree.revision,active.goal||active.title,sources.map(x=>x.id));
            setDraft(await api.getDraft(active.id,job.draftId));},'已生成候选草稿，请在确认后应用')} disabled={busy||!sources.length}>◈ 生成原文结构草稿</button></div></div>
          <div className="canvas-container"><ReactFlow fitView fitViewOptions={{padding:0.23}} nodes={graph.nodes} edges={graph.edges} onNodeClick={nodeClick} nodesConnectable={false} elementsSelectable>
            <Background color="#26354d" gap={24} size={1}/><Controls showInteractive={false}/><MiniMap pannable zoomable nodeColor="#559eaf"/>
          </ReactFlow></div><div className="canvas-footer">CLICK A NODE TO INSPECT EVIDENCE <span>证据锚点 ≠ 事实真实性</span></div>
        </section>
        <section className="inspector"><div className="panel-head"><div className="eyebrow">03 / INSPECTOR</div><h2>来源与节点核验</h2></div><div className="inspector-tabs"><button className={panel==='detail'?'active':''} onClick={()=>setPanel('detail')}>节点详情</button><button className={panel==='source'?'active':''} onClick={()=>setPanel('source')}>原文位置</button></div>
          {panel==='detail'&&selected?<div className="inspector-content"><div className="node-type">{typeLabels[selected.type]||selected.type} · {selected.origin==='ai'?'规则生成':'人工创建'}</div>
          <label className="form-label">节点标题<input value={editTitle} onChange={e=>setEditTitle(e.target.value)} maxLength={160}/></label>
          <button className="button button-secondary" disabled={busy||!editTitle.trim()||editTitle===selected.title} onClick={()=>mutate([{op:'rename',nodeId:selected.id,title:editTitle}],'节点标题已保存')}>保存标题</button>
          <div className="detail-stat"><span>核验状态</span><strong className={selected.verification==='verified_by_user'?'verified':'unverified'}>{selected.verification==='verified_by_user'?'✓ 用户已核验':'◇ 待核验'}</strong></div>
          <button className="button button-outline" disabled={busy||(!selected.evidenceRefs.some(x=>x.anchorStatus==='anchored')&&selected.verification!=='verified_by_user')} onClick={()=>mutate([{op:'verify',nodeId:selected.id,verified:selected.verification!=='verified_by_user'}],'已更新人工核验状态')}>{selected.verification==='verified_by_user'?'撤回核验':'确认已核对原文'}</button>
          <h3>引用证据 <span>{selected.evidenceRefs.length}</span></h3>
          {selected.evidenceRefs.length===0?<p className="muted">尚无锚定引用。本节点不能标记为已核验。</p>:selected.evidenceRefs.map((r,index)=><button className="evidence-card" key={index} disabled={r.anchorStatus!=='anchored'} onClick={()=>openRef(r)}><span>{r.anchorStatus==='anchored'?'● 可定位':'○ '+r.anchorStatus}</span><strong>“{r.exactQuote.slice(0,110)}”</strong><small>查看原文位置 →</small></button>)}
          <div className="divider"/><h3>结构编辑</h3><label className="form-label">新增子节点<input placeholder="新的研究问题或判断" value={newChild} onChange={e=>setNewChild(e.target.value)}/></label>
          <button className="button button-secondary" disabled={busy||!newChild.trim()} onClick={()=>{mutate([{op:'add',parentId:selected.id,node:{type:'question',title:newChild}}],'已添加子节点');setNewChild('');}}>＋ 添加子节点</button>
          {selected.id!==tree.rootId&&<button className="button button-danger" disabled={busy} onClick={()=>{if(window.confirm('删除这个节点及其所有子节点？'))mutate([{op:'delete',nodeId:selected.id}],'节点子树已删除');}}>删除选中节点</button>}
          <div className="divider"/><h3>局部修改建议</h3><p className="muted">当前是规则型演示，建议必须预览并手工确认。</p>
          <div className="patch-buttons">{[{op:'questions',label:'追问'},{op:'challenge',label:'质疑'},{op:'expand',label:'扩展'}].map(a=><button key={a.op} className="button button-outline" disabled={busy} onClick={()=>void run(async()=>{const result=await api.propose(active.id,tree.revision,selected.id,a.op);setPatch(await api.getPatch(active.id,result.patchId));setAccepted(new Set());},'已生成未应用的修改提议')}>{a.label}</button>)}</div>
          </div>:panel==='source'?<div className="inspector-content"><div className="node-type">ORIGINAL DOCUMENT · READ ONLY</div><h3>{source?.title||'来源正文'}</h3>
          {paragraphs.length===0?<p className="muted">请选择左侧资料或点击节点证据引用以查看原文。</p>:openedRef&&paragraph&&visualHighlight?<div className="quote-context"><small>段落 {paragraph.ordinal+1} {paragraph.pageNo?`· 第 ${paragraph.pageNo} 页`:''}</small><p>{visualHighlight[0]}<mark>{visualHighlight[1]}</mark>{visualHighlight[2]}</p><div className="anchor-status">精确字符定位 · Unicode 码点</div></div>:paragraphs.map(p=><div className="quote-context" key={p.id}><small>段落 {p.ordinal+1}</small><p>{p.text}</p></div>)}
          </div>:<div className="inspector-content muted">点击中间画布的任意节点。</div>}
        </section>
      </div>}
      {draft&&active&&tree&&<div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="draft-title"><span className="eyebrow">REVIEW BEFORE COMMIT</span><h2 id="draft-title">导图草稿预览</h2><p>规则型原文摘录生成了 <b>{draft.map.nodes.length}</b> 个节点。确认前不会更改正式地图。它不是 AI 研究结论。</p>
      <div className="modal-items">{draft.map.nodes.slice(0,8).map(n=><div key={n.id}><span>{typeLabels[n.type]||n.type}</span><strong>{n.title.slice(0,110)}</strong></div>)}</div>
      <footer><button className="button button-quiet" onClick={()=>setDraft(null)}>取消</button><button className="button button-primary" disabled={busy} onClick={()=>void run(async()=>{await api.commitDraft(active.id,tree.revision,draft.draftId);setDraft(null);await reload();},'已确认并保存草稿')}>确认替换地图</button></footer></div></div>}
      {patch&&active&&tree&&<div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="patch-title"><span className="eyebrow">ATOMIC PATCH PROPOSAL</span><h2 id="patch-title">局部修改预览</h2><p>下列修改当前尚未写入地图。默认全部不选中；仅确认选中的操作。</p>
      <div className="modal-items">{patch.proposedOps.map(op=><label key={op.opId} className="proposal-item"><input type="checkbox" checked={accepted.has(op.opId)} onChange={e=>setAccepted(old=>{const next=new Set(old);e.target.checked?next.add(op.opId):next.delete(op.opId);return next;})}/><div><span>＋ 新增 {typeLabels[op.node.type]||op.node.type}</span><strong>{op.node.title}</strong></div></label>)}</div>
      <footer><button className="button button-quiet" onClick={()=>setPatch(null)}>放弃建议</button><button className="button button-primary" disabled={busy||accepted.size===0} onClick={()=>void run(async()=>{await api.applyPatch(active.id,tree.revision,patch.patchId,[...accepted]);setPatch(null);await reload();},'已原子应用选中的修改')}>确认应用 {accepted.size} 项</button></footer></div></div>}
    </main>
  </div>;
}
