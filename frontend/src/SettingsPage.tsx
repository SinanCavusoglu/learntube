import { useRef, useState } from 'react'
import { Archive, Download, RotateCcw, ShieldCheck } from 'lucide-react'
import { API } from '@/lib/api'

type Summary = {
  created_at: string
  format_version: number
  schema_version: number
  counts: Record<string, number>
  pdf_files: number
  archive_sha256: string
  safety_backup?: string
}
type SaveHandle = { createWritable: () => Promise<{ write: (chunk: Uint8Array) => Promise<void>; close: () => Promise<void>; abort: () => Promise<void> }> }

async function errorFrom(response: Response): Promise<string> {
  const body = await response.json().catch(() => null)
  return typeof body?.detail === 'string' ? body.detail : 'The request failed.'
}

function backupFilename(): string {
  const now = new Date()
  const pad = (number: number) => String(number).padStart(2, '0')
  return `learntube-backup-${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}-${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}.zip`
}

const groups: { label: string; tables: string[] }[] = [
  { label: 'Videos and transcripts', tables: ['video', 'transcriptsegment', 'videonote'] },
  { label: 'PDF documents and notes', tables: ['pdfdocument', 'pdfnote'] },
  { label: 'Vocabulary and reviews', tables: ['vocabularyitem', 'reviewevent'] },
  { label: 'IELTS Writing', tables: ['writingsession'] },
  { label: 'Notebook', tables: ['notebook', 'notebooknote'] },
  { label: 'Study activity', tables: ['studyactivity'] },
]

