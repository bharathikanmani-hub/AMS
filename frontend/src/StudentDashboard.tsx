import { useEffect, useState } from 'react'
import { CalendarDays, CheckCircle2, LogOut, TriangleAlert } from 'lucide-react'
import { AuthError, getStudentDashboard, type StudentDash, type User } from './lib/api'

const THRESHOLD = 75
const badge = {
  present: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300',
  absent: 'border-red-500/40 bg-red-500/10 text-red-300',
}
const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'
const filters = ['All', 'Present', 'Absent'] as const
const tabs = ['Attendance History', 'My Timetable'] as const
const lbl = 'font-mono text-[11px] tracking-[.2em] uppercase'

export default function StudentDashboard({ user, onOut }: { user: User; onOut: () => void }) {
  const [tab, setTab] = useState<(typeof tabs)[number]>('Attendance History')
  const [data, setData] = useState<StudentDash | null>(null)
  const [err, setErr] = useState('')
  const [filter, setFilter] = useState<(typeof filters)[number]>('All')

  useEffect(() => {  // refresh regularly: a student marked present in class shows up here within seconds
    let stop = false
    const load = () => getStudentDashboard().then(d => { if (!stop) { setData(d); setErr('') } })
      .catch(e => { if (e instanceof AuthError) onOut(); else if (!stop) setErr(e.message || 'Could not load your attendance.') })
    load(); const id = window.setInterval(load, 10000)
    return () => { stop = true; window.clearInterval(id) }
  }, [])

  const records = data?.records ?? []
  const present = data?.present ?? 0
  const total = data?.total ?? 0
  const absent = data?.absent ?? 0
  const shown = records.filter(r => filter === 'All' || r.status === filter.toLowerCase())
  const overall = data?.overall ?? 0
  const good = total === 0 || overall >= THRESHOLD
  const displayName = data?.name && data.name !== data.roll ? data.name : null
  const first = (displayName ?? user.name).split(/[\s.@]/)[0] || 'Student'
  const th = `p-3 text-left font-medium text-slate-400 ${lbl}`
  return (
    <div className="min-h-screen bg-[#090d15] text-slate-100 relative overflow-hidden"
      style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)', backgroundSize: '40px 40px' }}>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-[radial-gradient(ellipse_at_top_left,rgba(20,184,166,.18),transparent_60%)]" />
      <div className="relative mx-auto max-w-5xl px-5 py-8 space-y-8">
        <header className="flex items-start justify-between gap-4">
          <div><h1 className="text-4xl md:text-5xl font-bold tracking-tight">Hello, {first}</h1>
            <p className="mt-2 text-lg text-slate-400">Roll {data?.roll ?? user.identifier}{data?.section ? ` · ${data.section}` : ''}</p></div>
          <button onClick={onOut} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm"><LogOut className="size-4" />Sign out</button>
        </header>
        {err && <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{err}</p>}
        {data && !data.section && <p className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-300">You are not assigned to a section yet, so attendance cannot be recorded for you. Please ask your faculty or administrator.</p>}
        <div className="grid md:grid-cols-3 gap-4">
          <div className="rounded-2xl border border-white/10 bg-[#101623] p-6">
            <p className={`${lbl} text-emerald-300`}>Overall attendance</p>
            <p className="mt-2 text-4xl font-bold">{data ? `${overall}%` : '…'}</p>
            <div className="mt-3 h-2 rounded-full bg-slate-800"><div className={`h-2 rounded-full ${good ? 'bg-emerald-400' : 'bg-red-400'}`} style={{ width: `${overall}%` }} /></div></div>
          <div className="rounded-2xl border border-white/10 bg-[#101623] p-6">
            <p className={`${lbl} text-cyan-300`}>Present sessions</p>
            <p className="mt-2 text-4xl font-bold">{present}<span className="text-xl text-slate-500"> /{total}</span></p></div>
          <div className="rounded-2xl border border-white/10 bg-[#101623] p-6">
            <p className={`${lbl} text-red-300`}>Absent sessions</p>
            <p className="mt-2 text-4xl font-bold">{absent}<span className="text-xl text-slate-500"> /{total}</span></p>
            <p className="mt-1 flex items-center gap-2 text-sm text-slate-400">{good ? <CheckCircle2 className="size-4 text-emerald-400" /> : <TriangleAlert className="size-4 text-amber-400" />}{total === 0 ? 'No classes yet' : good ? 'Good standing' : `Below the ${THRESHOLD}% minimum`}</p></div>
        </div>
        <div className="inline-flex rounded-xl border border-white/10 bg-[#101623] p-1 text-sm">
          {tabs.map(t => <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 rounded-lg ${tab === t ? 'bg-[#0b0f18] text-white font-medium' : 'text-slate-400'}`}>{t}</button>)}</div>
        <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#101623] p-3">
          {tab === 'Attendance History' ? <>
            <div className="flex gap-2 p-1 pb-3 text-xs">{filters.map(f => <button key={f} onClick={() => setFilter(f)} className={`rounded-full border px-3 py-1 ${filter === f ? 'border-cyan-400/60 bg-cyan-400/10 text-cyan-200' : 'border-white/10 text-slate-400'}`}>{f}{f === 'Present' ? ` (${present})` : f === 'Absent' ? ` (${absent})` : ` (${total})`}</button>)}</div>
            <table className="w-full text-sm"><thead><tr>{['Date', 'Subject', 'Entry', 'Exit', 'Status'].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{data && shown.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">{records.length === 0 ? 'No class has been held for you yet.' : `No ${filter.toLowerCase()} classes.`}</td></tr>}
              {shown.map((r, i) => <tr key={i} className="border-t border-white/10"><td className="p-3 font-mono">{r.date}</td><td>{r.subject}</td><td className="font-mono">{fmtTime(r.entry)}</td><td className="font-mono">{fmtTime(r.exit)}</td>
                <td><span className={`rounded-full border px-2.5 py-0.5 text-xs uppercase ${badge[r.status]}`}>{r.status}</span></td></tr>)}</tbody></table></>
          : <table className="w-full text-sm"><thead><tr>{['Day', 'Time', 'Subject', 'Room'].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{data && (data.timetable.length === 0) && <tr><td colSpan={4} className="p-4 text-slate-500">{data.section ? 'No timetable has been published for your section yet.' : 'Your timetable will appear once you are assigned to a section.'}</td></tr>}
              {data?.timetable.map((r, i) => <tr key={i} className="border-t border-white/10">{r.map((c, j) => <td key={j} className={`p-3 ${j === 1 ? 'font-mono' : ''}`}>{c}</td>)}</tr>)}</tbody></table>}
        </div>
        <p className="flex items-center gap-2 text-xs text-slate-500"><CalendarDays className="size-3.5" />Press Entry when you arrive and Exit when you leave. Each period is 45 minutes; less than 20 minutes in class counts as absent.</p>
      </div>
    </div>
  )
}
