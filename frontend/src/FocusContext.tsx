import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { focusApi, type FocusPhase, type FocusSession, type FocusSettings, type FocusTask } from '@/lib/api'
import { elapsedSeconds, interrupted, remainingSeconds } from '@/lib/focusClock'
import { localISO } from '@/lib/plannerDates'

type Controller = {
  session:FocusSession|null; settings:FocusSettings|null; phase:FocusPhase; selectedTask:FocusTask|null
  remaining:number; busy:boolean; readOnly:boolean; message:string; error:string
  selectTask:(task:FocusTask|null)=>void; setPhase:(phase:FocusPhase)=>void
  start:(phase?:FocusPhase,task?:FocusTask|null)=>Promise<void>; pause:()=>Promise<void>; resume:()=>Promise<void>
  stop:(confirmed?:boolean)=>Promise<boolean>; reset:()=>Promise<void>; saveSettings:(value:FocusSettings)=>Promise<void>
  clearMessage:()=>void
}
const Context=createContext<Controller|null>(null)
const snapshotKey='learntube-focus-snapshot',leaseKey='learntube-focus-lease'
const leaseTimeoutMs=90_000
type Snapshot={id:string;verified:number;at:number}
type Anchor={base:number;started:number;lastWall:number;lastMono:number}
const timezone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone||'UTC'
const defaultSettings:FocusSettings={focus_minutes:30,short_break_minutes:5,long_break_minutes:15,long_break_after:4,auto_start_breaks:false,auto_start_focus:false,notification_sound:true,browser_notifications:false,ticking_sound:false}
let audio:AudioContext|null=null
function tone(frequency:number,duration:number,volume:number){
  try{audio??=new AudioContext();void audio.resume();const oscillator=audio.createOscillator(),gain=audio.createGain();oscillator.connect(gain);gain.connect(audio.destination);gain.gain.value=volume;oscillator.frequency.value=frequency;oscillator.start();oscillator.stop(audio.currentTime+duration)}catch{}
}

function safeRead<T>(key:string):T|null{try{return JSON.parse(localStorage.getItem(key)||'null') as T}catch{return null}}
function safeWrite(key:string,value:unknown){try{localStorage.setItem(key,JSON.stringify(value))}catch{}}
function safeRemove(key:string){try{localStorage.removeItem(key)}catch{}}
function notify(title:string,settings:FocusSettings){
  if(settings.notification_sound)tone(740,0.2,0.08)
  if(settings.browser_notifications&&'Notification' in window&&Notification.permission==='granted')new Notification(title)
}

