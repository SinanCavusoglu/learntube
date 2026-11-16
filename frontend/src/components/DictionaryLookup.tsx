import { useCallback, useEffect, useRef, useState } from 'react'
import { dictionaryApi, type DictionaryResult } from '@/lib/api'

type Props = {
  text:string
  definition:string
  examples:string
  onFill:(definition:string,examples:string,oldDefinition:string,oldExamples:string)=>void
}

export function DictionaryLookup({text,definition,examples,onFill}:Props){
  const [result,setResult]=useState<DictionaryResult|null>(null),[selected,setSelected]=useState(0),[loading,setLoading]=useState(false),[error,setError]=useState('')
  const controller=useRef<AbortController|null>(null),requestId=useRef(0),lastApplied=useRef(''),active=useRef(true),latestWord=useRef('')
  latestWord.current=text.trim().replace(/\s+/g,' ')
  const lookup=useCallback(async()=>{
    const word=text.trim().replace(/\s+/g,' ')
    if(!word)return
    if((definition.trim()||examples.trim())&&!window.confirm('Replace existing definition and examples with dictionary results?'))return
    controller.current?.abort()
    const next=new AbortController(),id=++requestId.current
    controller.current=next
    setLoading(true);setError('');setResult(null)
    const oldDefinition=definition,oldExamples=examples
    try{
      const response=await dictionaryApi.lookup(word,next.signal)
      if(id!==requestId.current||next.signal.aborted||!active.current||latestWord.current!==word)return
      setResult(response);setSelected(0)
      const first=response.definitions[0]?.definition
      if(!first){setError('No dictionary definition found.');return}
      lastApplied.current=first
      onFill(first,response.examples.slice(0,3).join('\n'),oldDefinition,oldExamples)
    }catch(cause){
      if(id!==requestId.current||next.signal.aborted||!active.current||latestWord.current!==word)return
      const message=cause instanceof Error?cause.message:'Dictionary lookup failed.'
      setError(message)
    }finally{if(id===requestId.current)setLoading(false)}
  },[text,definition,examples,onFill])
  useEffect(()=>{controller.current?.abort();requestId.current++;setLoading(false);setResult(null);setError('')},[text])
  useEffect(()=>{active.current=true;return()=>{active.current=false;controller.current?.abort();requestId.current++}},[])
  const choose=(index:number)=>{
    const next=result?.definitions[index]?.definition
    if(!next)return
    if(definition.trim()&&definition!==lastApplied.current&&!window.confirm('Replace your edited definition with this dictionary definition?'))return
    setSelected(index);lastApplied.current=next
    onFill(next,examples,definition,examples)
  }
  return <div className="space-y-2 text-xs"><div className="flex flex-wrap items-center gap-2"><button type="button" disabled={!text.trim()||loading} onClick={()=>void lookup()} className="rounded border border-indigo-300/30 px-3 py-2 text-indigo-200 disabled:opacity-40">{loading?'Looking up…':'Free Dictionary'}</button>{loading&&<span role="status" className="text-zinc-400">Checking dictionary…</span>}</div>{error&&<p role="alert" className="text-amber-200">{error} You can still enter your own definition and save.</p>}{result&&result.definitions.length>1&&<label className="flex items-center gap-2 text-zinc-400">Meaning<select aria-label="Choose dictionary definition" value={selected} onChange={event=>choose(Number(event.target.value))} className="min-w-0 max-w-full flex-1 rounded border border-white/10 bg-[#202126] px-2 py-1.5 text-zinc-100">{result.definitions.map((item,index)=><option key={`${index}:${item.definition}`} value={index}>{item.part_of_speech?`${item.part_of_speech}: `:''}{item.definition}</option>)}</select></label>}</div>
}
