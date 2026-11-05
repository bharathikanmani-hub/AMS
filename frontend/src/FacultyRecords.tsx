// Attendance records for the signed-in faculty, read from the database (so they are still there after a reload).
// Pick a date -> every class taken that day with Present / Absent / Total -> click a class for the student list
// with the subject, entry time, exit time and status.
import { useCallback, useEffect, useState } from 'react'
import { Download } from 'lucide-react'
import { AuthError, live, type HistorySession, type HistoryStudent } from './lib/api'

const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'
const fmtDate = (iso: string) => new Date(iso + 'T00:00:00').toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })

export default function FacultyRecords({ dark = false, onAuthError }: { dark?: boolean; onAuthError?: () => void }) {
  const [date, setDate] = useState(todayISO())
  const [rows, setRows] = useState<HistorySession[]>([])
  const [openId, setOpenId] = useState<number | null>(null)
  const [detail, setDetail] = useState<HistoryStudent[]>([])
  const [err, setErr] = useState('')

  const C = dark
    ? { card: 'border-white/10 bg-[#101826]', muted: 'text-slate-400', head: 'text-slate-300', line: 'border-white/10', input: 'border-white/10 bg-[#0a0e16] text-slate-100 [color-scheme:dark]', btn: 'border-white/15 text-slate-200' }
    : { card: 'border-slate-200 bg-white', muted: 'text-slate-500', head: 'text-slate-500', line: 'border-slate-200', input: 'border-slate-300 bg-white text-slate-900', btn: 'border-slate-300 text-slate-700' }

  const fail = (e: any) => { if (e instanceof AuthError) onAuthError?.(); else setErr(e?.message || 'Could not load the records.') }
  const load = useCallback(async () => {
    try {
      const r = await live.history(date)
      setRows(r.sessions); setErr('')
      if (openId != null) setDetail((await live.historySession(openId)).students)
    } catch (e) { fail(e) }
  }, [date, openId])
  useEffect(() => {
    load()
    const id = window.setInterval(() => { if (!document.hidden) load() }, 10000)   // stays current while a class is running
    return () => window.clearInterval(id)
  }, [load])

  const toggle = async (id: number) => {
    if (openId === id) { setOpenId(null); setDetail([]); return }
    setOpenId(id); setDetail([])
    try { setDetail((await live.historySession(id)).students) } catch (e) { fail(e) }
  }
  const chip = (st: string) => st === 'present'
    ? (dark ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300' : 'border-emerald-300 bg-emerald-50 text-emerald-700')
    : (dark ? 'border-red-500/40 bg-red-500/10 text-red-300' : 'border-red-300 bg-red-50 text-red-700')

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm font-medium">Date
          <input type="date" value={date} max={todayISO()} onChange={e => { setDate(e.target.value || todayISO()); setOpenId(null); setDetail([]) }}
            className={`mt-1 block rounded-lg border px-3 py-2 text-sm ${C.input}`} /></label>
        <button onClick={load} className={`rounded-lg border px-4 py-2 text-sm ${C.btn}`}>Refresh</button>
      </div>
      {err && <p role="alert" className="text-sm text-red-500">{err}</p>}
      {rows.length === 0 && !err && <p className={`rounded-xl border p-5 text-sm ${C.card} ${C.muted}`}>No class was marked on {fmtDate(date)}.</p>}
      {rows.map(r => (
        <div key={r.session_id} className={`rounded-xl border ${C.card}`}>
          <button onClick={() => toggle(r.session_id)} className="w-full p-4 text-left">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div><p className="font-semibold">{r.subject} · {r.section}</p>
                <p className={`text-xs ${C.muted}`}>{fmtDate(r.date)} · period {r.period} · {r.finished ? 'class ended' : 'in progress'}</p></div>
              <div className="flex gap-2 text-center text-xs">
                <div className={`rounded-lg border px-3 py-1.5 ${chip('present')}`}><p className="text-xl font-bold">{r.present}</p>Present</div>
                <div className={`rounded-lg border px-3 py-1.5 ${chip('absent')}`}><p className="text-xl font-bold">{r.absent}</p>Absent</div>
                <div className={`rounded-lg border px-3 py-1.5 ${C.line}`}><p className="text-xl font-bold">{r.total}</p>Total</div>
              </div>
            </div>
          </button>
          {openId === r.session_id && (
            <div className={`overflow-x-auto border-t p-3 ${C.line}`}>
              <div className="mb-2 flex justify-end">
                <a href={live.csvUrl(r.session_id)} className={`inline-flex items-center gap-2 rounded-md border px-3 py-1 text-xs ${C.btn}`}><Download className="size-3.5" />CSV</a></div>
              <table className="w-full text-sm">
                <thead className={`text-left ${C.head}`}><tr>{['Roll', 'Name', 'Subject', 'Entry', 'Exit', 'Status'].map(h => <th key={h} className="p-2 font-medium">{h}</th>)}</tr></thead>
                <tbody>
                  {detail.length === 0 && <tr><td colSpan={6} className={`p-2 ${C.muted}`}>No students in this class.</td></tr>}
                  {detail.map(d => (
                    <tr key={d.roll} className={`border-t ${C.line}`}>
                      <td className="p-2 font-mono">{d.roll}</td><td className="p-2">{d.name}</td><td className="p-2">{d.subject}</td>
                      <td className="p-2 font-mono">{fmtTime(d.entry)}</td>
                      <td className="p-2 font-mono">{d.inside ? 'inside' : fmtTime(d.exit)}</td>
                      <td className="p-2"><span className={`rounded-full border px-2 py-0.5 text-xs ${chip(d.status)}`}>{d.status}</span></td>
                    </tr>))}
                </tbody>
              </table>
            </div>)}
        </div>))}
    </div>
  )
}
