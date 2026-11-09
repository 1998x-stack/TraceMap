import { Handle, Position, type Node, type NodeProps } from '@xyflow/react';

export type ResearchNodeData = {
  title: string;
  kind: string;
  verified: boolean;
  origin: 'user' | 'ai';
  evidenceCount: number;
  anchoredCount: number;
  depth: number;
};
export type ResearchFlowNode = Node<ResearchNodeData, 'research'>;

const kinds: Record<string, {label:string; mark:string}> = {
  topic: {label:'研究主题',mark:'◉'},
  claim: {label:'核心主张',mark:'◆'},
  evidence: {label:'证据',mark:'▣'},
  counterpoint: {label:'反向观点',mark:'↔'},
  question: {label:'待探索',mark:'?'},
  decision: {label:'研究判断',mark:'✦'},
};

/** Pure presentation: no data editing or network calls inside the graph node. */
export default function ResearchNodeCard({ data, selected }:NodeProps<ResearchFlowNode>) {
  const { label,mark } = kinds[data.kind] ?? {label:'节点',mark:'•'};
  const verificationLabel = data.verified ? '人工已核验' : data.anchoredCount ? '证据可定位' : '尚待核验';
  return (
    <div className={`research-node kind-${data.kind} ${selected?'selected':''} ${data.verified?'verified':''}`}>
      <Handle type="target" position={Position.Left} className="research-handle" isConnectable={false} />
      <div className="research-node-top">
        <span className="node-kind"><span aria-hidden="true" className="node-kind-mark">{mark}</span>{label}</span>
        <span className="node-origin">{data.origin==='user'?'MANUAL':'EXTRACTED'}</span>
      </div>
      <div className="research-node-title">{data.title}</div>
      <div className="research-node-bottom">
        <span className={`node-evidence-state ${data.verified?'state-verified':data.anchoredCount?'state-anchored':'state-pending'}`}>
          <span className="status-dot" aria-hidden="true" /> {verificationLabel}
        </span>
        {data.evidenceCount>0&&<span className="node-ref-count" aria-label={`${data.evidenceCount} 条证据`}>▤ {data.evidenceCount}</span>}
      </div>
      <Handle type="source" position={Position.Right} className="research-handle" isConnectable={false} />
    </div>
  );
}
