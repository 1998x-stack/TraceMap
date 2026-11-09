import {useEffect,useState} from 'react';

export type GenerationPhase = 'waiting' | 'reading';

type Props = {
  phase: GenerationPhase;
  mode: 'llm' | 'extractive';
  sourceCount: number;
  startedAt: number;
};

function clock(totalSeconds:number):string {
  const minutes=Math.floor(totalSeconds/60).toString().padStart(2,'0');
  const seconds=(totalSeconds%60).toString().padStart(2,'0');
  return minutes+':'+seconds;
}

/** An honest, non-percent status panel for the synchronous /generate API.
 *
 * The backend currently does not stream or persist progress events. We display
 * elapsed wall time and transitions that the *browser has actually observed*,
 * never invented parsing/model percentage or fabricated internal milestones.
 */
export default function GenerationProgress({phase,mode,sourceCount,startedAt}:Props){
  const [elapsed,setElapsed]=useState(0);
  useEffect(()=>{
    const update=()=>setElapsed(Math.max(0,Math.floor((Date.now()-startedAt)/1000)));
    update();
    const id=window.setInterval(update,1000);
    return()=>window.clearInterval(id);
  },[startedAt]);

  const waiting=phase==='waiting';
  const isLLM=mode==='llm';
  const steps=[
    {label:'请求已发起',state:'complete'},
    {label:isLLM?'等待模型响应':'等待结构生成',state:waiting?'current':'complete'},
    {label:'读取候选草稿',state:waiting?'upcoming':'current'},
  ] as const;

  return <section className="generation-progress" role="status" aria-label="生成进度" aria-live="off" aria-busy={waiting}>
    <div className="generation-progress-head">
      <div>
        <div className="generation-kicker">RESEARCH PROCESS · {isLLM?'MODEL-ASSISTED':'EXTRACTIVE'}</div>
        <h3>候选导图正在生成<span className="generation-loading-mark" aria-hidden="true">…</span></h3>
        <p>已选择 {sourceCount} 份资料 · {isLLM?'正在等待模型生成有出处的候选结构':'使用本地规则整理原文结构'}</p>
      </div>
      <div className="generation-time">
        <span>已等待</span>
        <strong aria-hidden="true" className="generation-timer">{clock(elapsed)}</strong>
        <span className="sr-only">{elapsed} 秒</span>
      </div>
    </div>
    <div className="generation-track" aria-hidden="true"><span/></div>
    <ol className="generation-steps" aria-label="当前生成阶段">
      {steps.map((step,index)=><li key={index} className={'generation-step '+step.state}>
        <span className="generation-step-mark" aria-hidden="true">{step.state==='complete'?'✓':String(index+1).padStart(2,'0')}</span>
        <span>{step.label}</span>
      </li>)}
    </ol>
    <div className="generation-progress-bottom">
      <p aria-live="polite">{waiting?
        (elapsed>=90?'处理时间较长，仍在等待服务器响应；如遇失败，错误将显示在页面上。':
         elapsed>=20?'模型生成可能持续数十秒，请勿重复提交或刷新页面。':
         '请求正在处理，候选草稿生成前不会修改已保存的导图。'):
         '服务端已返回结果，正在读取候选草稿供你审阅。'}</p>
      <small>同步请求 · 暂无服务端逐步进度；计时不是完成百分比</small>
    </div>
  </section>;
}
