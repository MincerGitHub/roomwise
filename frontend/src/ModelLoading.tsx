import type {ModelState} from './furnitureObjects';
import './modelLoading.css';

export default function ModelLoading({states,retry}:{states:ModelState[];retry:()=>void}){
 const pending=states.filter(state=>state.status==='loading'),failed=states.filter(state=>state.status==='error');
 if(!pending.length&&!failed.length)return null;
 return <div className="model-loading">
  {!!pending.length&&<p role="status">正在加载家具模型（{pending.length}件）…</p>}
  {!!failed.length&&<div role="alert"><p>模型加载失败：{failed.map(state=>state.label).join('、')}</p><button onClick={retry}>重新加载模型</button></div>}
 </div>;
}
