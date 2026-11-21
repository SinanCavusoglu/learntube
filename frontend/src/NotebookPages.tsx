import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { BookOpenText, Pin, Plus, Search, Trash2 } from 'lucide-react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, notebookApi, type NotebookDraft, type NotebookNote } from '@/lib/api'
import { VocabularyLookupChoices } from '@/components/VocabularyLookupChoices'
import { SafeMarkdown } from '@/components/SafeMarkdown'

const panel = 'rounded-xl border border-white/10 bg-[#18191d]'
const input = 'w-full rounded-md border border-white/10 bg-black/20 px-3 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-300'
const grammar = `# Grammar Topic

## Rule
Explain the grammatical rule.

## Structure
Write the grammar structure.

## Examples
- Example 1
- Example 2

## Common Mistakes
- Incorrect:
- Correct:

## Personal Notes
Additional observations.
`

function NoteEditor({note,notebooks,onSaved,expanded}:{note:NotebookNote;notebooks:{id:number;name:string}[];onSaved:()=>void;expanded:boolean}) {
  const [draft,setDraft]=useState<NotebookDraft>(()=>{
    const stored=localStorage.getItem(`learntube-note-${note.id}`)
    if(stored){try{return JSON.parse(stored) as NotebookDraft}catch{ /* use server copy */ }}
    return {title:note.title,content:note.content,notebook_id:note.notebook_id,is_pinned:note.is_pinned}
  })
  const [status,setStatus]=useState<'Saved'|'Saving'|'Unsaved'|'Error'>(localStorage.getItem(`learntube-note-${note.id}`)?'Unsaved':'Saved')
  const [saveTick,setSaveTick]=useState(0)
  const [selected,setSelected]=useState(''),[meaning,setMeaning]=useState(''),[examples,setExamples]=useState(''),[personal,setPersonal]=useState('')
  const [vocabOpen,setVocabOpen]=useState(false)
  const [preview,setPreview]=useState(false)
  const textarea=useRef<HTMLTextAreaElement>(null),latest=useRef(draft),revision=useRef(note.revision),pending=useRef<Promise<void>|null>(null),timer=useRef<number|undefined>(undefined),alive=useRef(true)
  const client=useQueryClient()
  const saveVocab=useMutation({mutationFn:()=>api.addVocabulary({text:selected.trim(),meaning,example_sentence:examples,personal_note:personal,source_note_id:note.id}),onSuccess:()=>{setVocabOpen(false);client.invalidateQueries({queryKey:['vocabulary']});client.invalidateQueries({queryKey:['dashboard']})}})
  const change=useCallback((next:NotebookDraft)=>{latest.current=next;setDraft(next);localStorage.setItem(`learntube-note-${note.id}`,JSON.stringify(next));setStatus('Unsaved')},[note.id])
  const save=useCallback(async()=>{
    if(pending.current)return pending.current
    const snapshot={...latest.current}
    let succeeded=false
    if(alive.current)setStatus('Saving')
    const task=notebookApi.saveNote(note.id,revision.current,snapshot).then(saved=>{
      succeeded=true
      revision.current=saved.revision
      if(JSON.stringify(latest.current)===JSON.stringify(snapshot)){
        localStorage.removeItem(`learntube-note-${note.id}`)
        if(alive.current)setStatus('Saved')
      }else if(alive.current)setStatus('Unsaved')
      onSaved()
    }).catch(()=>{if(alive.current)setStatus('Error')}).finally(()=>{pending.current=null;if(succeeded&&JSON.stringify(latest.current)!==JSON.stringify(snapshot)&&alive.current)setSaveTick(value=>value+1)})
    pending.current=task
    return task
  },[note.id,onSaved])
  useEffect(()=>{if(status==='Unsaved'){clearTimeout(timer.current);timer.current=window.setTimeout(()=>{void save()},700)}return()=>clearTimeout(timer.current)},[draft,status,save,saveTick])
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;clearTimeout(timer.current);if(localStorage.getItem(`learntube-note-${note.id}`))void save()}},[note.id,save])
  const addSelection=()=>{const element=textarea.current;if(!element)return;const text=element.value.slice(element.selectionStart,element.selectionEnd).trim();if(!text)return;setSelected(text.slice(0,500));setMeaning('');setExamples('');setPersonal('');setVocabOpen(true)}
  const wrap=(before:string,after=before,label='text')=>{
    const element=textarea.current
    if(!element)return
    const start=element.selectionStart,end=element.selectionEnd
    const selected=draft.content.slice(start,end)
    if(after===''&&before.endsWith(' ')){
      const lineStart=draft.content.lastIndexOf('\n',start-1)+1
      const lineEnd=draft.content.indexOf('\n',end)
      const blockEnd=lineEnd<0?draft.content.length:lineEnd
      const lines=draft.content.slice(lineStart,blockEnd).split('\n')
      const block=lines.map(line=>before+line).join('\n')
      change({...draft,content:draft.content.slice(0,lineStart)+block+draft.content.slice(blockEnd)})
      requestAnimationFrame(()=>{element.focus();element.setSelectionRange(start+before.length,end+before.length*lines.length)})
      return
    }
    const content=selected||label
    change({...draft,content:draft.content.slice(0,start)+before+content+after+draft.content.slice(end)})
    requestAnimationFrame(()=>{element.focus();element.setSelectionRange(start+before.length,start+before.length+content.length)})
  }
  const insertEquation=()=>{
    const element=textarea.current
    if(!element)return
    const start=element.selectionStart,end=element.selectionEnd,source=draft.content
    const chosen=source.slice(start,end)||'\\frac{a}{b}'
    const prefix=start>0&&source[start-1]!=='\n'?'\n':''
    const suffix=end<source.length&&source[end]!=='\n'?'\n':''
    change({...draft,content:source.slice(0,start)+`${prefix}$$\n${chosen}\n$$${suffix}`+source.slice(end)})
    const selectedStart=start+prefix.length+3
    requestAnimationFrame(()=>{element.focus();element.setSelectionRange(selectedStart,selectedStart+chosen.length)})
  }
  return <section className={`${panel} min-w-0 p-4 sm:p-6`}>
    <div className="flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-zinc-500">Markdown note</p><span role="status" className={`text-xs ${status==='Error'?'text-rose-300':status==='Saved'?'text-emerald-300':'text-amber-200'}`}>{status==='Error'?'Save failed. Draft kept locally.':status}</span></div>
    <input aria-label="Note title" value={draft.title} onChange={event=>change({...draft,title:event.target.value})} className="mt-4 w-full bg-transparent text-2xl font-semibold outline-none placeholder:text-zinc-600" placeholder="Untitled note"/>
    <div className="mt-4 flex flex-wrap items-center gap-2 border-y border-white/10 py-3 text-xs"><button onClick={()=>change({...draft,is_pinned:!draft.is_pinned})} className="flex items-center gap-1 rounded px-2 py-1 text-zinc-300 hover:bg-white/10"><Pin size={14}/>{draft.is_pinned?'Unpin':'Pin'}</button><label className="flex items-center gap-2 text-zinc-400">Move to<select aria-label="Move note to notebook" value={draft.notebook_id} onChange={event=>change({...draft,notebook_id:Number(event.target.value)})} className="rounded border border-white/10 bg-[#202126] px-2 py-1 text-zinc-100">{notebooks.map(book=><option key={book.id} value={book.id}>{book.name}</option>)}</select></label><button onClick={addSelection} className="rounded px-2 py-1 text-indigo-300 hover:bg-white/10">Add selection to Vocabulary</button></div>
    <div role="tablist" aria-label="Note view" className="mt-4 flex gap-4 border-b border-white/10 text-sm"><button type="button" role="tab" aria-selected={!preview} onClick={()=>setPreview(false)} className={`pb-2 ${!preview?'border-b-2 border-indigo-300 text-indigo-200':'text-zinc-400 hover:text-white'}`}>Edit</button><button type="button" role="tab" aria-selected={preview} onClick={()=>setPreview(true)} className={`pb-2 ${preview?'border-b-2 border-indigo-300 text-indigo-200':'text-zinc-400 hover:text-white'}`}>Preview</button></div>
    <div hidden={preview}>
      <div className="mt-3 flex flex-wrap gap-1 text-xs text-zinc-400">{[['Heading','## ',''],['Bold','**','**'],['Italic','*','*'],['Bullet','- ',''],['Numbered','1. ',''],['Quote','> ',''],['Link','[','](https://)'],['Code','`','`'],['Inline math','$','$']].map(([label,before,after])=><button key={label} type="button" onMouseDown={event=>event.preventDefault()} onClick={()=>wrap(before,after,label==='Link'?'link text':label==='Code'?'code':label==='Inline math'?'x^2':'text')} className="rounded px-2 py-1 hover:bg-white/10 hover:text-white">{label}</button>)}<button type="button" onMouseDown={event=>event.preventDefault()} onClick={insertEquation} className="rounded px-2 py-1 hover:bg-white/10 hover:text-white">Equation</button></div>
      <textarea ref={textarea} aria-label="Note content" value={draft.content} onChange={event=>change({...draft,content:event.target.value})} onKeyDown={event=>{if((event.ctrlKey||event.metaKey)&&event.key==='s'){event.preventDefault();clearTimeout(timer.current);void save()}}} className={`${expanded?'min-h-[72vh]':'min-h-[55vh]'} mt-3 w-full resize-y bg-transparent text-base leading-7 text-zinc-200 outline-none placeholder:text-zinc-600`} placeholder="Write in Markdown…" spellCheck/>
      <p className="mt-3 text-xs text-zinc-500">Select text before using a format button, then choose Preview. Bold: **word**. Math: $x^2$ or $$ on separate lines. Ctrl+S saves immediately.</p>
    </div>
    {preview&&<div role="tabpanel" aria-label="Formatted note preview" className={`${expanded?'min-h-[72vh]':'min-h-[55vh]'} mt-3 rounded-lg border border-white/10 bg-black/10 p-4`}>{draft.content.trim()?<SafeMarkdown source={draft.content}/>:<p className="text-sm text-zinc-500">This note is empty. Choose Edit to start writing.</p>}</div>}
    {vocabOpen&&<div role="dialog" aria-modal="true" aria-label="Add to Vocabulary" className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-4"><form onSubmit={(event:FormEvent)=>{event.preventDefault();saveVocab.mutate()}} className={`${panel} w-full max-w-lg space-y-3 p-6 shadow-2xl`}><h2 className="text-lg font-semibold">Add to Vocabulary</h2><label className="block text-xs text-zinc-400">Word or phrase<input required maxLength={500} value={selected} onChange={event=>setSelected(event.target.value)} className={`${input} mt-1`}/></label><VocabularyLookupChoices text={selected} definition={meaning} examples={examples} onFill={(definition,sentences,oldDefinition,oldExamples)=>{setMeaning(current=>current===oldDefinition?definition:current);setExamples(current=>current===oldExamples?sentences:current)}}/><label className="block text-xs text-zinc-400">Definition<textarea value={meaning} onChange={event=>setMeaning(event.target.value)} className={`${input} mt-1 min-h-20`}/></label><label className="block text-xs text-zinc-400">Examples<textarea value={examples} onChange={event=>setExamples(event.target.value)} className={`${input} mt-1 min-h-20`}/></label><label className="block text-xs text-zinc-400">Personal Notes (optional)<textarea value={personal} onChange={event=>setPersonal(event.target.value)} className={`${input} mt-1 min-h-16`}/></label>{saveVocab.error&&<p role="alert" className="text-xs text-rose-300">{saveVocab.error.message}</p>}<div className="flex justify-end gap-2"><button type="button" onClick={()=>setVocabOpen(false)} className="rounded px-3 py-2 text-sm text-zinc-400">Cancel</button><button disabled={saveVocab.isPending||!selected.trim()} className="rounded bg-white px-3 py-2 text-sm text-zinc-950 disabled:opacity-50">Save expression</button></div></form></div>}
  </section>
}

