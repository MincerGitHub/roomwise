import {useEffect,useId,useRef,useState} from 'react';
import {ChevronDown,House,MessageSquare,Send,Sparkles} from 'lucide-react';

export type LayoutMessage={role:'user'|'assistant';text:string;warning?:boolean};
const examples=['衣柜不要动','桌子靠窗，椅子面朝窗户方向','床头柜放床头的右侧','床放在衣柜前面'];

type Props={
 draft:string;
 onDraft:(draft:string)=>void;
 onSend:(text?:string)=>void;
 busy:boolean;
 messages:LayoutMessage[];
 compact?:boolean;
};

export default function LayoutConversation({draft,onDraft,onSend,busy,messages,compact=false}:Props){
 const log=useRef<HTMLDivElement>(null),contentId=useId();
 const [expanded,setExpanded]=useState(false);
 useEffect(()=>{if(log.current)log.current.scrollTop=log.current.scrollHeight;},[messages,expanded]);
 function send(text?:string){setExpanded(true);onSend(text);}

 return <section className={'conversation'+(compact?' preview-conversation':'')} aria-label="历史记录" aria-busy={busy}>
  <div id={contentId} className="conversation-content" hidden={!expanded}>
   <div className="conversation-heading"><MessageSquare size={16}/><h3>历史记录</h3></div>
   {messages.length>0?<div className="messages" role="log" ref={log} tabIndex={0} aria-label="历史记录">{messages.slice(-4).map((message,i)=><div key={i} className={'message '+message.role+(message.warning?' warning':'')}>
    <span aria-hidden="true">{message.role==='assistant'?<Sparkles size={14}/>:<House size={14}/>}</span><p>{message.text}</p>
   </div>)}</div>:<p className="conversation-empty">暂无历史记录</p>}
   {!compact&&<div className="prompt-examples">{examples.map(text=><button key={text} disabled={busy} onClick={()=>send(text)}>{text}</button>)}</div>}
  </div>
  <div className="conversation-composer">
   <form className="command-box" onSubmit={event=>{event.preventDefault();send();}}>
    <input aria-label="输入修改要求" value={draft} onChange={event=>onDraft(event.target.value)} placeholder="例如：书桌靠窗"/>
    <button aria-label="发送要求" disabled={busy||!draft.trim()}><Send size={17}/></button>
   </form>
   <button type="button" className="btn conversation-toggle" aria-expanded={expanded} aria-controls={contentId} aria-label={expanded?'折叠历史记录':'展开历史记录'} onClick={()=>setExpanded(open=>!open)}>
    <span>历史记录</span><span>{expanded?'折叠':'展开'}</span><ChevronDown size={15} aria-hidden="true"/>
   </button>
  </div>
 </section>;
}
