import type { MapNode, MapDocument } from './api';
import type { Edge } from '@xyflow/react';
import type { ResearchFlowNode } from './components/ResearchNode';

/** Deterministic, stable horizontal tree layout; source of truth stays on the server. */
export function layout(tree: MapDocument): { nodes: ResearchFlowNode[]; edges: Edge[] } {
  const byParent = new Map<string,MapNode[]>();
  for (const item of tree.nodes) {
    if (!item.parentId) continue;
    const list = byParent.get(item.parentId) ?? [];
    list.push(item);
    byParent.set(item.parentId,list);
  }
  for (const children of byParent.values()) {
    children.sort((a,b)=>a.sortOrder-b.sortOrder || a.id.localeCompare(b.id));
  }
  const positions = new Map<string,{x:number;y:number;depth:number}>();
  let leafIndex = 0;
  const walk = (id:string,depth:number):number => {
    const children=byParent.get(id)??[];
    // Center a parent between its first and last descendant instead of averaging
    // a skewed subtree by its immediate child count.
    let y:number;
    if(children.length===0){y=leafIndex*156;leafIndex++;}
    else {
      const centers=children.map(child=>walk(child.id,depth+1));
      y=(centers[0]+centers[centers.length-1])/2;
    }
    positions.set(id,{x:depth*368,y,depth});
    return y;
  };
  walk(tree.rootId,0);
  const nodes:ResearchFlowNode[] = tree.nodes.map(node => {
    const position=positions.get(node.id)??{x:0,y:0,depth:0};
    return {
      id:node.id,position:{x:position.x,y:position.y},type:'research',
      draggable:false,connectable:false,selectable:true,
      data:{
        title:node.title,kind:node.type,verified:node.verification==='verified_by_user',
        origin:node.origin,evidenceCount:node.evidenceRefs.length,
        anchoredCount:node.evidenceRefs.filter(ref=>ref.anchorStatus==='anchored').length,
        depth:position.depth,
      },
    };
  });
  const edges:Edge[] = tree.nodes.filter(n=>n.parentId).map(n=>({
    id:`edge-${n.id}`,source:n.parentId!,target:n.id,type:'smoothstep',
    animated:false,style:{stroke:'#7e9bb2',strokeWidth:1.6},
  }));
  return {nodes,edges};
}

/** Python uses Unicode codepoint offsets; JS string indices use UTF-16 code units. */
export function sliceCodepoints(text:string,start:number,end:number):[string,string,string]{
  const chars=Array.from(text);
  return [chars.slice(0,start).join(''),chars.slice(start,end).join(''),chars.slice(end).join('')];
}
