import { useEffect, useMemo, useRef, useState } from 'react'
import { BookOpenText, FileText, Library, LoaderCircle, Search, X } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { API } from '@/lib/api'

type Group = 'vocabulary' | 'videos' | 'pdfs' | 'notebook'
type Result = { id: number; kind: string; type: Group; title: string; snippet: string; location: string; url: string }
type Response = { groups: Record<Group, Result[]>; has_more: Record<Group, boolean> }
const order: Group[] = ['vocabulary', 'videos', 'pdfs', 'notebook']
const labels: Record<Group, string> = { vocabulary: 'Vocabulary', videos: 'YouTube', pdfs: 'PDF', notebook: 'Notebook' }
const empty = (): Response => ({ groups: { vocabulary: [], videos: [], pdfs: [], notebook: [] },
  has_more: { vocabulary: false, videos: false, pdfs: false, notebook: false } })
const icons = { vocabulary: BookOpenText, videos: Library, pdfs: FileText, notebook: BookOpenText }

function Highlight({ text, query }: { text: string; query: string }) {
  const terms = query.trim().split(/\s+/).filter(Boolean).map(term => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
  if (!terms.length) return <>{text}</>
  const expression = new RegExp(`(${terms.join('|')})`, 'ig')
  const exact = new RegExp(`^(?:${terms.join('|')})$`, 'i')
  return <>{text.split(expression).map((part, index) => exact.test(part)
    ? <mark key={index} className="rounded bg-indigo-300/25 text-indigo-100">{part}</mark> : <span key={index}>{part}</span>)}</>
}

export function GlobalSearch() {
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [type, setType] = useState<'all' | Group>('all')
  const [page, setPage] = useState(0)
  const [data, setData] = useState<Response>(empty)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [active, setActive] = useState(0)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault(); setOpen(value => !value)
      } else if (event.key === 'Escape') setOpen(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  useEffect(() => { if (open) requestAnimationFrame(() => input.current?.focus()) }, [open])
  useEffect(() => {
    const timer = window.setTimeout(() => { setDebounced(query.trim()); setPage(0); setData(empty()); setActive(0) }, 180)
    return () => clearTimeout(timer)
  }, [query, type])
  useEffect(() => {
    if (!open || debounced.length < 2) { setLoading(false); return }
    const controller = new AbortController()
    setLoading(true); setError('')
    const params = new URLSearchParams({ q: debounced, type, limit: '8', offset: String(page * 8) })
    fetch(`${API}/api/search?${params}`, { signal: controller.signal })
      .then(async response => { if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? 'Search failed'); return response.json() as Promise<Response> })
      .then(next => setData(current => page === 0 ? next : ({ groups: Object.fromEntries(order.map(group => [group, [...current.groups[group], ...next.groups[group]]])) as Response['groups'], has_more: next.has_more })))
      .catch(cause => { if (!controller.signal.aborted) setError(cause instanceof Error ? cause.message : 'Search failed') })
      .finally(() => { if (!controller.signal.aborted) setLoading(false) })
    return () => controller.abort()
  }, [open, debounced, type, page])

  const visible = useMemo(() => order.flatMap(group => type === 'all' || type === group ? data.groups[group] : []), [data, type])
  const positions = useMemo(() => new Map(visible.map((result, index) => [`${result.kind}-${result.id}`, index])), [visible])
  useEffect(() => { if (open) document.querySelector(`[data-search-index="${active}"]`)?.scrollIntoView({ block: 'nearest' }) }, [open, active])
  const go = (result: Result) => { setOpen(false); navigate(result.url) }
  const onInputKey = (event: React.KeyboardEvent<HTMLInputElement>) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive(index => Math.max(0, Math.min(index + 1, visible.length - 1))) }
    if (event.key === 'ArrowUp') { event.preventDefault(); setActive(index => Math.max(index - 1, 0)) }
    if (event.key === 'Enter' && visible[active]) { event.preventDefault(); go(visible[active]) }
  }
  return <>
    <button type="button" onClick={() => setOpen(true)} className="mb-3 flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-left text-sm text-zinc-400 hover:border-white/20 hover:text-zinc-100" aria-label="Search LearnTube"><Search size={16}/><span className="flex-1">Search</span><kbd className="text-xs text-zinc-500">Ctrl/Cmd K</kbd></button>
    {open && <div className="fixed inset-0 z-[100] flex items-start justify-center bg-black/70 px-3 pt-[8vh] sm:pt-[12vh]" onMouseDown={event => { if (event.target === event.currentTarget) setOpen(false) }}>
      <div role="dialog" aria-modal="true" aria-label="Search LearnTube" className="w-full max-w-2xl overflow-hidden rounded-2xl border border-white/15 bg-[#1c1d22] shadow-2xl">
        <div className="flex items-center gap-3 border-b border-white/10 px-4"><Search size={19} className="text-indigo-300"/><input ref={input} value={query} maxLength={200} onChange={event => setQuery(event.target.value)} onKeyDown={onInputKey} placeholder="Search your study materials…" aria-label="Search query" className="min-w-0 flex-1 bg-transparent py-4 text-sm text-zinc-100 outline-none placeholder:text-zinc-500"/>{loading && <LoaderCircle size={17} className="animate-spin text-zinc-400"/>}{query && <button type="button" aria-label="Clear search" onClick={() => { setQuery(''); setDebounced(''); setData(empty()); setPage(0); setActive(0); input.current?.focus() }} className="text-zinc-400 hover:text-white"><X size={17}/></button>}<button type="button" onClick={() => setOpen(false)} className="rounded border border-white/10 px-1.5 py-0.5 text-xs text-zinc-500">Esc</button></div>
        <div className="flex gap-1 overflow-x-auto border-b border-white/10 px-3 py-2">{(['all', ...order] as const).map(value => <button key={value} type="button" onClick={() => { setType(value); setPage(0); setData(empty()); setActive(0) }} className={`whitespace-nowrap rounded-md px-3 py-1.5 text-xs ${type === value ? 'bg-indigo-300/15 text-indigo-200' : 'text-zinc-400 hover:bg-white/5'}`}>{value === 'all' ? 'All' : labels[value]}</button>)}</div>
        <div className="max-h-[65vh] overflow-y-auto p-3">{error && <p role="alert" className="p-4 text-sm text-rose-300">{error}</p>}{debounced.length < 2 ? <p className="p-5 text-center text-sm text-zinc-500">Type at least two characters to search.</p> : !loading && !visible.length && !error ? <p className="p-5 text-center text-sm text-zinc-500">No results found.</p> : order.map(group => (type === 'all' || type === group) && data.groups[group].length > 0 && <section key={group} className="mb-3"><h2 className="px-3 py-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">{labels[group]}</h2>{data.groups[group].map(result => { const index = positions.get(`${result.kind}-${result.id}`) ?? 0; const Icon = icons[group]; return <button key={`${result.kind}-${result.id}`} data-search-index={index} type="button" onMouseEnter={() => setActive(index)} onClick={() => go(result)} className={`flex w-full items-start gap-3 rounded-lg px-3 py-3 text-left ${active === index ? 'bg-indigo-300/10' : 'hover:bg-white/5'}`}><Icon size={17} className="mt-0.5 shrink-0 text-indigo-300"/><span className="min-w-0 flex-1"><span className="block truncate text-sm font-medium text-zinc-100"><Highlight text={result.title} query={debounced}/></span><span className="mt-1 block line-clamp-2 text-xs leading-5 text-zinc-400"><Highlight text={result.snippet} query={debounced}/></span><span className="mt-1 block text-xs text-zinc-500">{labels[group]} · {result.location}</span></span></button> })}</section>)}
          {debounced.length >= 2 && order.some(group => (type === 'all' || type === group) && data.has_more[group]) && <button type="button" disabled={loading} onClick={() => setPage(value => value + 1)} className="mt-2 w-full rounded-lg border border-white/10 py-2.5 text-sm text-indigo-300 hover:bg-white/5 disabled:opacity-50">{loading ? 'Loading…' : 'Show more results'}</button>}
        </div>
        <p className="border-t border-white/10 px-4 py-2 text-xs text-zinc-500">↑ ↓ to navigate · Enter to open · Esc to close</p>
      </div>
    </div>}
  </>
}
