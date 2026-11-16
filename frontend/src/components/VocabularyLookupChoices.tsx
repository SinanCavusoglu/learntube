import { DictionaryLookup } from '@/components/DictionaryLookup'
import { VocabularyAIFill } from '@/components/VocabularyAIFill'

type Props = {
  text:string
  definition:string
  examples:string
  onFill:(definition:string,examples:string,oldDefinition:string,oldExamples:string)=>void
}

export function VocabularyLookupChoices(props:Props){
  return <div className="space-y-2"><p className="text-xs text-zinc-400">Fill from (optional)</p><div className="flex flex-wrap items-start gap-3"><DictionaryLookup {...props}/><VocabularyAIFill {...props}/></div></div>
}
