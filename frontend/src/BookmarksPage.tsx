import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Bookmark as BookmarkIcon, FileText, Library, Pencil, Trash2 } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { bookmarksApi, type Bookmark } from '@/lib/api'
import { BookmarkEditor, BookmarkToast, bookmarkPosition, bookmarkUrl } from '@/components/Bookmarks'

export function BookmarksPage() {
  const client = useQueryClient(), navigate = useNavigate()
  const [type, setType] = useState<'all' | 'video' | 'pdf'>('all')
  const [query, setQuery] = useState('')
  const [debounced, setDebounced] = useState('')
  const [editing, setEditing] = useState<Bookmark | null>(null)
  const [toast, setToast] = useState('')
  useEffect(() => { const timer = window.setTimeout(() => setDebounced(query.trim()), 180); return () => clearTimeout(timer) }, [query])
  const bookmarks = useQuery({ queryKey: ['bookmarks', type, debounced], queryFn: () => bookmarksApi.all(type, debounced) })
  const update = useMutation({ mutationFn: ({ bookmark, title, note }: { bookmark: Bookmark; title: string; note: string }) => bookmarksApi.update(bookmark.id, title, note),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['bookmarks'] }); void client.invalidateQueries({ queryKey: ['videoBookmarks'] }); void client.invalidateQueries({ queryKey: ['pdfBookmarks'] }); setToast('Bookmark updated.') } })
  const remove = useMutation({ mutationFn: (bookmark: Bookmark) => bookmarksApi.remove(bookmark.id),
    onSuccess: () => { void client.invalidateQueries({ queryKey: ['bookmarks'] }); void client.invalidateQueries({ queryKey: ['videoBookmarks'] }); void client.invalidateQueries({ queryKey: ['pdfBookmarks'] }); setToast('Bookmark deleted.') } })
  return <main className="mx-auto max-w-5xl px-6 py-10 sm:px-10">
    <p className="flex items-center gap-2 text-sm text-indigo-300"><BookmarkIcon size={16}/> Bookmarks</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight">Return to what matters.</h1>
    <p className="mt-2 text-sm text-zinc-400">Your saved positions in videos and PDFs.</p>
    <div className="mt-8 flex flex-wrap items-center gap-2">{(['all', 'video', 'pdf'] as const).map(value => <button key={value} type="button" onClick={() => setType(value)} className={`rounded-lg px-4 py-2 text-sm ${type === value ? 'bg-indigo-300/15 text-indigo-200' : 'border border-white/10 text-zinc-400 hover:bg-white/5'}`}>{value === 'all' ? 'All' : value === 'video' ? 'Videos' : 'PDFs'}</button>)}<input value={query} onChange={event => setQuery(event.target.value)} maxLength={200} aria-label="Search bookmarks" placeholder="Search bookmarks…" className="min-w-0 flex-1 rounded-lg border border-white/10 bg-[#18191d] px-4 py-2 text-sm text-zinc-100 outline-none focus:border-indigo-300 sm:ml-auto sm:max-w-xs"/></div>
    {bookmarks.isLoading && <p className="mt-8 text-sm text-zinc-400">Loading bookmarks…</p>}
    {bookmarks.error && <p role="alert" className="mt-8 text-sm text-rose-300">{bookmarks.error.message}</p>}
    {remove.error && <p role="alert" className="mt-4 text-sm text-rose-300">{remove.error.message}</p>}
    {!bookmarks.isLoading && !bookmarks.error && bookmarks.data?.length === 0 && <div className="mt-8 rounded-xl border border-dashed border-white/10 p-10 text-center text-sm text-zinc-500">{query ? 'No bookmarks match your search.' : 'No bookmarks yet. Open a video or PDF and choose Save Bookmark.'}</div>}
    <div className="mt-6 space-y-3">{bookmarks.data?.map(bookmark => { const Icon = bookmark.type === 'video' ? Library : FileText; return <article key={bookmark.id} className="flex items-start gap-4 rounded-xl border border-white/10 bg-[#18191d] p-4"><span className="rounded-lg bg-indigo-300/10 p-2 text-indigo-300"><Icon size={18}/></span><div className="min-w-0 flex-1"><p className="truncate text-xs text-zinc-500">{bookmark.source_title} · {bookmark.type === 'video' ? 'Video' : 'PDF'}</p><h2 className="mt-1 font-medium text-zinc-100">{bookmark.title}</h2><p className="mt-1 text-xs text-indigo-300">{bookmarkPosition(bookmark)}</p>{bookmark.note && <p className="mt-2 line-clamp-2 text-sm text-zinc-400">{bookmark.note}</p>}<p className="mt-3 text-xs text-zinc-500">Saved {new Date(bookmark.created_at).toLocaleDateString()}</p></div><div className="flex shrink-0 gap-1"><button type="button" onClick={() => navigate(bookmarkUrl(bookmark))} className="rounded-md px-2 py-1 text-sm text-indigo-300 hover:bg-indigo-300/10">Open</button><button type="button" aria-label={`Edit ${bookmark.title}`} onClick={() => setEditing(bookmark)} className="rounded-md p-2 text-zinc-400 hover:bg-white/5 hover:text-white"><Pencil size={16}/></button><button type="button" aria-label={`Delete ${bookmark.title}`} disabled={remove.isPending} onClick={() => { if (confirm(`Delete bookmark “${bookmark.title}”?`)) remove.mutate(bookmark) }} className="rounded-md p-2 text-zinc-400 hover:bg-rose-400/10 hover:text-rose-300 disabled:opacity-50"><Trash2 size={16}/></button></div></article> })}</div>
    {editing && <BookmarkEditor key={editing.id} editing location={`${editing.source_title} · ${bookmarkPosition(editing)}`} title={editing.title} note={editing.note} onSave={(title, note) => update.mutateAsync({ bookmark: editing, title, note }).then(() => undefined)} onClose={() => setEditing(null)}/>}
    {toast && <BookmarkToast message={toast} onClose={() => setToast('')}/>}
  </main>
}
