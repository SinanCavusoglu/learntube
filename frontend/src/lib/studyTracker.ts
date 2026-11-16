import { API } from '@/lib/api'

type Kind = 'video' | 'vocabulary' | 'writing' | 'pdf' | 'podcast'
type Active = { kind:Kind; sourceId:number; lastWall:number; lastMonotonic:number; idleUntil:number; token:symbol }
const clientSessionId = crypto.randomUUID()
const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('learntube-study') : null
let active:Active|null = null
let interval:number|undefined

function send(item:Active, endWall:number, seconds:number, beacon=false) {
  const bounded=Math.floor(seconds*100)/100
  if (bounded <= 0) return
  const body = JSON.stringify({event_key:crypto.randomUUID(), client_session_id:clientSessionId, activity_type:item.kind, source_id:item.sourceId, ended_at:new Date(endWall).toISOString(), duration_seconds:bounded})
  if (beacon && navigator.sendBeacon) {
    navigator.sendBeacon(`${API}/api/dashboard/activity`, new Blob([body], {type:'application/json'}))
  } else {
    const post=(attempt:number)=>fetch(`${API}/api/dashboard/activity`, {method:'POST',headers:{'Content-Type':'application/json'},body,keepalive:true}).then(response=>{if(!response.ok&&response.status>=500&&attempt<2)window.setTimeout(()=>post(attempt+1),2000)}).catch(()=>{if(attempt<2)window.setTimeout(()=>post(attempt+1),2000)})
    void post(0)
  }
}

function pulse(beacon=false) {
  const item=active
  if (!item) return
  const now=performance.now(), wall=Date.now()
  const elapsed=Math.max(0,(now-item.lastMonotonic)/1000)
  const allowed=Math.min(elapsed, 10, Math.max(0,(item.idleUntil-item.lastWall)/1000))
  if (allowed > 0.05) {
    const endWall=Math.min(wall,item.idleUntil)
    send(item,endWall,allowed,beacon)
  }
  item.lastWall=wall
  item.lastMonotonic=now
  if (wall>=item.idleUntil) stop()
}

function stop(beacon=false) {
  if (!active) return
  pulseWithoutStop(beacon)
  active=null
  if (interval!==undefined) {clearInterval(interval);interval=undefined}
}

function pulseWithoutStop(beacon=false) {
  const item=active
  if (!item) return
  const now=performance.now(), wall=Date.now()
  const seconds=Math.min(Math.max(0,(now-item.lastMonotonic)/1000),10,Math.max(0,(item.idleUntil-item.lastWall)/1000))
  if (seconds>0.05) send(item,Math.min(wall,item.idleUntil),seconds,beacon)
  item.lastWall=wall;item.lastMonotonic=now
}

function begin(kind:Kind,sourceId:number,idleMs:number) {
  if ((document.hidden && kind!=='podcast') || (kind==='pdf'&&!document.hasFocus())) return Symbol()
  if (active?.kind===kind && active.sourceId===sourceId) {
    if(Date.now()>active.idleUntil) pulse()
  }
  if (active?.kind===kind && active.sourceId===sourceId) {
    active.idleUntil=Date.now()+idleMs
    return active.token
  }
  stop()
  channel?.postMessage('stop')
  const token=Symbol(), wall=Date.now()
  active={kind,sourceId,lastWall:wall,lastMonotonic:performance.now(),idleUntil:wall+idleMs,token}
  interval=window.setInterval(pulse,10000)
  return token
}

document.addEventListener('visibilitychange',()=>{if(document.hidden&&active?.kind!=='podcast')stop(true)})
window.addEventListener('pagehide',()=>stop(true))
window.addEventListener('blur',()=>{if(active?.kind==='pdf')stop(true)})
if(channel)channel.onmessage=()=>stop()

export const studyTracker = {
  video:(id:number)=>begin('video',id,24*60*60*1000),
  vocabulary:(id:number)=>begin('vocabulary',id,30000),
  writing:(id:number)=>begin('writing',id,20000),
  pdf:(id:number)=>begin('pdf',id,30000),
  podcast:(id:number)=>begin('podcast',id,30000),
  stop:(token?:symbol)=>{if(!token||active?.token===token)stop()},
}
