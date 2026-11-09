import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {
  ReactFlow,Background,BackgroundVariant,Controls,MiniMap,type ReactFlowInstance,type Edge,
  type NodeMouseHandler,
} from '@xyflow/react';
import {
  Api,ApiError,type Project,type Source,type MapDocument,type MapNode,
  type EvidenceRef,type Paragraph,type GenerationDraft,type PatchProposal,type Health,
} from './api';
import {layout,sliceCodepoints} from './layout';
import ResearchNodeCard, {type ResearchFlowNode} from './components/ResearchNode';
import GenerationProgress, {type GenerationPhase} from './components/GenerationProgress';

const api=new Api('dev-alice');
const nodeTypes={research:ResearchNodeCard};
const typeLabels:Record<string,string>={topic:'主题',claim:'主张',evidence:'依据',counterpoint:'反例',question:'问题',decision:'决策'};
const patchTypes=[{op:'questions',label:'追问',note:'梳理仍需验证的问题',icon:'?'},{op:'challenge',label:'质疑',note:'补充反向观察',icon:'↗'},{op:'expand',label:'扩展',note:'延伸当前分支',icon:'+'}];
const kindSymbol:Record<string,string>={text:'T',markdown:'M',pdf:'P'};

function getError(error:unknown){
  return error instanceof ApiError?`${error.code} · ${error.message}`:error instanceof Error?error.message:String(error);
}
function savedLayoutPreference(key:string){
  try {return window.localStorage.getItem(key)==='1';}
  catch {return false;}
}
function dateLabel(value:string){
  try {return new Date(value).toLocaleDateString('zh-CN',{month:'2-digit',day:'2-digit'});}
  catch {return value.slice(0,10);}
}
function nodeTrail(tree:MapDocument,selected:MapNode|null){
  const index=new Map(tree.nodes.map(n=>[n.id,n]));
  const trail:string[]=[];
  let current:MapNode|undefined|null=selected;
  while(current&&trail.length<6){trail.unshift(current.title);current=current.parentId?index.get(current.parentId):undefined;}
  return trail;
}

/** A narrow screen is a reading task: render a deterministic outline instead of a tiny panned graph. */
function outlineTree(tree:MapDocument):Array<{node:MapNode;depth:number}>{
  const groups=new Map<string,MapNode[]>();
  for(const node of tree.nodes){if(node.parentId){const siblings=groups.get(node.parentId)||[];siblings.push(node);groups.set(node.parentId,siblings);}}
  for(const siblings of groups.values())siblings.sort((a,b)=>a.sortOrder-b.sortOrder||a.id.localeCompare(b.id));
  const byId=new Map(tree.nodes.map(n=>[n.id,n]));
  const result:Array<{node:MapNode;depth:number}>=[];
  const visit=(id:string,depth:number)=>{
    const node=byId.get(id);if(!node||result.length>=120)return;
    result.push({node,depth});
    for(const child of groups.get(id)||[])visit(child.id,depth+1);
  };
  visit(tree.rootId,0);
  return result;
}

