import { lazy, Suspense, useCallback, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { writingApi, type WritingSession } from '@/lib/api'
import { buildWritingPrompt } from '@/lib/writingPrompt'
const SafeMarkdown=lazy(()=>import('@/components/SafeMarkdown').then(module=>({default:module.SafeMarkdown})))

const localKey=(id:number)=>`learntube-writing-feedback-${id}`
const readDraft=(id:number)=>{try{return localStorage.getItem(localKey(id))}catch{return null}}
const storeDraft=(id:number,value:string)=>{try{localStorage.setItem(localKey(id),value)}catch{/* Keep the editor value in memory. */}}
const clearDraft=(id:number)=>{try{localStorage.removeItem(localKey(id))}catch{/* The saved server copy is authoritative. */}}

export function WritingFeedback({session,question,essay}:{session:WritingSession;question:string;essay:string}){
  const client=useQueryClient()
  const [feedback,setFeedback]=useState(()=>readDraft(session.id)??session.chatgpt_feedback??'')
  const [status,setStatus]=useState<'Saved'|'Saving'|'Unsaved'|'Error'>(readDraft(session.id)!==null?'Unsaved':'Saved')
  const [copyStatus,setCopyStatus]=useState(''),[preview,setPreview]=useState(false),[saveTick,setSaveTick]=useState(0)
  const latest=useRef(feedback),revision=useRef(session.feedback_revision),pending=useRef<Promise<void>|null>(null),timer=useRef<number|undefined>(undefined),alive=useRef(true)
  const edit=(value:string)=>{latest.current=value;setFeedback(value);storeDraft(session.id,value);setStatus('Unsaved')}
  const save=useCallback(async()=>{
    if(pending.current)return pending.current
    const snapshot=latest.current
    let succeeded=false
    if(alive.current)setStatus('Saving')
    const task=writingApi.feedback(session.id,snapshot,revision.current).then(updated=>{
      succeeded=true
      revision.current=updated.feedback_revision
      if(latest.current===snapshot){clearDraft(session.id);if(alive.current)setStatus('Saved')}
      else if(alive.current)setStatus('Unsaved')
      void client.invalidateQueries({queryKey:['writing']})
    }).catch(()=>{if(alive.current)setStatus('Error')}).finally(()=>{pending.current=null;if(succeeded&&latest.current!==snapshot&&alive.current)setSaveTick(value=>value+1)})
    pending.current=task
    return task
  },[session.id,client])
  useEffect(()=>{if(status==='Unsaved'){clearTimeout(timer.current);timer.current=window.setTimeout(()=>{void save()},800)}return()=>clearTimeout(timer.current)},[feedback,status,save,saveTick])
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;clearTimeout(timer.current);if(readDraft(session.id)!==null)void save()}},[session.id,save])
  const copy=async()=>{
    try{await navigator.clipboard.writeText(buildWritingPrompt(session.task_type,question,essay));setCopyStatus('Copied. Paste into ChatGPT.')}catch{setCopyStatus('Could not copy. Check clipboard permission.')}
  }
  return <section className="mt-6 rounded-xl border border-white/10 bg-[#18191d] p-5">
    <div className="flex flex-wrap items-start justify-between gap-3"><div><h2 className="text-lg font-semibold">ChatGPT Feedback</h2><p className="mt-2 text-sm text-zinc-400">Copy your essay, evaluate it separately in ChatGPT, then paste the feedback here.</p></div><span role="status" className={`text-xs ${status==='Error'?'text-rose-300':status==='Saved'?'text-emerald-300':'text-amber-200'}`}>{status==='Error'?'Save failed. Draft kept locally.':status}</span></div>
    <button type="button" onClick={()=>void copy()} className="mt-4 rounded-md border border-white/15 px-3 py-2 text-sm hover:bg-white/5">Copy for ChatGPT</button>{copyStatus&&<p role="status" className="mt-2 text-xs text-zinc-400">{copyStatus}</p>}
    <div className="mt-5 flex gap-2 border-b border-white/10 pb-3 text-sm"><button type="button" onClick={()=>setPreview(false)} className={!preview?'text-indigo-300':'text-zinc-400'}>Edit</button><button type="button" onClick={()=>setPreview(true)} className={preview?'text-indigo-300':'text-zinc-400'}>Preview</button></div>
    {preview?<div className="min-h-64 py-4">{feedback?<Suspense fallback={<p className="text-sm text-zinc-400">Loading preview…</p>}><SafeMarkdown source={feedback}/></Suspense>:<p className="text-sm text-zinc-500">Paste feedback to preview it.</p>}</div>:<label className="mt-4 block text-sm">Paste or edit ChatGPT feedback<textarea value={feedback} onChange={event=>edit(event.target.value)} className="mt-2 min-h-80 w-full resize-y rounded-md border border-white/10 bg-black/20 p-4 text-sm leading-7 text-zinc-100 outline-none focus:border-indigo-300" placeholder="Paste feedback here…"/></label>}
    <button type="button" disabled={status==='Saved'||status==='Saving'} onClick={()=>{clearTimeout(timer.current);void save()}} className="mt-4 rounded-md bg-white px-4 py-2 text-sm font-medium text-zinc-950 disabled:opacity-40">Save Feedback</button>
  </section>
}
