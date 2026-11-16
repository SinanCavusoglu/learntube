import { useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { aiApi } from '@/lib/api'

type Props = {
  text: string
  definition: string
  examples: string
  onFill: (definition: string, examples: string, capturedDefinition: string, capturedExamples: string) => void
}

export function VocabularyAIFill({text, definition, examples, onFill}: Props) {
  const status = useQuery({queryKey:['aiStatus'],queryFn:aiApi.status,staleTime:30_000})
  const dailyLimitReached = status.data?.daily_limit != null && status.data?.used_today != null && status.data.used_today >= status.data.daily_limit
  const [generated,setGenerated] = useState(false)
  const current = useRef({text,definition,examples,onFill})
  current.current = {text,definition,examples,onFill}
  const fill = useMutation({mutationFn: async () => {
    const captured = {...current.current}
    const result = await aiApi.vocabulary(text.trim().slice(0,500))
    return {result,captured}
  },onSuccess:({result,captured}) => {
    if(current.current.text !== captured.text) return
    current.current.onFill(result.definition,result.examples.join('\n'),captured.definition,captured.examples)
    setGenerated(true)
  }})
  const generate = () => {
    if(fill.isPending || !text.trim()) return
    if((definition.trim() || examples.trim()) && !window.confirm('Replace the current definition and examples with new AI suggestions?')) return
    fill.mutate()
  }
  return <div className="space-y-1 text-xs"><button type="button" disabled={!status.data?.enabled || dailyLimitReached || fill.isPending || !text.trim()} onClick={generate} className="rounded border border-indigo-300/30 px-3 py-2 text-indigo-200 disabled:opacity-40">{fill.isPending?'Generating…':generated?'Regenerate with Gemini':'Gemini'}</button>{fill.isPending&&<span role="status" className="ml-2 text-zinc-400">Creating suggestions…</span>}{fill.error&&<p role="alert" className="text-rose-300">{fill.error.message} You can still fill the fields manually.</p>}{generated&&<p className="text-zinc-500">Gemini suggestions are editable. Save when ready.</p>}{dailyLimitReached&&<p className="text-zinc-500">Daily Gemini limit reached ({status.data?.used_today}/{status.data?.daily_limit}). Resets at 00:00 UTC.</p>}{!status.isLoading&&!status.data?.enabled&&<p className="text-zinc-500">Gemini is unavailable; manual entry still works.</p>}</div>
}