export function NotebookPage(){
  const {notebookId,noteId}=useParams(),navigate=useNavigate(),client=useQueryClient()
  const selectedBook=notebookId&&notebookId!=='all'?Number(notebookId):null,selectedNote=noteId?Number(noteId):null
  const [query,setQuery]=useState(''),[pinned,setPinned]=useState(false),[browseNote,setBrowseNote]=useState<number|null>(null)
  const focused=selectedNote!==null&&browseNote!==selectedNote
  const books=useQuery({queryKey:['notebooks'],queryFn:notebookApi.all})
  const notes=useQuery({queryKey:['notebookNotes',selectedBook,query,pinned],queryFn:()=>notebookApi.notes(query,selectedBook,pinned)})
  const note=useQuery({queryKey:['notebookNote',selectedNote],queryFn:()=>notebookApi.note(selectedNote!),enabled:selectedNote!==null})
  const refresh=useCallback(()=>{void client.invalidateQueries({queryKey:['notebooks']});void client.invalidateQueries({queryKey:['notebookNotes']})},[client])
  const onNoteSaved=useCallback(()=>{refresh();void client.invalidateQueries({queryKey:['notebookNote',selectedNote]})},[refresh,client,selectedNote])
  const createBook=useMutation({mutationFn:({name,description}:{name:string;description:string})=>notebookApi.create(name,description),onSuccess:book=>{refresh();navigate(`/notebook/${book.id}`)}})
  const renameBook=useMutation({mutationFn:({id,name,description}:{id:number;name:string;description:string})=>notebookApi.update(id,name,description),onSuccess:refresh})
  const deleteBook=useMutation({mutationFn:notebookApi.remove,onSuccess:()=>{refresh();navigate('/notebook')}})
  const createNote=useMutation({mutationFn:({template}:{template:boolean})=>notebookApi.createNote({notebook_id:selectedBook!,title:template?'Grammar Topic':'Untitled note',content:template?grammar:''}),onSuccess:created=>{refresh();navigate(`/notebook/${created.notebook_id}/${created.id}`)}})
  const deleteNote=useMutation({mutationFn:notebookApi.removeNote,onSuccess:()=>{refresh();navigate(selectedBook?`/notebook/${selectedBook}`:'/notebook') }})
  const book=books.data?.find(item=>item.id===selectedBook)
  return <main className={`${focused?'w-full':'mx-auto max-w-[1700px]'} p-4 sm:p-6`}><header className="mb-6"><p className="text-sm text-indigo-300">LearnTube</p><h1 className="mt-1 text-3xl font-semibold">Notebook</h1><p className="mt-2 text-sm text-zinc-400">Keep your English learning notes organized.</p></header>
    {selectedNote!==null&&<button type="button" onClick={()=>setBrowseNote(focused?selectedNote:null)} className="mb-4 rounded-md border border-white/15 px-3 py-2 text-sm text-indigo-300 hover:bg-white/5">{focused?'Browse notebooks and notes':'Expand editor'}</button>}
    <div className={`${focused?'grid-cols-1':'xl:grid-cols-[220px_280px_minmax(0,1fr)]'} grid min-w-0 gap-4`}><aside className={`${panel} p-3 ${focused?'hidden':''}`}><div className="mb-3 flex items-center justify-between px-2"><h2 className="text-sm font-semibold">Notebooks</h2><button aria-label="Create notebook" title="Create notebook" onClick={()=>{const name=prompt('Notebook name');if(name?.trim()){const description=prompt('Description (optional)','');if(description!==null)createBook.mutate({name:name.trim(),description})}}} className="rounded p-1 text-indigo-300 hover:bg-white/10"><Plus size={17}/></button></div><Link to="/notebook" className={`block rounded px-3 py-2 text-sm ${selectedBook===null?'bg-white/10 text-white':'text-zinc-400 hover:bg-white/5'}`}>All notes</Link>{books.data?.map(item=><Link key={item.id} to={`/notebook/${item.id}`} className={`mt-1 flex items-center gap-2 rounded px-3 py-2 text-sm ${item.id===selectedBook?'bg-white/10 text-white':'text-zinc-400 hover:bg-white/5'}`}><BookOpenText size={15} className="shrink-0"/><span className="min-w-0 flex-1 truncate">{item.name}</span></Link>)}{books.data?.length===0&&<p className="px-3 py-4 text-xs text-zinc-500">Create your first notebook.</p>}{book&&<div className="mt-5 border-t border-white/10 px-2 pt-3"><p className="text-xs text-zinc-500">{book.description||'No description'}</p><div className="mt-3 flex gap-3 text-xs"><button onClick={()=>{const name=prompt('Rename notebook',book.name);if(name?.trim()){const description=prompt('Description (optional)',book.description);if(description!==null)renameBook.mutate({id:book.id,name:name.trim(),description})}}} className="text-indigo-300">Rename</button><button onClick={()=>{if(confirm(`Delete “${book.name}” and all its notes?`))deleteBook.mutate(book.id)}} className="text-rose-300">Delete</button></div></div>}{(createBook.error||renameBook.error||deleteBook.error)&&<p role="alert" className="mt-3 text-xs text-rose-300">{(createBook.error||renameBook.error||deleteBook.error)?.message}</p>}</aside>
    <section className={`${panel} min-w-0 p-3 ${focused?'hidden':''}`}><div className="flex items-center justify-between gap-2 px-2"><h2 className="text-sm font-semibold">{book?.name||'All notes'}</h2>{selectedBook!==null&&<div className="flex gap-1"><button title="Blank note" aria-label="Create blank note" onClick={()=>createNote.mutate({template:false})} className="rounded p-1 text-indigo-300 hover:bg-white/10"><Plus size={17}/></button><button onClick={()=>createNote.mutate({template:true})} className="rounded px-2 py-1 text-xs text-indigo-300 hover:bg-white/10">Grammar</button></div>}</div><div className="relative mt-4"><Search size={15} className="absolute left-3 top-2.5 text-zinc-500"/><input aria-label="Search notes" value={query} onChange={event=>setQuery(event.target.value)} placeholder="Search notes" className={`${input} pl-9`}/></div><label className="mt-3 flex items-center gap-2 text-xs text-zinc-400"><input type="checkbox" checked={pinned} onChange={event=>setPinned(event.target.checked)}/>Pinned only</label>{notes.isLoading&&<p className="mt-4 text-xs text-zinc-500">Loading notes…</p>}{notes.error&&<p role="alert" className="mt-4 text-xs text-rose-300">{notes.error.message}</p>}<div className="mt-4 space-y-1">{notes.data?.map(item=><Link key={item.id} to={`/notebook/${item.notebook_id}/${item.id}`} onClick={()=>setBrowseNote(null)} className={`block rounded-lg border px-3 py-3 ${selectedNote===item.id?'border-indigo-300/40 bg-indigo-300/10':'border-transparent hover:bg-white/5'}`}><div className="flex items-center gap-2 text-sm font-medium">{item.is_pinned&&<Pin size={13} className="text-indigo-300"/>}<span className="truncate">{item.title||'Untitled note'}</span></div><p className="mt-1 line-clamp-2 text-xs text-zinc-500">{item.content||'Empty note'}</p><p className="mt-2 text-[11px] text-zinc-600">{new Date(item.updated_at).toLocaleDateString()}</p></Link>)}</div>{notes.data?.length===0&&<p className="mt-5 text-xs text-zinc-500">No notes found.</p>}{createNote.error&&<p role="alert" className="mt-3 text-xs text-rose-300">{createNote.error.message}</p>}</section>
    <div className="min-w-0">{note.data&&selectedNote!==null?<><div className="mb-3 flex items-center justify-between"><span className="text-xs text-zinc-500">{books.data?.find(item=>item.id===note.data.notebook_id)?.name}</span><div className="flex items-center gap-3"><button type="button" onClick={()=>setBrowseNote(focused?selectedNote:null)} className="text-xs text-indigo-300">{focused?'Browse notes':'Expand editor'}</button><button onClick={()=>{if(confirm(`Delete “${note.data.title}”?`))deleteNote.mutate(note.data.id)}} className="flex items-center gap-1 text-xs text-rose-300"><Trash2 size={14}/>Delete note</button></div></div><NoteEditor key={note.data.id} note={note.data} notebooks={books.data||[]} onSaved={onNoteSaved} expanded={focused}/></>:<div className={`${panel} grid min-h-[50vh] place-items-center p-8 text-center text-sm text-zinc-500`}>{selectedNote&&note.error?'Note could not be loaded.':selectedBook?'Select a note or create one.':'Choose a notebook to begin.'}</div>}</div></div>
  </main>
}