export function SettingsPage() {
  const [busy, setBusy] = useState<'create' | 'inspect' | 'restore' | null>(null)
  const [message, setMessage] = useState(() => {
    const notice = sessionStorage.getItem('learntube.restoreNotice') ?? ''
    sessionStorage.removeItem('learntube.restoreNotice')
    return notice
  })
  const [error, setError] = useState('')
  const [selected, setSelected] = useState<File | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const chooser = useRef<HTMLInputElement>(null)

  const create = async () => {
    setBusy('create'); setError(''); setMessage('')
    try {
      const picker = (window as Window & { showSaveFilePicker?: (options: { suggestedName: string; types: { description: string; accept: Record<string, string[]> }[] }) => Promise<SaveHandle> }).showSaveFilePicker
      let handle: SaveHandle | undefined
      if (picker) {
        try {
          handle = await picker.call(window, { suggestedName: backupFilename(),
            types: [{ description: 'LearnTube backup', accept: { 'application/zip': ['.zip'] } }] })
        } catch (cause) {
          if (cause instanceof DOMException && cause.name === 'AbortError') return
          throw cause
        }
      }
      const response = await fetch(`${API}/api/backups/create`, { method: 'POST' })
      if (!response.ok) throw new Error(await errorFrom(response))
      if (handle && response.body) {
        const writable = await handle.createWritable()
        try {
          const reader = response.body.getReader()
          while (true) {
            const { done, value } = await reader.read()
            if (done) break
            await writable.write(value)
          }
          await writable.close()
        } catch (cause) { await writable.abort(); throw cause }
      } else {
        const blob = await response.blob()
        const filename = /filename="?([^";]+)"?/.exec(response.headers.get('content-disposition') ?? '')?.[1]
          ?? backupFilename()
        const url = URL.createObjectURL(blob)
        const anchor = document.createElement('a')
        anchor.href = url; anchor.download = filename; document.body.append(anchor); anchor.click(); anchor.remove()
        window.setTimeout(() => URL.revokeObjectURL(url), 60_000)
      }
      setMessage('Backup created. Save the downloaded ZIP outside the LearnTube folder.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Backup failed.') }
    finally { setBusy(null) }
  }

  const inspect = async (file: File) => {
    setSelected(file); setSummary(null); setError(''); setMessage(''); setBusy('inspect')
    const form = new FormData(); form.append('file', file)
    try {
      const response = await fetch(`${API}/api/backups/inspect`, { method: 'POST', body: form })
      if (!response.ok) throw new Error(await errorFrom(response))
      setSummary(await response.json() as Summary)
      setMessage('Backup validated. Review the details before restoring.')
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Invalid backup.') }
    finally { setBusy(null) }
  }

  const restore = async () => {
    if (!selected || !summary) return
    if (!window.confirm('Restore this backup? Current LearnTube data will be replaced. A safety backup will be saved first.')) return
    setBusy('restore'); setError(''); setMessage('')
    const form = new FormData()
    form.append('file', selected)
    form.append('expected_hash', summary.archive_sha256)
    form.append('confirmation', 'RESTORE')
    try {
      const response = await fetch(`${API}/api/backups/restore`, { method: 'POST', body: form })
      if (!response.ok) throw new Error(await errorFrom(response))
      const result = await response.json() as Summary
      const notice = `Restore completed. Safety backup: backend/safety-backups/${result.safety_backup}.`
      sessionStorage.setItem('learntube.restoreNotice', notice)
      setMessage(`${notice} Reloading…`)
      window.setTimeout(() => window.location.assign('/settings'), 1200)
    } catch (cause) { setError(cause instanceof Error ? cause.message : 'Restore failed.') }
    finally { setBusy(null) }
  }

  return <main className="mx-auto max-w-3xl px-6 py-10 sm:px-10">
    <p className="text-sm font-medium text-indigo-300">Settings</p>
    <h1 className="mt-2 text-3xl font-semibold tracking-tight">Backup & Restore</h1>
    <p className="mt-3 text-sm leading-6 text-zinc-400">Protect your LearnTube study data. Backup and restore are available on this computer.</p>
    <div className="mt-8 space-y-5">
      <section className="rounded-2xl border border-white/10 bg-[#18191d] p-6">
        <div className="flex items-start gap-4"><span className="rounded-xl bg-indigo-300/10 p-3 text-indigo-300"><Archive size={22}/></span><div><h2 className="text-lg font-medium">Create a backup</h2><p className="mt-1 text-sm leading-6 text-zinc-400">Download your database, PDFs, notes, progress, and study history as a ZIP file.</p></div></div>
        <button type="button" disabled={busy !== null} onClick={create} className="mt-6 inline-flex items-center gap-2 rounded-lg bg-indigo-300 px-4 py-2.5 text-sm font-medium text-zinc-950 hover:bg-indigo-200 disabled:cursor-wait disabled:opacity-50"><Download size={16}/>{busy === 'create' ? 'Creating backup…' : 'Create Backup'}</button>
      </section>
      <section className="rounded-2xl border border-white/10 bg-[#18191d] p-6">
        <div className="flex items-start gap-4"><span className="rounded-xl bg-indigo-300/10 p-3 text-indigo-300"><RotateCcw size={22}/></span><div><h2 className="text-lg font-medium">Restore a backup</h2><p className="mt-1 text-sm leading-6 text-zinc-400">Choose a LearnTube ZIP. We will check it before changing any data.</p></div></div>
        <input ref={chooser} type="file" accept=".zip,application/zip" className="hidden" onChange={event => { const file = event.target.files?.[0]; if (file) void inspect(file) }} />
        <button type="button" disabled={busy !== null} onClick={() => { if (chooser.current) chooser.current.value = ''; chooser.current?.click() }} className="mt-6 rounded-lg border border-white/20 px-4 py-2.5 text-sm hover:bg-white/5 disabled:opacity-50">{busy === 'inspect' ? 'Validating…' : 'Choose Backup File'}</button>
        {selected && <p className="mt-3 break-all text-xs text-zinc-500">{selected.name}</p>}
        {summary && <div className="mt-6 rounded-xl border border-white/10 bg-[#202126] p-5">
          <div className="flex items-center gap-2 text-sm font-medium text-emerald-300"><ShieldCheck size={17}/> Backup validated</div>
          <p className="mt-3 text-sm text-zinc-300">Created {new Date(summary.created_at).toLocaleString()} · Format {summary.format_version} · Schema {summary.schema_version}</p>
          <dl className="mt-4 grid gap-2 text-sm sm:grid-cols-2">{groups.map(group => <div key={group.label} className="flex justify-between gap-4 border-b border-white/5 py-2 text-zinc-400"><dt>{group.label}</dt><dd className="text-zinc-200">{group.tables.reduce((total, table) => total + (summary.counts[table] ?? 0), 0)}</dd></div>)}</dl>
          <p className="mt-3 text-xs text-zinc-500">Uploaded PDF files: {summary.pdf_files}</p>
          <p className="mt-5 text-sm text-amber-200">Restoring replaces current data. A safety backup will be created on this PC first.</p>
          <button type="button" disabled={busy !== null} onClick={restore} className="mt-4 rounded-lg border border-amber-300/40 px-4 py-2.5 text-sm font-medium text-amber-100 hover:bg-amber-300/10 disabled:cursor-wait disabled:opacity-50">{busy === 'restore' ? 'Restoring…' : 'Restore Backup'}</button>
        </div>}
      </section>
    </div>
    {message && <p role="status" className="mt-5 text-sm text-emerald-300">{message}</p>}
    {error && <p role="alert" className="mt-5 text-sm text-rose-300">{error}</p>}
  </main>
}