export function FocusProvider({children}:{children:ReactNode}){
  const client=useQueryClient()
  const location=useLocation()
  const [session,setSession]=useState<FocusSession|null>(null),[settings,setSettings]=useState<FocusSettings|null>(null)
  const [phase,setPhaseState]=useState<FocusPhase>('focus'),[selectedTask,setSelectedTask]=useState<FocusTask|null>(null)
  const [displayElapsed,setDisplayElapsed]=useState(0),[busy,setBusy]=useState(false),[readOnly,setReadOnly]=useState(false)
  const [message,setMessage]=useState(''),[error,setError]=useState('')
  const sessionRef=useRef<FocusSession|null>(null),anchor=useRef<Anchor|null>(null),busyRef=useRef(false),readOnlyRef=useRef(false)
  const lastTickSound=useRef(-1)
  const [controllerId]=useState(()=>crypto.randomUUID())
  const updateSession=(next:FocusSession|null)=>{sessionRef.current=next;setSession(next)}
  const lease=()=>safeRead<{owner:string;at:number}>(leaseKey)
  const ownLease=()=>{const current=lease();return !current||current.owner===controllerId||Date.now()-current.at>leaseTimeoutMs}
  const claim=()=>{if(!ownLease()){readOnlyRef.current=true;setReadOnly(true);return false}safeWrite(leaseKey,{owner:controllerId,at:Date.now()});readOnlyRef.current=false;setReadOnly(false);return true}
  const currentElapsed=()=>{const row=sessionRef.current,a=anchor.current;return row&&a&&row.status==='running'?Math.min(row.target_seconds,elapsedSeconds(a.base,a.started,performance.now())):row?.verified_seconds??0}
  const clearActive=()=>{updateSession(null);anchor.current=null;setDisplayElapsed(0);safeRemove(snapshotKey);if(lease()?.owner===controllerId)safeRemove(leaseKey)}
  const invalidate=()=>{void client.invalidateQueries({queryKey:['focus']});void client.invalidateQueries({queryKey:['planner']});void client.invalidateQueries({queryKey:['planner-upcoming']})}
  const act=async(action:'checkpoint'|'pause'|'resume'|'complete'|'stop',verified?:number)=>{
    const row=sessionRef.current
    if(!row||busyRef.current||readOnlyRef.current)return null
    busyRef.current=true;setBusy(true);setError('')
    try{
      const next=await focusApi.action(row.id,action,row.revision,verified??currentElapsed())
      if(next.status==='completed'||next.status==='stopped')clearActive()
      else{updateSession(next);if(action!=='checkpoint')setDisplayElapsed(next.verified_seconds);if(next.status==='paused')anchor.current=null;else if(action==='resume')anchor.current={base:next.verified_seconds,started:performance.now(),lastWall:Date.now(),lastMono:performance.now()}}
      invalidate()
      return next
    }catch(cause){
      setError(cause instanceof Error?cause.message:'Timer action failed.')
      try{
        const fresh=await focusApi.active()
        if(!fresh){clearActive();setMessage('Timer ended. Check Focus statistics for a completed session.')}
        else if(fresh.id===row.id&&fresh.status==='running'){
          updateSession(fresh)
          // A missed checkpoint response must not freeze a still-running timer.
          if(anchor.current)setDisplayElapsed(currentElapsed())
          setMessage('Timer sync was interrupted; the countdown is continuing.')
        }else{updateSession(fresh);anchor.current=null;setMessage('Timer state changed. Resume when ready.')}
      }catch{setMessage('Connection interrupted; countdown continues and will retry syncing.')}
      return null
    }
    finally{busyRef.current=false;setBusy(false)}
  }
  const start=async(nextPhase:FocusPhase=phase,task:FocusTask|null=selectedTask)=>{
    if(sessionRef.current||busyRef.current||!claim())return
    busyRef.current=true;setBusy(true);setError('')
    try{
      const row=await focusApi.start(crypto.randomUUID(),nextPhase,task)
      updateSession(row);setPhaseState(nextPhase)
      setDisplayElapsed(row.verified_seconds)
      const now=performance.now();anchor.current={base:row.verified_seconds,started:now,lastWall:Date.now(),lastMono:now}
      safeWrite(snapshotKey,{id:row.id,verified:row.verified_seconds,at:Date.now()})
      setMessage('');invalidate()
    }catch(cause){setError(cause instanceof Error?cause.message:'Could not start timer.');const fresh=await focusApi.active().catch(()=>null);if(fresh){updateSession(fresh);anchor.current=null;setMessage('Another timer is active. Resume it to continue.')}}
    finally{busyRef.current=false;setBusy(false)}
  }
  const pause=async()=>{await act('pause')}
  const resume=async()=>{if(sessionRef.current?.status==='paused'){const next=await act('resume');if(next)setMessage('')}}
  const stop=async(confirmed=false)=>{const row=sessionRef.current;if(!row)return false;if(!confirmed&&row.phase==='focus'&&currentElapsed()>60&&!window.confirm('Stop this focus session? It will not count as a completed Pomodoro.'))return false;const stopped=await act('stop');if(stopped)setMessage('Session stopped.');return !!stopped}
  const reset=async()=>{if(sessionRef.current){const row=sessionRef.current;if(row.phase==='focus'&&currentElapsed()>60&&!window.confirm('Reset this focus session? Progress will not count.'))return;if(!await act('stop'))return}setMessage('Timer reset.')}
  const changePhase=(next:FocusPhase)=>{if(sessionRef.current)return;setPhaseState(next);setMessage('')}
  const saveSettings=async(value:FocusSettings)=>{const saved=await focusApi.saveSettings(value);setSettings(saved);setMessage('Timer settings saved.');invalidate()}

  useEffect(()=>()=>{if(audio){void audio.close();audio=null}},[])
  useEffect(()=>{const unload=()=>{const row=sessionRef.current;if(row?.status==='running'&&anchor.current)safeWrite(snapshotKey,{id:row.id,verified:currentElapsed(),at:Date.now()});if(lease()?.owner===controllerId)safeRemove(leaseKey)};window.addEventListener('pagehide',unload);return()=>window.removeEventListener('pagehide',unload)},[controllerId])

  useEffect(()=>{let cancelled=false;const boot=async()=>{
    try{
      const [prefs,active]=await Promise.all([focusApi.settings(),focusApi.active()])
      if(cancelled)return
      setSettings(prefs)
      if(!active)return
      updateSession(active);setPhaseState(active.phase);setDisplayElapsed(active.verified_seconds)
      if(active.task_plan_id&&active.task_date&&active.task_occurrence_date){
        void focusApi.tasks(active.task_date).then(rows=>{
          if(cancelled)return
          const task=rows.find(row=>row.plan_id===active.task_plan_id&&row.occurrence_date===active.task_occurrence_date)
          if(task)setSelectedTask(task)
        }).catch(()=>undefined)
      }
      if(!claim())return
      if(active.status==='paused')return
      const snapshot=safeRead<Snapshot>(snapshotKey)
      if(snapshot?.id===active.id&&Date.now()-snapshot.at<=10_000&&snapshot.verified<active.target_seconds){
        const now=performance.now();anchor.current={base:Math.max(active.verified_seconds,snapshot.verified),started:now,lastWall:Date.now(),lastMono:now}
        setDisplayElapsed(anchor.current.base)
      }else{
        const verified=snapshot?.id===active.id?Math.max(active.verified_seconds,snapshot.verified):active.verified_seconds
        try{const paused=await focusApi.action(active.id,'pause',active.revision,Math.min(verified,active.target_seconds));if(!cancelled){updateSession(paused);setMessage('Timer paused after the page was closed or inactive. Resume when ready.')}}
        catch{if(!cancelled)setMessage('Timer recovery needs attention. Refresh or stop the session.')}
      }
    }catch(cause){if(!cancelled)setError(cause instanceof Error?cause.message:'Focus timer could not load.')}
  };void boot();return()=>{cancelled=true}},[])

  useEffect(()=>{if(!session)return;const timer=window.setInterval(()=>{
    const row=sessionRef.current
    if(!row)return
    if(readOnlyRef.current){const remote=safeRead<Snapshot>(snapshotKey);setDisplayElapsed(remote?.id===row.id&&Date.now()-remote.at<leaseTimeoutMs?remote.verified+(Date.now()-remote.at)/1000:row.verified_seconds);if(ownLease()){claim();void focusApi.active().then(fresh=>{if(fresh){updateSession(fresh);if(fresh.status==='running')void act('pause',fresh.verified_seconds).then(paused=>{if(paused)setMessage('Previous tab stopped responding. Timer paused to protect your progress. Resume when ready.')})}else clearActive()}).catch(()=>undefined)}return}
    safeWrite(leaseKey,{owner:controllerId,at:Date.now()})
    if(row.status!=='running'||!anchor.current)return
    const a=anchor.current,wall=Date.now(),mono=performance.now()
    if(interrupted(a.lastWall,a.lastMono,wall,mono)){
      const safe=Math.min(row.target_seconds,elapsedSeconds(a.base,a.started,a.lastMono))
      void act('pause',safe).then(paused=>{if(paused)setMessage('Computer sleep or a system clock change was detected. Timer paused; resume when ready.')})
      return
    }
    a.lastWall=wall;a.lastMono=mono
    const verified=Math.min(row.target_seconds,elapsedSeconds(a.base,a.started,mono))
    if(settings?.ticking_sound&&Math.floor(verified)!==lastTickSound.current){lastTickSound.current=Math.floor(verified);tone(420,0.025,0.012)}
    safeWrite(snapshotKey,{id:row.id,verified,at:wall})
    setDisplayElapsed(verified)
    if(verified>=row.target_seconds){
      void act('complete',row.target_seconds).then(async completed=>{
        if(!completed)return
        const prefs=settings??defaultSettings
        const title=completed.phase==='focus'?'Pomodoro completed!':'Break finished. Ready to focus?'
        setMessage(title);notify(title,prefs)
        let next:FocusPhase='focus'
        if(completed.phase==='focus'){
          const summary=await focusApi.stats(localISO(new Date()),timezone()).catch(()=>null)
          next=summary&&summary.completed_total%prefs.long_break_after===0?'long_break':'short_break'
        }
        setPhaseState(next)
        if((completed.phase==='focus'&&prefs.auto_start_breaks)||(completed.phase!=='focus'&&prefs.auto_start_focus))
          window.setTimeout(()=>void start(next,selectedTask),0)
      })
    }else if(Math.floor(verified/10)>Math.floor(row.verified_seconds/10)&&!busyRef.current){
      void act('checkpoint',verified)
    }
  },500);return()=>clearInterval(timer)},[session,settings,selectedTask])

  const preview=phase==='focus'?(selectedTask?.focus_minutes??settings?.focus_minutes??30):phase==='short_break'?(selectedTask?.short_break_minutes??settings?.short_break_minutes??5):(selectedTask?.long_break_minutes??settings?.long_break_minutes??15)
  const remaining=session?remainingSeconds(session.target_seconds,displayElapsed):preview*60
  return <Context.Provider value={{session,settings,phase,selectedTask,remaining,busy,readOnly,message,error,selectTask:setSelectedTask,setPhase:changePhase,start,pause,resume,stop,reset,saveSettings,clearMessage:()=>setMessage('')}}>{children}{message&&location.pathname!=='/focus'&&<div role="status" className="fixed bottom-4 right-4 z-[120] flex max-w-sm items-center gap-3 rounded-xl border border-indigo-300/30 bg-[#18191d] px-4 py-3 text-sm text-zinc-100 shadow-2xl"><span>{message}</span><button type="button" aria-label="Dismiss focus notification" onClick={()=>setMessage('')} className="text-zinc-400 hover:text-white">×</button></div>}</Context.Provider>
}

export function useFocus(){const value=useContext(Context);if(!value)throw new Error('FocusProvider missing');return value}
