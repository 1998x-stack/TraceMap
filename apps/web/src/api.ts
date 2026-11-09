export type EvidenceRef = { sourceId: string; paragraphId: string; start: number; end: number; exactQuote: string; quoteSha256?: string; anchorStatus: 'anchored'|'invalid'|'unverified'|'source_deleted' };
export type MapNode = { id: string; parentId: string|null; type: string; title: string; note?: string; origin: 'user'|'ai'; verification: 'unverified'|'verified_by_user'; evidenceRefs: EvidenceRef[]; sortOrder: number };
export type MapDocument = { revision: number; rootId: string; nodes: MapNode[] };
export type Project = { id: string; title: string; goal: string; revision: number; createdAt: string; updatedAt: string };
export type Source = { id: string; title: string; kind: string; status: string; extractedCharCount: number };
export type Paragraph = { id: string; text: string; sourceId: string; pageNo: number|null; ordinal: number };
export type PatchProposal = { patchId: string; baseRevision: number; status: string; operation: string; generationMode: string; proposedOps: ({opId:string;op:string;parentId:string;node:{title:string;type:string}})[] };
export type GenerationDraft = { draftId: string; baseRevision: number; status: string; generationMode: string; selectionPolicy?: string; provider?: { api: string; model: string }; usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number }; droppedEvidenceCount?: number; map: Omit<MapDocument,'revision'> };
export type Health = { status: string; mode: string; generationProvider: string; generationModel: string | null; llmConfigured: boolean };
export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}
/**
 * RFC 4122 v4 identifier.
 *
 * ``crypto.randomUUID`` is only defined in a browser *secure context*, so a
 * plain-HTTP origin (e.g. a LAN IP like http://192.168.1.10:5173) throws
 * "crypto.randomUUID is not a function" on every write. ``crypto.getRandomValues``
 * is available in insecure contexts, so fall back to it (see gotchas GT-0021).
 */
export function newId(): string {
  const c: Crypto | undefined = globalThis.crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  const bytes = new Uint8Array(16);
  if (c && typeof c.getRandomValues === 'function') c.getRandomValues(bytes);
  else for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  bytes[6] = (bytes[6] & 0x0f) | 0x40; // version 4
  bytes[8] = (bytes[8] & 0x3f) | 0x80; // variant 10xx
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
const key = () => newId();
export class Api {
  constructor(private user: string = 'dev-alice') {}
  private auth(): Record<string,string> { return {Authorization:`Bearer ${this.user}`}; }
  async call<T>(path: string, method='GET', body?: unknown, revision?: number): Promise<T> {
    const headers: Record<string,string> = {...this.auth()};
    if (method!=='GET') { headers['Idempotency-Key']=key(); if(revision!==undefined)headers['If-Match']=`"rev-${revision}"`; }
    if(body!==undefined) headers['Content-Type']='application/json';
    const res=await fetch('/api/v1'+path,{method,headers,body:body!==undefined?JSON.stringify(body):undefined});
    if(!res.ok){const msg=await res.json().catch(()=>({}));throw new ApiError(msg.error?.code||'REQUEST_FAILED',msg.error?.message||`HTTP ${res.status}`,res.status);}
    return res.json() as Promise<T>;
  }
  listProjects() { return this.call<{items:Project[]}>('/projects'); }
  async health(): Promise<Health> {
    const res = await fetch('/health');
    if (!res.ok) throw new ApiError('HEALTH_FAILED', `HTTP ${res.status}`, res.status);
    return await res.json() as Health;
  }
  createProject(title:string,goal:string) { return this.call<Project>('/projects','POST',{title,goal}); }
  project(id:string) { return this.call<Project>(`/projects/${id}`); }
  map(id:string) { return this.call<MapDocument>(`/projects/${id}/map`); }
  sources(id:string) { return this.call<{items:Source[]}>(`/projects/${id}/sources`); }
  paragraphs(pid:string,sid:string) {return this.call<{items:Paragraph[]}>(`/projects/${pid}/sources/${sid}/paragraphs`);}
  addText(pid:string,revision:number,title:string,text:string) {return this.call<{revision:number;sourceId:string}>(`/projects/${pid}/sources/text`,'POST',{title,text,format:'text'},revision);}
  async upload(pid:string,revision:number,file:File) {
    const form=new FormData();form.append('file',file);
    const res=await fetch(`/api/v1/projects/${pid}/sources`,{method:'POST',headers:{...this.auth() as Record<string,string>, 'If-Match':`"rev-${revision}"`,'Idempotency-Key':key()},body:form});
    if(!res.ok){const msg=await res.json().catch(()=>({}));throw new ApiError(msg.error?.code||'REQUEST_FAILED',msg.error?.message||`HTTP ${res.status}`,res.status);}
    return res.json() as Promise<{revision:number;sourceId:string}>;
  }
  edit(pid:string,revision:number,ops:unknown[]) { return this.call<{revision:number}>(`/projects/${pid}/nodes/ops`,'POST',{operations:ops},revision); }
  generate(pid:string,revision:number,goal:string,sourceIds:string[]) {return this.call<{draftId:string;generationMode:string}>(`/projects/${pid}/generate`,'POST',{goal,sourceIds,language:'zh-CN'},revision);}
  getDraft(pid:string,did:string) {return this.call<GenerationDraft>(`/projects/${pid}/generation-drafts/${did}`);}
  commitDraft(pid:string,revision:number,did:string) {return this.call<{revision:number}>(`/projects/${pid}/generation-drafts/${did}/commit`,'POST',{},revision);}
  propose(pid:string,revision:number,targetNodeId:string,operation:string) {return this.call<{patchId:string}>(`/projects/${pid}/patches`,'POST',{targetNodeId,baseRevision:revision,operation});}
  getPatch(pid:string,patchId:string) {return this.call<PatchProposal>(`/projects/${pid}/patches/${patchId}`);}
  applyPatch(pid:string,revision:number,patchId:string,acceptedOpIds:string[]) {return this.call<{revision:number}>(`/projects/${pid}/patches/${patchId}/apply`,'POST',{acceptedOpIds},revision);}
  undo(pid:string,revision:number) {return this.call<{revision:number}>(`/projects/${pid}/undo`,'POST',{},revision);}
  async download(pid:string,format:'md'|'json') {
    const res=await fetch(`/api/v1/projects/${pid}/export?format=${format}`,{headers:this.auth()});
    if(!res.ok)throw new ApiError('EXPORT_FAILED',`导出失败 (${res.status})`,res.status);
    const blob=await res.blob();const url=URL.createObjectURL(blob);
    const anchor=document.createElement('a');anchor.href=url;anchor.download=`tracemap.${format}`;anchor.click();
    URL.revokeObjectURL(url);
  }
}
