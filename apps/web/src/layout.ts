import type { MapNode, MapDocument } from './api';
import type { Node, Edge } from '@xyflow/react';

/** Deterministic horizontal tree layout. React Flow is a renderer, not a source of truth. */
export function layout(tree: MapDocument): {nodes:Node[];edges:Edge[]} {
  const byParent=new Map<string,MapNode[]>();
  for(const node of tree.nodes){if(node.parentId){const list=byParent.get(node.parentId)||[];list.push(node);byParent.set(node.parentId,list);}}
  for(const list of byParent.values())list.sort((a,b)=>a.sortOrder-b.sortOrder||a.id.localeCompare(b.id));
  const positions=new Map<string,{x:number;y:number}>();let leaf=0;
  const walk=(id:string,depth:number):number=>{
    const children=byParent.get(id)||[];
    const y=children.length? (walk(children[0].id,depth+1)+(children.length>1?children.slice(1).reduce((sum,child)=>sum+walk(child.id,depth+1),0):0))/(children.length) : leaf++*132;
    positions.set(id,{x:depth*340,y});return y;
  };
  walk(tree.rootId,0);
  const nodes:Node[]=tree.nodes.map(n=>({id:n.id,position:positions.get(n.id)||{x:0,y:0},draggable:false,
    data:{label:n.title,type:n.type,verified:n.verification==='verified_by_user',origin:n.origin,refs:n.evidenceRefs.length},
    type:'default',className:`map-node kind-${n.type} ${n.verification==='verified_by_user'?'is-verified':''}`}));
  const edges:Edge[]=tree.nodes.filter(n=>n.parentId).map(n=>({id:`e-${n.id}`,source:n.parentId!,target:n.id,type:'smoothstep',animated:false,style:{stroke:'#7f91af',strokeWidth:1.5}}));
  return {nodes,edges};
}

/** Python uses Unicode codepoint offsets while JS string offsets use UTF-16 units. */
export function sliceCodepoints(text:string,start:number,end:number):[string,string,string]{
  const chars=Array.from(text);return [chars.slice(0,start).join(''),chars.slice(start,end).join(''),chars.slice(end).join('')];
}
