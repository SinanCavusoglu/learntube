import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Bookmark as BookmarkIcon, Pencil, Trash2, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Bookmark } from '@/lib/api'

export function formatTime(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds))
  const hours = Math.floor(whole / 3600)
  const minutes = Math.floor((whole % 3600) / 60)
  const rest = String(whole % 60).padStart(2, '0')
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${String(minutes).padStart(2, '0')}:${rest}`
}

export function bookmarkPosition(bookmark: Bookmark): string {
  return bookmark.type === 'video' ? formatTime(bookmark.timestamp_seconds ?? 0) : `Page ${bookmark.page_number}`
}

export function bookmarkUrl(bookmark: Bookmark): string {
  return bookmark.type === 'video'
    ? `/videos/${bookmark.video_id}?t=${bookmark.timestamp_seconds ?? 0}`
    : `/pdfs/${bookmark.pdf_id}?page=${bookmark.page_number ?? 1}`
}

export function BookmarkEditor({ location, title: initialTitle, note: initialNote = '', editing = false, onSave, onClose }:
  { location: string; title: string; note?: string; editing?: boolean; onSave: (title: string, note: string) => Promise<void>; onClose: () => void }) {
  const [title, setTitle] = useState(initialTitle)
  const [note, setNote] = useState(initialNote)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const submitting = useRef(false)
  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (submitting.current || !title.trim()) return
    submitting.current = true; setPending(true); setError('')
    try { await onSave(title.trim(), note); onClose() }
    catch (cause) { setError(cause instanceof Error ? cause.message : 'Bookmark could not be saved.') }
    finally { submitting.current = false; setPending(false) }
  }
  return <div className="fixed inset-0 z-[90] grid place-items-center bg-black/70 p-4" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !pending) onClose() }}>
    <form onSubmit={submit} role="dialog" aria-modal="true" aria-label={editing ? 'Edit bookmark' : 'Save bookmark'} onKeyDown={event => { if (event.key === 'Escape' && !pending) onClose() }} className="w-full max-w-md rounded-2xl border border-white/15 bg-[#202126] p-6 shadow-2xl">
      <div className="flex items-center justify-between"><div className="flex items-center gap-2"><BookmarkIcon size={18} className="text-indigo-300"/><h2 className="text-lg font-semibold">{editing ? 'Edit Bookmark' : 'Save Bookmark'}</h2></div><button type="button" aria-label="Close" disabled={pending} onClick={onClose} className="text-zinc-400 hover:text-white"><X size={18}/></button></div>
      <p className="mt-2 text-sm text-zinc-400">{location}</p>
      <label className="mt-5 block text-sm text-zinc-300">Title<input autoFocus required maxLength={120} value={title} onChange={event => setTitle(event.target.value)} className="mt-2 w-full rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-zinc-100 outline-none focus:border-indigo-300"/></label>
      <label className="mt-4 block text-sm text-zinc-300">Note (optional)<textarea maxLength={2000} value={note} onChange={event => setNote(event.target.value)} className="mt-2 min-h-24 w-full resize-y rounded-lg border border-white/15 bg-black/20 px-3 py-2 text-zinc-100 outline-none focus:border-indigo-300"/></label>
      {error && <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>}
      <div className="mt-5 flex justify-end gap-2"><Button type="button" variant="outline" disabled={pending} onClick={onClose}>Cancel</Button><Button disabled={pending || !title.trim()}>{pending ? 'Saving…' : editing ? 'Save Changes' : 'Save Bookmark'}</Button></div>
    </form>
  </div>
}

export function BookmarkToast({ message, onClose }: { message: string; onClose: () => void }) {
  useEffect(() => { const timer = window.setTimeout(onClose, 4000); return () => clearTimeout(timer) }, [message, onClose])
  if (!message) return null
  return <div role="status" className="fixed right-4 top-4 z-[110] rounded-xl border border-emerald-300/30 bg-[#18191d] px-4 py-3 text-sm text-emerald-200 shadow-xl">{message}</div>
}

export function BookmarkList({ bookmarks, loading, error, onOpen, onEdit, onDelete }:
  { bookmarks?: Bookmark[]; loading: boolean; error?: string; onOpen: (bookmark: Bookmark) => void; onEdit: (bookmark: Bookmark) => void; onDelete: (bookmark: Bookmark) => void }) {
  if (loading) return <p className="mt-3 text-sm text-zinc-400">Loading bookmarks…</p>
  if (error) return <p role="alert" className="mt-3 text-sm text-rose-300">{error}</p>
  if (!bookmarks?.length) return <p className="mt-3 text-sm text-zinc-500">No bookmarks yet.</p>
  return <div className="mt-3 space-y-2">{bookmarks.map(bookmark => <div key={bookmark.id} className="flex items-start gap-2 rounded-lg border border-white/10 p-3"><button type="button" onClick={() => onOpen(bookmark)} className="min-w-0 flex-1 text-left"><span className="text-xs font-medium text-indigo-300">{bookmarkPosition(bookmark)}</span><span className="ml-2 text-sm font-medium text-zinc-100">{bookmark.title}</span>{bookmark.note && <span className="mt-1 block line-clamp-2 text-xs leading-5 text-zinc-400">{bookmark.note}</span>}</button><button type="button" aria-label={`Edit ${bookmark.title}`} onClick={() => onEdit(bookmark)} className="rounded p-1 text-zinc-400 hover:bg-white/10 hover:text-white"><Pencil size={15}/></button><button type="button" aria-label={`Delete ${bookmark.title}`} onClick={() => onDelete(bookmark)} className="rounded p-1 text-zinc-400 hover:bg-rose-400/10 hover:text-rose-300"><Trash2 size={15}/></button></div>)}</div>
}