export default function App(){
  const [projects,setProjects]=useState<Project[]>([]);
  const [active,setActive]=useState<Project|null>(null);
  const [tree,setTree]=useState<MapDocument|null>(null);
  const [sources,setSources]=useState<Source[]>([]);
  const [selectedId,setSelectedId]=useState<string|null>(null);
  const [paragraphs,setParagraphs]=useState<Paragraph[]>([]);
  const [openedRef,setOpenedRef]=useState<EvidenceRef|null>(null);
  const [inspectedSourceId,setInspectedSourceId]=useState<string|null>(null);
  const [loadingSource,setLoadingSource]=useState(false);
  const [projectTitle,setProjectTitle]=useState('');
  const [projectGoal,setProjectGoal]=useState('');
  const [sourceTitle,setSourceTitle]=useState('');
  const [sourceText,setSourceText]=useState('');
  const [draft,setDraft]=useState<GenerationDraft|null>(null);
  const [patch,setPatch]=useState<PatchProposal|null>(null);
  const [accepted,setAccepted]=useState<Set<string>>(new Set());
  const [busy,setBusy]=useState(false);
  const [generation,setGeneration]=useState<null|{phase:GenerationPhase; mode:'llm'|'extractive'; sourceCount:number; startedAt:number}>(null);
  const generationLock=useRef(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [health,setHealth]=useState<Health|null>(null);
  const [editTitle,setEditTitle]=useState('');
  const [newChild,setNewChild]=useState('');
  const [panel,setPanel]=useState<'detail'|'source'>('detail');
  const [search,setSearch]=useState('');
  const [composerOpen,setComposerOpen]=useState(true);
  const [navCollapsed,setNavCollapsed]=useState(()=>savedLayoutPreference('tracemap.navCollapsed'));
  const [sourceCollapsed,setSourceCollapsed]=useState(()=>savedLayoutPreference('tracemap.sourceCollapsed'));
  const [inspectorCollapsed,setInspectorCollapsed]=useState(()=>savedLayoutPreference('tracemap.inspectorCollapsed'));
  const [canvasFullscreen,setCanvasFullscreen]=useState(false);
  const fullscreenFallback=useRef(false);
  const mapPanelRef=useRef<HTMLElement|null>(null);
  const sourceRequest=useRef(0);
  const modalRef=useRef<HTMLDivElement|null>(null);
  const canvasFlow=useRef<ReactFlowInstance<ResearchFlowNode,Edge>|null>(null);

  const refreshList=useCallback(async()=>{setProjects((await api.listProjects()).items);},[]);
  const load=useCallback(async(project:Project)=>{
    const [latest,map,src]=await Promise.all([api.project(project.id),api.map(project.id),api.sources(project.id)]);
    sourceRequest.current++;
    setActive(latest);setTree(map);setSources(src.items);
    setSelectedId(old=>old&&map.nodes.some(n=>n.id===old)?old:map.rootId);
    setPatch(null);setDraft(null);setOpenedRef(null);setParagraphs([]);setInspectedSourceId(null);
    setPanel('detail');setLoadingSource(false);
  },[]);
  useEffect(()=>{refreshList().catch(e=>setError(getError(e)));},[refreshList]);
  useEffect(()=>{api.health().then(setHealth).catch(()=>{});},[]);
  useEffect(()=>{
    try {
      localStorage.setItem('tracemap.navCollapsed',navCollapsed?'1':'0');
      localStorage.setItem('tracemap.sourceCollapsed',sourceCollapsed?'1':'0');
      localStorage.setItem('tracemap.inspectorCollapsed',inspectorCollapsed?'1':'0');
    } catch { /* Private browsing may disable storage; in-memory controls still work. */ }
  },[navCollapsed,sourceCollapsed,inspectorCollapsed]);
  useEffect(()=>{
    const syncFullscreen=()=>{
      const native=document.fullscreenElement===mapPanelRef.current;
      if(native)fullscreenFallback.current=false;
      setCanvasFullscreen(native||fullscreenFallback.current);
    };
    const escapeFallback=(event:KeyboardEvent)=>{
      if(event.key==='Escape'&&fullscreenFallback.current){
        fullscreenFallback.current=false;
        setCanvasFullscreen(false);
      }
    };
    document.addEventListener('fullscreenchange',syncFullscreen);
    window.addEventListener('keydown',escapeFallback);
    return()=>{
      document.removeEventListener('fullscreenchange',syncFullscreen);
      window.removeEventListener('keydown',escapeFallback);
    };
  },[]);
  useEffect(()=>{
    if(!draft&&!patch)return;
    const previous=document.activeElement instanceof HTMLElement?document.activeElement:null;
    modalRef.current?.focus();
    const dismiss=(e:KeyboardEvent)=>{
      if(e.key==='Escape'){setDraft(null);setPatch(null);}
    };
    window.addEventListener('keydown',dismiss);
    return()=>{window.removeEventListener('keydown',dismiss);previous?.focus();};
  },[draft,patch]);

  const selected=tree?.nodes.find(n=>n.id===selectedId)||null;
  const graph=useMemo(()=>tree?layout(tree):{nodes:[],edges:[]},[tree]);
  const outline=useMemo(()=>tree?outlineTree(tree):[],[tree]);
  const verifiedCount=tree?.nodes.filter(n=>n.verification==='verified_by_user').length??0;
  const anchoredCount=tree?.nodes.filter(n=>n.evidenceRefs.some(r=>r.anchorStatus==='anchored')).length??0;
  const llmActive=health?.generationProvider==='llm';
  const filteredProjects=projects.filter(p=>p.title.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const sourceChars=sources.reduce((sum,s)=>sum+s.extractedCharCount,0);
  useEffect(()=>{
    if(!tree)return;
    // Wait until React Flow has committed and measured the latest nodes before fitting.
    // A zero-duration fit avoids a misleading, temporarily clipped canvas after commit.
    const timer=window.setTimeout(()=>{void canvasFlow.current?.fitView({padding:0.25,minZoom:0.25,maxZoom:1.05,duration:0});},160);
    return()=>window.clearTimeout(timer);
  },[active?.id,tree?.revision,tree?.nodes.length]);

  const selectedTrail=tree?nodeTrail(tree,selected):[];
  useEffect(()=>setEditTitle(selected?.title||''),[selected?.id,selected?.title]);

  async function run(action:()=>Promise<unknown>,message:string){
    setBusy(true);setError('');setNotice('');
    try {await action();setNotice(message);}
    catch(error){
      setError(getError(error));
      if(error instanceof ApiError&&error.status===409&&active){
        // Keep unsent user inputs; refresh only canonical map and revision.
        const latest=await api.map(active.id).catch(()=>null);
        if(latest)setTree(latest);
        setNotice('版本冲突：已刷新服务器版本，请重新审阅后再提交。');
      }
    }finally{setBusy(false);}
  }
  async function reload(){
    if(!active)return;
    const [nextProject,nextMap,nextSources]=await Promise.all([api.project(active.id),api.map(active.id),api.sources(active.id)]);
    setActive(nextProject);setTree(nextMap);setSources(nextSources.items);
    await refreshList();
  }
  function mutate(ops:unknown[],message:string,afterSuccess?:()=>void){
    if(!active||!tree)return;
    void run(async()=>{await api.edit(active.id,tree.revision,ops);await reload();afterSuccess?.();},message);
  }
  function inspectSource(sourceId:string,ref:EvidenceRef|null=null){
    if(!active)return;
    const request=++sourceRequest.current;
    setPanel('source');setInspectorCollapsed(false);setInspectedSourceId(sourceId);setOpenedRef(ref);
    setParagraphs([]);setLoadingSource(true);
    api.paragraphs(active.id,sourceId).then(result=>{
      if(request===sourceRequest.current)setParagraphs(result.items);
    }).catch(e=>{if(request===sourceRequest.current)setError(getError(e));})
      .finally(()=>{if(request===sourceRequest.current)setLoadingSource(false);});
  }
  const nodeClick:NodeMouseHandler=(_e,node)=>{setSelectedId(node.id);setPanel('detail');setOpenedRef(null);setInspectorCollapsed(false);};
  const inspectedSource=sources.find(s=>s.id===inspectedSourceId);
  const citedParagraph=openedRef?paragraphs.find(p=>p.id===openedRef.paragraphId):null;
  const highlight=openedRef&&citedParagraph?sliceCodepoints(citedParagraph.text,openedRef.start,openedRef.end):null;

  const createProject=async(event:React.FormEvent)=>{
    event.preventDefault();if(!projectTitle.trim())return;
    await run(async()=>{
      const created=await api.createProject(projectTitle.trim(),projectGoal.trim());
      setProjectTitle('');setProjectGoal('');
      await refreshList();await load(created);
    },'新项目已创建');
  };
  const submitSource=(event:React.FormEvent)=>{
    event.preventDefault();if(!active||!tree||!sourceText.trim())return;
    void run(async()=>{
      await api.addText(active.id,tree.revision,sourceTitle.trim()||'未命名材料',sourceText);
      setSourceText('');setSourceTitle('');await reload();
    },'资料已解析并保存');
  };
  const toggleCanvasFullscreen=async()=>{
    const element=mapPanelRef.current;
    if(!element)return;
    if(canvasFullscreen){
      if(document.fullscreenElement===element){
        try {await document.exitFullscreen();}
        catch {return;}
      }else{
        fullscreenFallback.current=false;
        setCanvasFullscreen(false);
      }
      return;
    }
    if(typeof element.requestFullscreen==='function'){
      try {
        await element.requestFullscreen();
        fullscreenFallback.current=false;
        setCanvasFullscreen(true);
        return;
      } catch { /* Use the CSS focus mode when browser fullscreen is unavailable. */ }
    }
    fullscreenFallback.current=true;
    setCanvasFullscreen(true);
  };

  const generate=()=>{
    if(!active||!tree||busy||generationLock.current||sources.length===0)return;
    // Immediate ref lock prevents two requests before React commits busy=true.
    generationLock.current=true;
    const pid=active.id, revision=tree.revision;
    setBusy(true);setError('');setNotice('');
    setGeneration({phase:'waiting',mode:llmActive?'llm':'extractive',sourceCount:sources.length,startedAt:Date.now()});
    void (async()=>{
      try {
        const job=await api.generate(pid,revision,active.goal||active.title,sources.map(x=>x.id));
        setGeneration(previous=>previous?{...previous,phase:'reading'}:null);
        const proposal=await api.getDraft(pid,job.draftId);
        setDraft(proposal);
        setNotice('候选草稿已生成；请核对证据后再决定是否替换正式地图。');
      } catch(err) {
        setError(getError(err));
        if(err instanceof ApiError&&err.status===409){
          const latest=await api.map(pid).catch(()=>null);
          if(latest)setTree(latest);
          setNotice('服务器版本已变化，生成未提交。请检查最新地图并重新审阅。');
        }
      } finally {
        generationLock.current=false;
        setGeneration(null);
        setBusy(false);
      }
    })();
  };

  return <div className="workspace">
    <aside className={'rail '+(navCollapsed?'is-collapsed':'')} aria-label="研究项目导航">
      <div className="brand"><div className="brand-icon" aria-hidden="true"><span className="brand-orbit">◎</span></div>
        <div><strong>TraceMap<span className="brand-period">.</span></strong><small>EVIDENCE WORKSPACE</small></div>
        <button className="rail-toggle" type="button" aria-label={navCollapsed?'展开项目导航':'折叠项目导航'}
          aria-expanded={!navCollapsed} title={navCollapsed?'展开项目导航':'折叠项目导航'}
          onClick={()=>setNavCollapsed(value=>!value)}>{navCollapsed?'›':'‹'}</button>
      </div>
      <div className="rail-section"><div className="rail-label">YOUR WORKSPACE <span className="rail-count">{projects.length.toString().padStart(2,'0')}</span></div>
        <div className="project-search-wrap"><span aria-hidden="true">⌕</span><input aria-label="搜索项目" placeholder="搜索研究项目" value={search} onChange={e=>setSearch(e.target.value)}/></div>
        <div className="project-list">
          {filteredProjects.length===0?<div className="rail-empty">{projects.length===0?'还没有研究项目':'未找到符合条件的项目'}</div>:
            filteredProjects.map(p=><button key={p.id} type="button" disabled={busy}
              className={'project-link '+(p.id===active?.id?'active':'')}
              aria-label={'打开项目：'+p.title} title={p.title}
              aria-current={p.id===active?.id?'page':undefined}
              onClick={()=>void run(()=>load(p),'已载入研究项目')}>
              <span className="project-glyph" aria-hidden="true">◈</span>
              <span className="project-link-text"><strong>{p.title}</strong><small>{dateLabel(p.updatedAt)} · REV {p.revision.toString().padStart(2,'0')}</small></span>
              {p.id===active?.id&&<span className="active-pin" aria-label="当前项目"/>}
            </button>)}
        </div>
      </div>
      <form className="new-project" onSubmit={e=>void createProject(e)}>
        <div className="new-project-heading"><span className="tiny-plus" aria-hidden="true">+</span><label htmlFor="project-title">NEW RESEARCH</label></div>
        <input id="project-title" placeholder="项目名称" maxLength={80} value={projectTitle} onChange={e=>setProjectTitle(e.target.value)}/>
        <input aria-label="研究目标" placeholder="想要回答什么问题？（可选）" maxLength={1000} value={projectGoal} onChange={e=>setProjectGoal(e.target.value)}/>
        <button className="button button-outline" type="submit" disabled={busy||!projectTitle.trim()}>＋ 创建研究项目</button>
      </form>
      <div className="rail-spacer"/>
      <div className="rail-guide"><div className="rail-guide-head"><span className="guide-mark">✳</span><span>HOW IT WORKS</span></div>
        <p>不止于生成。<br/>让每个判断都经得起追溯。</p>
        <div className="guide-progress"><span>资料</span><i/><span>结构</span><i/><span>核验</span></div>
      </div>
      <div className="rail-bottom"><div className="dev-led"/><span>DEV MODE · dev-alice</span><small>本地实验环境 · 非生产认证</small></div>
    </aside>

    <main className="main" id="main">
      <header className="topbar">
        <div className="breadcrumb"><span>WORKSPACE</span><span className="crumb-divider">/</span>
          <strong>{active?.title||'研究首页'}</strong></div>
        <div className="top-actions">
          <div className="save-indicator"><span className={`status-dot ${busy?'pulse':''}`}/><span>{busy?'正在处理…':tree?`本地已同步 · REV ${tree.revision}`:'准备开始'}</span></div>
          {active&&tree&&<>
            <button className="button button-quiet" disabled={busy} title="撤销上一次已确认的地图修改" onClick={()=>void run(async()=>{await api.undo(active.id,tree.revision);await reload();},'最近一次地图变更已撤销')}>↶ 撤销</button>
            <button className="button button-quiet export-json" disabled={busy} onClick={()=>void run(()=>api.download(active.id,'json'),'JSON 已导出')}>JSON</button>
            <button className="button button-primary export-main" disabled={busy} onClick={()=>void run(()=>api.download(active.id,'md'),'Markdown 已导出')}>导出 Markdown ↗</button>
          </>}
        </div>
      </header>
      <div className="dev-banner"><span className="dev-banner-label">DEVELOPMENT PREVIEW</span><span>{llmActive
        ? <>已连接真实 LLM（<b>{health?.generationModel||'iagent/standard'}</b>）· 候选内容必须人工确认 · 仅限本机开发，勿上传敏感信息</>
        : <>规则型原文摘录演示 · <b>没有连接真实 LLM</b> · 仅限本机开发，勿上传敏感信息</>}</span></div>
      {(error||notice)&&<div role={error?'alert':'status'} className={'feedback '+(error?'bad':'good')}>
        <span className="feedback-icon" aria-hidden="true">{error?'!':'✓'}</span><span>{error||notice}</span>
        <button type="button" onClick={()=>{setError('');setNotice('');}} aria-label="关闭提示">×</button></div>}

      {!active||!tree ? <section className="welcome">
        <div className="welcome-glow" aria-hidden="true"><div className="glow-ring ring-one"/><div className="glow-ring ring-two"/><div className="glow-core">◎</div></div>
        <div className="welcome-content">
          <div className="eyebrow"><span className="eyebrow-line"/> RESEARCH NOTEBOOK · SCHOLARLY EDITION</div>
          <h1>从信息，到结构。<br/><span>从观点，到证据。</span></h1>
          <p>将零散资料转化为可编辑、可溯源的思维导图。<br/>每一条证据有出处，每一次修改由你决定。</p>
          <div className="welcome-instruction"><span className="welcome-arrow">↖</span><span>从左侧创建一个研究项目，即可开始。</span></div>
          <div className="welcome-stages"><div><strong>01</strong><span>收集资料</span><small>源头可追溯</small></div><div><strong>02</strong><span>组织论点</span><small>结构一目了然</small></div><div><strong>03</strong><span>人工审阅</span><small>修改始终可控</small></div></div>
        </div>
      </section> : <div className={'studio'+(sourceCollapsed?' source-collapsed':'')+(inspectorCollapsed?' inspector-collapsed':'')}>
        <section className={'source-panel'+(sourceCollapsed?' is-collapsed':'')} aria-label="研究资料">
          {sourceCollapsed?<button className="sidebar-expand-tab" type="button" aria-label="展开研究资料侧栏"
            title="展开研究资料侧栏" onClick={()=>setSourceCollapsed(false)}><span aria-hidden="true">›</span><span>资料</span></button>:<>
          <div className="panel-head"><div><div className="eyebrow">01 / KNOWLEDGE BASE</div><h2>研究资料 <span className="panel-counter">{sources.length}/5</span></h2></div>
            <div className="panel-head-actions"><span className="panel-head-symbol" aria-hidden="true">▤</span>
              <button className="panel-collapse-toggle" type="button" aria-label="折叠研究资料侧栏" title="折叠研究资料侧栏"
                aria-expanded="true" onClick={()=>setSourceCollapsed(true)}>‹</button></div></div>
          <div className="source-overview"><span>已收录资料</span><strong>{sourceChars.toLocaleString('en-US')} <small>/ 80,000 字符</small></strong>
            <div className="quota-track"><span style={{width:`${Math.min(100,sourceChars/80000*100)}%`}}/></div></div>
          {sources.length===0?<div className="empty-sources"><div className="empty-icon">▤</div><strong>知识库还是空的</strong><p>粘贴访谈、竞品介绍或研究文档，开始建立有出处的研究地图。</p></div>:
            <div className="source-list">{sources.map((s,index)=><button key={s.id} type="button" disabled={busy} className={'source-item '+(s.id===inspectedSourceId?'selected':'')}
              onClick={()=>inspectSource(s.id)}><div className="source-number">{kindSymbol[s.kind]||String(index+1).padStart(2,'0')}</div><div className="source-item-body"><strong title={s.title}>{s.title}</strong>
              <small>{s.kind.toUpperCase()} <span>·</span> {s.extractedCharCount.toLocaleString()} 字符</small></div><span className="source-item-trailing" aria-hidden="true">↗</span></button>)}</div>}
          <div className="source-composer">
            <button className="composer-toggle" type="button" aria-expanded={composerOpen} onClick={()=>setComposerOpen(x=>!x)}>
              <span><span className="composer-plus">+</span> 添加研究资料</span><span className="composer-chevron" aria-hidden="true">{composerOpen?'⌃':'⌄'}</span>
            </button>
            {composerOpen&&<form className="source-form" onSubmit={submitSource}>
              <input aria-label="来源标题" placeholder="来源名称（例如：竞品访谈）" value={sourceTitle} maxLength={200} onChange={e=>setSourceTitle(e.target.value)}/>
              <textarea aria-label="来源正文" placeholder="在这里粘贴研究资料……" value={sourceText} rows={5} onChange={e=>setSourceText(e.target.value)}/>
              <button className="button button-secondary source-submit" type="submit" disabled={busy||!sourceText.trim()||sources.length>=5}>＋ 添加文本来源</button>
              <label className={'file-upload '+(busy||sources.length>=5?'disabled':'')}>↥ 上传 PDF / MD / TXT
                <input type="file" accept=".pdf,.md,.txt" disabled={busy||sources.length>=5} onChange={e=>{
                  const file=e.target.files?.[0];e.target.value='';if(!file)return;
                  void run(async()=>{await api.upload(active.id,tree.revision,file);await reload();},'文件已解析并保存');
                }}/>
              </label><small>最多 5 份文件，单份 ≤10 MB；扫描版 PDF 暂不支持。</small>
            </form>}
          </div>
          </>}
        </section>

        <section ref={mapPanelRef} className={'map-panel'+(canvasFullscreen?' is-canvas-fullscreen':'')} aria-label="研究地图画布">
          <div className="map-head"><div className="map-project-meta"><div className="eyebrow">02 / REASONING CANVAS</div><h2 title={active.title}>{active.title}</h2><p>{active.goal||'让每个结论，都有迹可循。'}</p></div>
            <div className="map-actions"><span className="node-count">{tree.nodes.length} NODES</span>
              <button className="button button-quiet fullscreen-toggle" type="button" aria-label={canvasFullscreen?'退出画布全屏':'全屏显示画布'}
                aria-pressed={canvasFullscreen} title={canvasFullscreen?'退出画布全屏':'全屏显示画布'}
                onClick={()=>void toggleCanvasFullscreen()}>{canvasFullscreen?'↙ 退出全屏':'⛶ 全屏画布'}</button>
              <button className="button button-primary" disabled={busy||sources.length===0} onClick={generate}>{llmActive?'◈ 生成候选导图（LLM）':'◈ 生成原文结构草稿'}</button></div>
          </div>
          {generation&&<GenerationProgress phase={generation.phase} mode={generation.mode}
            sourceCount={generation.sourceCount} startedAt={generation.startedAt}/>}
          <div className="map-metrics" aria-label="地图摘要">
            <div><span className="metric-pictogram">◇</span> <strong>{tree.nodes.length}</strong> 节点</div>
            <div><span className="metric-pictogram mint">◈</span> <strong>{anchoredCount}</strong> 有来源</div>
            <div><span className="metric-pictogram gold">✦</span> <strong>{verifiedCount}</strong> 已核验</div>
            <div className="metric-note">点击节点查看细节 <span>↗</span></div>
          </div>
          <div className="canvas-container">
            <div className="canvas-key"><span><i className="legend-swatch legend-claim"/> 主张</span><span><i className="legend-swatch legend-evidence"/> 证据</span><span><i className="legend-swatch legend-question"/> 待探索</span></div>
            {tree.nodes.length===1&&<div className="canvas-hint" aria-live="polite"><span>✳</span> 导入资料后，生成你的第一张研究地图。</div>}
            <div className="mobile-outline" role="tree" aria-label="移动端研究地图">
              <div className="mobile-outline-heading">MAP OUTLINE <span>{outline.length} 个节点</span></div>
              {outline.map(({node,depth})=><button key={node.id} type="button" role="treeitem" aria-level={depth+1}
                aria-selected={selectedId===node.id}
                className={'outline-node '+(node.id===selectedId?'selected':'')}
                style={{paddingLeft:14+depth*16}}
                onClick={()=>{setSelectedId(node.id);setPanel('detail');setInspectorCollapsed(false);document.querySelector('.inspector')?.scrollIntoView({behavior:'smooth',block:'start'});}}>
                <span className="outline-type">{typeLabels[node.type]||node.type}</span>
                <strong>{node.title}</strong>
                <small>{node.verification==='verified_by_user'?'✓ 人工已核验':node.evidenceRefs.some(r=>r.anchorStatus==='anchored')?'◈ 有原文引用':'◇ 待核验'}</small>
              </button>)}
              <p className="mobile-outline-note">在移动端使用层级阅读视图。点击任一节点可跳转至证据与编辑面板。</p>
            </div>
            <ReactFlow nodes={graph.nodes} edges={graph.edges} nodeTypes={nodeTypes}
              fitView fitViewOptions={{padding:0.24,minZoom:0.4,maxZoom:1.05}}
              onNodeClick={nodeClick} onInit={instance=>{canvasFlow.current=instance;}} nodesConnectable={false} nodesDraggable={false} elementsSelectable
              minZoom={0.25} maxZoom={1.8} snapToGrid={false} proOptions={{hideAttribution:true}}>
              <Background variant={BackgroundVariant.Dots} color="#d2d9df" gap={22} size={1.2}/>
              <Controls showInteractive={false} position="bottom-left"/>
              <MiniMap position="bottom-right" pannable zoomable nodeColor="#608c94" maskColor="rgba(228,235,237,.75)"/>
            </ReactFlow>
          </div>
          <div className="canvas-footer"><span>TRACEABLE BY DESIGN <i/> LOCAL WORKSPACE</span><span>可定位的引用 ≠ 外部真实性证明</span></div>
        </section>

        <section className={'inspector'+(inspectorCollapsed?' is-collapsed':'')} aria-label="节点与原文检查器">
          {inspectorCollapsed?<button className="sidebar-expand-tab" type="button" aria-label="展开证据检查侧栏"
            title="展开证据检查侧栏" onClick={()=>setInspectorCollapsed(false)}><span aria-hidden="true">‹</span><span>审阅</span></button>:<>
          <div className="panel-head inspector-head"><div><div className="eyebrow">03 / EVIDENCE INSPECTOR</div><h2>审阅与核验</h2></div>
            <div className="panel-head-actions"><span className="panel-head-symbol" aria-hidden="true">⌁</span>
              <button className="panel-collapse-toggle" type="button" aria-label="折叠证据检查侧栏" title="折叠证据检查侧栏"
                aria-expanded="true" onClick={()=>setInspectorCollapsed(true)}>›</button></div></div>
          <div className="inspector-tabs" role="tablist" aria-label="检查器视图">
            <button type="button" role="tab" aria-selected={panel==='detail'} className={panel==='detail'?'active':''} onClick={()=>setPanel('detail')}>节点详情</button>
            <button type="button" role="tab" aria-selected={panel==='source'} className={panel==='source'?'active':''} onClick={()=>setPanel('source')}>原文位置</button>
          </div>
          {panel==='detail'&&selected?<div className="inspector-content" role="tabpanel">
            <div className="inspector-context">{selectedTrail.map((t,i)=><React.Fragment key={i}>{i>0&&<span>›</span>}<span className={i===selectedTrail.length-1?'current':''}>{t}</span></React.Fragment>)}</div>
            <div className="node-meta"><span className="node-type">{typeLabels[selected.type]||selected.type}</span><span className="node-origin-label">{selected.origin==='ai'?'◈ 规则生成':'✎ 人工创建'}</span></div>
            <h3 className="section-heading">节点内容</h3>
            <label className="form-label">节点标题<input value={editTitle} onChange={e=>setEditTitle(e.target.value)} maxLength={160}/></label>
            <button className="button button-secondary inspector-wide" disabled={busy||!editTitle.trim()||editTitle===selected.title}
              onClick={()=>mutate([{op:'rename',nodeId:selected.id,title:editTitle}],'节点标题已保存')}>保存标题</button>
            <div className="inspector-divider"/>
            <h3 className="section-heading">可信度与核验</h3>
            <div className="verification-box"><span className={`verification-symbol ${selected.verification==='verified_by_user'?'is-verified':''}`}>{selected.verification==='verified_by_user'?'✓':'?'}</span>
              <div><strong>{selected.verification==='verified_by_user'?'用户已核验':'等待人工核验'}</strong><small>{selected.verification==='verified_by_user'?'该判断已由你确认过原文':'来源可追溯不代表内容一定真实'}</small></div></div>
            <button className="button button-outline inspector-wide" disabled={busy||(!selected.evidenceRefs.some(x=>x.anchorStatus==='anchored')&&selected.verification!=='verified_by_user')}
              onClick={()=>mutate([{op:'verify',nodeId:selected.id,verified:selected.verification!=='verified_by_user'}],'已更新人工核验状态')}>
              {selected.verification==='verified_by_user'?'撤回核验':'确认已核对原文'}</button>
            <h3 className="section-heading evidence-heading">引用证据 <span>{selected.evidenceRefs.length}</span></h3>
            {selected.evidenceRefs.length===0?<p className="muted empty-evidence">本节点还没有引用。请添加证据后再标记为已核验。</p>:
              selected.evidenceRefs.map((ref,index)=><button type="button" className="evidence-card" key={`${ref.paragraphId}-${index}`}
                disabled={ref.anchorStatus!=='anchored'} onClick={()=>inspectSource(ref.sourceId,ref)}>
                <span className={`evidence-status ${ref.anchorStatus==='anchored'?'is-anchored':''}`}>{ref.anchorStatus==='anchored'?'● 可定位原文':'○ '+ref.anchorStatus}</span>
                <strong>“{ref.exactQuote.slice(0,110)}”</strong>
                <small>{sources.find(s=>s.id===ref.sourceId)?.title||'来源'} <span>查看原文 →</span></small>
              </button>)}
            <div className="inspector-divider"/>
            <h3 className="section-heading">组织结构</h3>
            <label className="form-label">新增子节点<input placeholder="新的研究问题或判断" maxLength={160} value={newChild} onChange={e=>setNewChild(e.target.value)}/></label>
            <button className="button button-secondary inspector-wide" disabled={busy||!newChild.trim()} onClick={()=>mutate([{op:'add',parentId:selected.id,node:{type:'question',title:newChild}}],'已添加子节点',()=>setNewChild(''))}>＋ 添加子节点</button>
            {selected.id!==tree.rootId&&<button className="button button-danger inspector-wide" disabled={busy}
              onClick={()=>{if(window.confirm('删除这个节点及其所有子节点？'))mutate([{op:'delete',nodeId:selected.id}],'节点子树已删除');}}>删除选中节点</button>}
            <div className="inspector-divider"/>
            <div className="ai-heading"><h3 className="section-heading">局部修改建议</h3><span>REVIEW FIRST</span></div>
            <p className="muted">规则型演示建议。所有修改必须先审阅，再手动确认。</p>
            <div className="patch-buttons">{patchTypes.map(item=><button type="button" key={item.op} className="button button-outline" disabled={busy}
              aria-label={item.label} title={item.note} onClick={()=>void run(async()=>{
                const response=await api.propose(active.id,tree.revision,selected.id,item.op);
                setPatch(await api.getPatch(active.id,response.patchId));setAccepted(new Set());
              },'已生成未应用的修改提议')}><span aria-hidden="true">{item.icon}</span>{item.label}</button>)}</div>
          </div>:
          panel==='source'?<div className="inspector-content" role="tabpanel">
            <div className="source-readonly"><span className="status-dot"/> ORIGINAL DOCUMENT · READ ONLY</div>
            <h3 className="source-document-title">{inspectedSource?.title||'来源正文'}</h3>
            {loadingSource?<p className="muted">正在定位原文……</p>:
              paragraphs.length===0?<div className="source-empty-state"><span>▤</span><p>选择左侧资料，或点击节点上的引用，即可阅读未经 AI 改写的原始段落。</p></div>:
                openedRef&&citedParagraph&&highlight?<div className="quote-context"><small>段落 {citedParagraph.ordinal+1} {citedParagraph.pageNo?`· 第 ${citedParagraph.pageNo} 页`:''}</small>
                  <p>{highlight[0]}<mark>{highlight[1]}</mark>{highlight[2]}</p><div className="anchor-status">✓ 原文精确字符定位 · Unicode 码点</div></div>:
                  paragraphs.map(p=><div className="quote-context" key={p.id}><small>段落 {p.ordinal+1} {p.pageNo?`· 第 ${p.pageNo} 页`:''}</small><p>{p.text}</p></div>)}
            <p className="source-footnote">显示的是原始资料文本，不代表来源事实已经得到独立验证。</p>
          </div>:<div className="inspector-content muted">点击画布中的节点，查看其来源与编辑选项。</div>}
          <div className="inspector-bottom"><span className="status-dot"/> HUMAN-IN-CONTROL WORKFLOW</div>
          </>}
        </section>
      </div>}

      {draft&&active&&tree&&<div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="draft-title" tabIndex={-1} ref={modalRef}>
        <div className="modal-eyebrow"><span className="review-spark">✳</span> REVIEW BEFORE COMMIT <span className="modal-step">01 / 02</span></div>
        <h2 id="draft-title">导图草稿预览</h2>
        <p>{llmActive?<>模型根据原文提出了 <b>{draft.map.nodes.length}</b> 个候选节点。请逐条核对后再决定是否应用；当前正式地图保持不变。</>:<>本地规则引擎从原文提取了 <b>{draft.map.nodes.length}</b> 个节点。请确认结构是否合理；当前正式地图保持不变。</>}</p>
        <div className="review-caution"><span>{llmActive?'✳':'ⓘ'}</span> {llmActive?'候选内容由语言模型生成，可能包含错误或无法定位的引用，必须人工核对原文后才能采信。':'这是一份原文摘录草稿，不是经过核验的 AI 研究结论。'}{llmActive&&typeof draft.droppedEvidenceCount==='number'&&draft.droppedEvidenceCount>0?`（已丢弃 ${draft.droppedEvidenceCount} 条无法在原文中定位的引用）`:''}</div>
        <div className="modal-list-caption"><span>PROPOSED STRUCTURE</span><span>{draft.map.nodes.length} NODES</span></div>
        <div className="modal-items">{draft.map.nodes.slice(0,10).map(n=><div key={n.id} className="draft-row"><span className="draft-kind">{typeLabels[n.type]||n.type}</span><strong>{n.title.slice(0,110)}</strong></div>)}</div>
        <footer><button className="button button-quiet" onClick={()=>setDraft(null)}>取消</button><button className="button button-primary" disabled={busy}
          onClick={()=>void run(async()=>{await api.commitDraft(active.id,tree.revision,draft.draftId);setDraft(null);await reload();},'已确认并保存草稿')}>确认替换地图</button></footer>
      </div></div>}
      {patch&&active&&tree&&<div className="modal-backdrop"><div className="modal" role="dialog" aria-modal="true" aria-labelledby="patch-title" tabIndex={-1} ref={modalRef}>
        <div className="modal-eyebrow"><span className="review-spark">↗</span> CONTROLLED PATCH <span className="modal-step">02 / 02</span></div>
        <h2 id="patch-title">局部修改预览</h2>
        <p>候选修改不会直接写入地图。逐条选择你认可的内容，只有确认后才会创建新版本。</p>
        <div className="review-caution"><span>✓</span> 已保护：目标子树之外的节点、人工核验结论、当前已保存版本。</div>
        <div className="modal-list-caption"><span>PROPOSED CHANGES</span><span>{accepted.size} / {patch.proposedOps.length} SELECTED</span></div>
        <div className="modal-items">{patch.proposedOps.map(op=><label key={op.opId} className={`proposal-item ${accepted.has(op.opId)?'chosen':''}`}>
          <input type="checkbox" checked={accepted.has(op.opId)} onChange={e=>setAccepted(old=>{
            const next=new Set(old);e.target.checked?next.add(op.opId):next.delete(op.opId);return next;
          })}/><div><span className="diff-add">＋ 新增 · {typeLabels[op.node.type]||op.node.type}</span><strong>{op.node.title}</strong></div>
        </label>)}</div>
        <footer><span className="modal-revision">BASE REV {patch.baseRevision}</span><button className="button button-quiet" onClick={()=>setPatch(null)}>放弃建议</button>
          <button className="button button-primary" disabled={busy||accepted.size===0}
            onClick={()=>void run(async()=>{await api.applyPatch(active.id,tree.revision,patch.patchId,[...accepted]);setPatch(null);await reload();},'已原子应用选中的修改')}>确认应用 {accepted.size} 项</button></footer>
      </div></div>}
    </main>
  </div>;
}
