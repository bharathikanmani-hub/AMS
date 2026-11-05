import { useCallback, useEffect, useState } from 'react'
import { CalendarDays, Check, ClipboardCheck, Download, Layers, LogOut, Pencil, Plus, ShieldCheck, Trash2, UserCog, Users, X } from 'lucide-react'
import { admin, AuthError, type AdminUser, type AttSession, type AttStudent, type NewPeriod, type Period, type SectionInfo, type User } from './lib/api'

const plus45 = (t: string) => { const [h, m] = t.split(':').map(Number); const x = h * 60 + m + 45; return `${String(Math.floor(x / 60) % 24).padStart(2, '0')}:${String(x % 60).padStart(2, '0')}` }
const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const fmt = (t: string) => { const [h, m] = t.split(':').map(Number); return `${String(h % 12 || 12).padStart(2, '0')}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}` }
const field = 'mt-1 w-full rounded-lg border border-white/10 bg-[#0b0f18] px-3 py-2.5 text-sm text-slate-100 outline-none focus:border-cyan-400 [color-scheme:dark]'
const tabs = ['Attendance', 'Timetable', 'Users', 'Sections', 'Reports'] as const
const todayISO = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}` }
const chip = { present: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300', absent: 'border-red-500/40 bg-red-500/10 text-red-300', not_seen: 'border-slate-500/40 bg-slate-500/10 text-slate-300' } as Record<string, string>
const th = 'p-3 text-left font-mono text-[11px] tracking-widest text-slate-400 uppercase font-medium'

const Stat = ({ label, value, color, icon }: { label: string; value: number; color: string; icon: React.ReactNode }) => (
  <div className="rounded-2xl border border-white/10 bg-[#101623] p-6 min-h-36">
    <div className={color}>{icon}</div>
    <p className={`mt-4 font-mono text-[11px] tracking-[.2em] uppercase ${color} opacity-80`}>{label}</p>
    <p className={`mt-1 text-4xl font-bold ${color}`}>{value}</p>
  </div>
)

export default function AdminConsole({ user, onOut }: { user: User; onOut: () => void }) {
  const [tab, setTab] = useState<(typeof tabs)[number]>('Attendance')
  const [counts, setCounts] = useState({ users: 0, faculty: 0, periods: 0, records: 0, students: 0, sections: 0, pending: 0 })
  const [periods, setPeriods] = useState<Period[]>([])
  const [facultyOpts, setFacultyOpts] = useState<{ id: number; name: string }[]>([])
  const [sectionNames, setSectionNames] = useState<string[]>([])
  const [users, setUsers] = useState<AdminUser[]>([])
  const [loadErr, setLoadErr] = useState('')
  const [f, setF] = useState({ day: 'Mon', no: '1', start: '09:00', end: '09:45', section: 'CSE-A', subject: '', faculty_id: '', room: '' })
  const [err, setErr] = useState('')
  const [okMsg, setOkMsg] = useState('')
  const [nu, setNu] = useState({ name: '', email: '', password: '', role: 'faculty' as 'faculty' | 'admin' | 'student', roll_number: '', section: '' })
  const [userMsg, setUserMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [low, setLow] = useState<{ roll: string; name: string; section: string; present: number; total: number; pct: number }[] | null>(null)

  const [secs, setSecs] = useState<SectionInfo[]>([])
  const [unassigned, setUnassigned] = useState(0)
  const [newSec, setNewSec] = useState('')
  const [bulk, setBulk] = useState({ section_id: '', rolls: '' })
  const [secMsg, setSecMsg] = useState<{ ok: boolean; text: string } | null>(null)
  const [attDate, setAttDate] = useState(todayISO())
  const [attRows, setAttRows] = useState<AttSession[]>([])
  const [openId, setOpenId] = useState<number | null>(null)
  const [detail, setDetail] = useState<AttStudent[]>([])
  const [decideMsg, setDecideMsg] = useState('')

  const fail = (e: any) => { if (e instanceof AuthError) onOut(); else setLoadErr(e?.message || 'Request failed.') }
  const reload = useCallback(async () => {
    try {
      const [o, t, u, sc] = await Promise.all([admin.overview(), admin.timetable(), admin.users(), admin.sections()])
      setCounts(o); setPeriods(t.periods); setFacultyOpts(t.faculty); setUsers(u.users); setSecs(sc.sections); setUnassigned(sc.unassigned)
      setSectionNames(Array.from(new Set([...t.sections, ...u.sections])))
      setLoadErr('')
    } catch (e) { fail(e) }
  }, [])
  useEffect(() => { reload() }, [reload])

  const loadAtt = useCallback(async () => {
    try {
      const r = await admin.attendance(attDate); setAttRows(r.sessions)
      if (openId != null) setDetail((await admin.attendanceDetail(openId)).students)
    } catch (e) { fail(e) }
  }, [attDate, openId])
  useEffect(() => {  // live: the numbers refresh while the admin watches a class being marked
    if (tab !== 'Attendance') return
    loadAtt()
    const id = window.setInterval(loadAtt, 8000)
    return () => window.clearInterval(id)
  }, [tab, loadAtt])
  const toggleOpen = async (id: number) => {
    if (openId === id) { setOpenId(null); setDetail([]); return }
    setOpenId(id); setDetail([])
    try { setDetail((await admin.attendanceDetail(id)).students) } catch (e) { fail(e) }
  }
  const decide = async (u: AdminUser, approve: boolean) => {
    try { const r = approve ? await admin.approve(u.id) : await admin.reject(u.id); setDecideMsg(r.message); reload() } catch (e) { fail(e) }
  }
  const editEmail = async (u: AdminUser) => {
    const v = window.prompt(`E-mail for ${u.name} (used for password-reset codes):`, u.email ?? '')
    if (v == null || !v.trim()) return
    try { await admin.setEmail(u.id, v.trim()); setDecideMsg('E-mail updated.'); reload() } catch (e: any) { if (e instanceof AuthError) onOut(); else setDecideMsg(e.message) }
  }
  const addSection = async (e: React.FormEvent) => {
    e.preventDefault(); setSecMsg(null)
    try { const r = await admin.createSection(newSec.trim()); setSecMsg({ ok: true, text: r.message }); setNewSec(''); reload() }
    catch (x: any) { if (x instanceof AuthError) onOut(); else setSecMsg({ ok: false, text: x.message }) }
  }
  const addBulk = async (e: React.FormEvent) => {
    e.preventDefault(); setSecMsg(null)
    if (!bulk.section_id) { setSecMsg({ ok: false, text: 'Choose a section first.' }); return }
    try { const r = await admin.addStudentsToSection(Number(bulk.section_id), bulk.rolls); setSecMsg({ ok: r.not_found.length === 0, text: r.message }); if (r.assigned) setBulk({ ...bulk, rolls: '' }); reload() }
    catch (x: any) { if (x instanceof AuthError) onOut(); else setSecMsg({ ok: false, text: x.message }) }
  }
  const removeSection = async (sc: SectionInfo) => {
    if (!window.confirm(`Delete section ${sc.name}?`)) return
    try { await admin.deleteSection(sc.id); setSecMsg({ ok: true, text: `${sc.name} deleted.` }); reload() } catch (x: any) { if (x instanceof AuthError) onOut(); else setSecMsg({ ok: false, text: x.message }) }
  }

  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => setF({ ...f, [k]: e.target.value })

  const addPeriod = async (e: React.FormEvent) => {
    e.preventDefault(); setOkMsg('')
    if (!f.subject.trim() || !f.faculty_id || !f.room.trim() || !f.no.trim() || !f.section.trim()) { setErr('Fill in section, period number, subject, faculty and classroom.'); return }
    const body: NewPeriod = { day: f.day, no: Number(f.no), start: f.start, end: f.end, section: f.section.trim(), subject: f.subject.trim(), faculty_id: Number(f.faculty_id), room: f.room.trim() }
    try {
      const r = await admin.addPeriod(body)
      setErr(''); setOkMsg(r.message); setF({ ...f, no: String(Number(f.no) + 1 || ''), subject: '' })
      reload()
    } catch (x: any) { if (x instanceof AuthError) onOut(); else setErr(x.message) }
  }
  const removePeriod = async (p: Period) => {
    if (!window.confirm(`Remove ${p.subject} · ${p.section} (${p.day} period ${p.no})? ${p.faculty} may lose access to this class.`)) return
    try { await admin.deletePeriod(p.id); reload() } catch (e) { fail(e) }
  }
  const addUser = async (e: React.FormEvent) => {
    e.preventDefault(); setUserMsg(null)
    try {
      const r = await admin.createUser(nu)
      setUserMsg({ ok: true, text: r.message }); setNu({ ...nu, name: '', email: '', password: '', roll_number: '' }); reload()
    } catch (x: any) { if (x instanceof AuthError) onOut(); else setUserMsg({ ok: false, text: x.message }) }
  }
  const toggle = async (u: AdminUser) => { try { await admin.setActive(u.id, !u.active); reload() } catch (e) { fail(e) } }
  const assign = async (u: AdminUser, section: string) => {
    if (u.student_id == null) return
    try { await admin.setSection(u.student_id, section); reload() } catch (e) { fail(e) }
  }

  return (
    <div className="min-h-screen bg-[#090d15] text-slate-100 relative overflow-hidden"
      style={{ backgroundImage: 'linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px)', backgroundSize: '40px 40px' }}>
      <div className="pointer-events-none absolute inset-x-0 top-0 h-96 bg-[radial-gradient(ellipse_at_top_left,rgba(20,184,166,.18),transparent_60%)]" />
      <div className="relative mx-auto max-w-6xl px-5 py-8 space-y-8">
        <header className="flex items-start justify-between gap-4">
          <div><h1 className="text-4xl md:text-5xl font-bold tracking-tight">Admin Console</h1>
            <p className="mt-2 text-lg text-slate-400">Users · Weekly timetable · Attendance analytics</p></div>
          <button onClick={onOut} className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-sm"><LogOut className="size-4" />Sign out</button>
        </header>
        {loadErr && <p role="alert" className="rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-300">{loadErr}</p>}
        <div className="grid sm:grid-cols-2 gap-4">
          <Stat label="Users" value={counts.users} color="text-cyan-300" icon={<Users className="size-5" />} />
          <Stat label="Faculty" value={counts.faculty} color="text-emerald-300" icon={<UserCog className="size-5" />} />
          <Stat label="Periods" value={counts.periods} color="text-violet-300" icon={<CalendarDays className="size-5" />} />
          <Stat label="Attendance records" value={counts.records} color="text-amber-300" icon={<ClipboardCheck className="size-5" />} />
          <Stat label="Students" value={counts.students} color="text-sky-300" icon={<Users className="size-5" />} />
          <Stat label="Sections" value={counts.sections} color="text-pink-300" icon={<Layers className="size-5" />} />
        </div>
        {counts.pending > 0 && <button onClick={() => setTab('Users')} className="w-full rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-left text-sm text-amber-300">{counts.pending} account request{counts.pending > 1 ? 's' : ''} waiting for your approval. Open Users to review.</button>}
        <div className="inline-flex rounded-xl border border-white/10 bg-[#101623] p-1 text-sm">
          {tabs.map(t => <button key={t} onClick={() => setTab(t)} className={`px-4 py-2 rounded-lg ${tab === t ? 'bg-[#0b0f18] text-white font-medium' : 'text-slate-400'}`}>{t}</button>)}
        </div>

        {tab === 'Attendance' && <div className="space-y-4">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-sm font-medium">Date<input type="date" value={attDate} max={todayISO()} onChange={e => { setAttDate(e.target.value || todayISO()); setOpenId(null); setDetail([]) }} className={field + ' w-auto'} /></label>
            <button onClick={loadAtt} className="rounded-lg border border-white/15 px-4 py-2.5 text-sm">Refresh</button>
            <span className="text-xs text-slate-500 pb-3">Updates automatically while a class is being marked.</span></div>
          {attRows.length === 0 && <p className="rounded-2xl border border-white/10 bg-[#101623] p-6 text-sm text-slate-400">No class was marked on {attDate}. When faculty start Live Attendance, each class appears here with its present / absent count out of the section total.</p>}
          {attRows.map(r => <div key={r.session_id} className="rounded-2xl border border-white/10 bg-[#101623]">
            <button onClick={() => toggleOpen(r.session_id)} className="w-full p-5 text-left">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div><p className="text-lg font-bold">{r.section} · {r.subject}</p><p className="text-xs text-slate-400">{r.faculty} · period {r.period} · <span className={r.finished ? 'text-slate-400' : 'text-emerald-300'}>{r.finished ? 'class ended' : 'in progress'}</span></p></div>
                <div className="flex gap-3 text-center">
                  <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-4 py-2"><p className="text-2xl font-bold text-emerald-300">{r.present}</p><p className="font-mono text-[10px] tracking-widest text-emerald-300/80 uppercase">Present</p></div>
                  <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-2"><p className="text-2xl font-bold text-red-300">{r.absent}</p><p className="font-mono text-[10px] tracking-widest text-red-300/80 uppercase">Absent</p></div>
                  <div className="rounded-xl border border-white/10 px-4 py-2"><p className="text-2xl font-bold">{r.total}</p><p className="font-mono text-[10px] tracking-widest text-slate-400 uppercase">Total</p></div></div></div></button>
            {openId === r.session_id && <div className="overflow-x-auto border-t border-white/10 p-3"><table className="w-full text-sm"><thead><tr>{['Roll', 'Name', 'Subject', 'Entry', 'Exit', 'Status'].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>{detail.length === 0 && <tr><td colSpan={6} className="p-3 text-slate-500">No students are assigned to this section yet. Add them in the Sections tab.</td></tr>}
                {detail.map(d => <tr key={d.roll} className="border-t border-white/10"><td className="p-3 font-mono">{d.roll}</td><td>{d.name}</td><td>{d.subject}</td>
                  <td className="font-mono">{d.entry ? new Date(d.entry).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'}</td>
                  <td className="font-mono">{d.exit ? new Date(d.exit).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'}</td>
                  <td><span className={`rounded-full border px-2.5 py-0.5 text-xs ${chip[d.status] ?? chip.absent}`}>{d.status}</span></td></tr>)}</tbody></table></div>}
          </div>)}
        </div>}

        {tab === 'Timetable' && <>
          <form onSubmit={addPeriod} noValidate className="rounded-2xl border border-white/10 bg-[#101623] p-6 space-y-4">
            <h2 className="text-lg font-bold">Add Period</h2>
            <p className="text-xs text-slate-400">Adding a period also gives that faculty member access to this subject and section in Live Attendance.</p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 text-sm font-medium">
              <label>Day<select value={f.day} onChange={set('day')} className={field}>{days.map(d => <option key={d}>{d}</option>)}</select></label>
              <label>Period #<input type="number" min={1} value={f.no} onChange={set('no')} className={field} /></label>
              <label>Start<input type="time" value={f.start} onChange={e => setF({ ...f, start: e.target.value, end: e.target.value ? plus45(e.target.value) : f.end })} className={field} /></label>
              <label>End (45 min)<input type="time" value={f.end} readOnly className={field + ' opacity-70'} /></label>
              <label>Section<input list="section-list" value={f.section} onChange={set('section')} placeholder="CSE-A" className={field} />
                <datalist id="section-list">{sectionNames.map(s => <option key={s} value={s} />)}</datalist></label>
              <label>Subject<input value={f.subject} onChange={set('subject')} placeholder="Computer Vision" className={field} /></label>
              <label>Faculty<select value={f.faculty_id} onChange={set('faculty_id')} className={field}><option value="">Pick faculty</option>{facultyOpts.map(d => <option key={d.id} value={d.id}>{d.name} (ID {d.id})</option>)}</select></label>
              <label>Classroom<input value={f.room} onChange={set('room')} placeholder="R-101" className={field} /></label>
            </div>
            {err && <p role="alert" className="text-sm text-red-400">{err}</p>}
            {okMsg && <p role="status" className="text-sm text-emerald-300">{okMsg}</p>}
            <button className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-medium text-slate-900"><Plus className="size-4" />Add Period</button>
          </form>
          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#101623]"><table className="w-full text-sm"><thead><tr>{['Day', '#', 'Time', 'Section', 'Subject', 'Faculty', 'Room', ''].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{periods.length === 0 && <tr><td colSpan={8} className="p-4 text-slate-500">No periods yet. Add the first one above.</td></tr>}
              {periods.map(p => <tr key={p.id} className="border-t border-white/10">
                <td className="p-3">{p.day}</td><td className="font-mono">{p.no}</td><td className="font-mono whitespace-nowrap">{fmt(p.start)} – {fmt(p.end)}</td><td>{p.section}</td><td>{p.subject}</td><td>{p.faculty}</td><td className="font-mono">{p.room}</td>
                <td className="pr-3 text-right"><button onClick={() => removePeriod(p)} aria-label="Remove period" className="text-slate-500 hover:text-red-400"><Trash2 className="size-4" /></button></td></tr>)}</tbody></table></div></>}

        {tab === 'Users' && <>
          {decideMsg && <p role="status" className="rounded-lg border border-white/10 bg-[#101623] p-3 text-sm text-emerald-300">{decideMsg}</p>}
          {users.some(u => u.pending) && <div className="rounded-2xl border border-amber-500/40 bg-amber-500/5 p-5 space-y-3">
            <h2 className="text-lg font-bold text-amber-300">Waiting for approval</h2>
            {users.filter(u => u.pending).map(u => <div key={u.id} className="flex flex-wrap items-center justify-between gap-3 border-t border-white/10 pt-3">
              <div><p className="font-medium">{u.name} <span className="ml-2 rounded-full border border-amber-500/40 px-2 py-0.5 text-xs capitalize text-amber-300">{u.requested_role}</span></p><p className="font-mono text-xs text-slate-400">{u.email}</p></div>
              <div className="flex gap-2"><button onClick={() => decide(u, true)} className="inline-flex items-center gap-1 rounded-lg bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950"><Check className="size-4" />Approve</button>
                <button onClick={() => decide(u, false)} className="inline-flex items-center gap-1 rounded-lg border border-red-500/40 px-3 py-1.5 text-sm text-red-300"><X className="size-4" />Reject</button></div></div>)}</div>}
          <form onSubmit={addUser} noValidate className="rounded-2xl border border-white/10 bg-[#101623] p-6 space-y-4">
            <h2 className="text-lg font-bold">Add Faculty / Admin / Student</h2>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 text-sm font-medium">
              <label>Full name<input value={nu.name} onChange={e => setNu({ ...nu, name: e.target.value })} placeholder="Maria" className={field} /></label>
              <label>E-mail<input type="email" value={nu.email} onChange={e => setNu({ ...nu, email: e.target.value })} placeholder="maria@college.edu" className={field} /></label>
              <label>Password<input type="password" value={nu.password} onChange={e => setNu({ ...nu, password: e.target.value })} placeholder="min 8 characters" autoComplete="new-password" className={field} /></label>
              <label>Role<select value={nu.role} onChange={e => setNu({ ...nu, role: e.target.value as 'faculty' | 'admin' | 'student' })} className={field}><option value="faculty">Faculty</option><option value="admin">Admin</option><option value="student">Student</option></select></label>
              {nu.role === 'student' && <label>Roll number<input value={nu.roll_number} onChange={e => setNu({ ...nu, roll_number: e.target.value })} placeholder="e.g. 21CS001" className={field} /></label>}
              {nu.role === 'student' && <label>Section (optional)<select value={nu.section} onChange={e => setNu({ ...nu, section: e.target.value })} className={field}><option value="">No section yet</option>{sectionNames.map(n => <option key={n} value={n}>{n}</option>)}</select></label>}
            </div>
            {userMsg && <p role="status" className={`text-sm ${userMsg.ok ? 'text-emerald-300' : 'text-red-400'}`}>{userMsg.text}</p>}
            <button className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-medium text-slate-900"><Plus className="size-4" />Create account</button>
          </form>
          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#101623]"><table className="w-full text-sm"><thead><tr>{['Name', 'Role', 'Sign-in ID / Roll', 'E-mail', 'Section', 'Status'].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{users.filter(u => !u.pending).map(u => <tr key={u.id} className="border-t border-white/10">
              <td className="p-3">{u.name}</td><td className="capitalize">{u.role}</td><td className="font-mono text-slate-300">{u.identifier}</td>
              <td className="text-xs text-slate-300"><span className="mr-1">{u.email?.endsWith('@attendai.local') ? <span className="text-amber-400">not set</span> : u.email}</span><button onClick={() => editEmail(u)} aria-label="Edit e-mail" className="align-middle text-slate-500 hover:text-cyan-300"><Pencil className="inline size-3.5" /></button></td>
              <td>{u.role === 'student'
                ? <select value={u.section ?? ''} onChange={e => assign(u, e.target.value)} className="rounded-md border border-white/10 bg-[#0b0f18] px-2 py-1 text-xs [color-scheme:dark]"><option value="">— unassigned —</option>{sectionNames.map(s => <option key={s} value={s}>{s}</option>)}</select>
                : <span className="text-slate-500">—</span>}</td>
              <td>{u.role === 'admin' && String(u.id) === user.identifier ? <span className="text-xs text-slate-500">you</span>
                : <button onClick={() => toggle(u)} className={`rounded-full border px-2.5 py-0.5 text-xs ${u.active ? 'border-emerald-500/40 text-emerald-300' : 'border-red-500/40 text-red-300'}`}>{u.active ? 'Active' : 'Disabled'}</button>}</td></tr>)}</tbody></table></div></>}

        {tab === 'Sections' && <>
          <div className="grid lg:grid-cols-2 gap-4">
            <form onSubmit={addSection} noValidate className="rounded-2xl border border-white/10 bg-[#101623] p-6 space-y-3">
              <h2 className="text-lg font-bold">Add Section</h2>
              <p className="text-xs text-slate-400">Examples: CSE-A, CSE-B, CSE-C, ECE-A. The part before the dash becomes the department.</p>
              <label className="block text-sm font-medium">Section name<input value={newSec} onChange={e => setNewSec(e.target.value)} placeholder="CSE-A" className={field} /></label>
              <button className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-medium text-slate-900"><Plus className="size-4" />Add section</button></form>
            <form onSubmit={addBulk} noValidate className="rounded-2xl border border-white/10 bg-[#101623] p-6 space-y-3">
              <h2 className="text-lg font-bold">Add students to a section</h2>
              <label className="block text-sm font-medium">Section<select value={bulk.section_id} onChange={e => setBulk({ ...bulk, section_id: e.target.value })} className={field}><option value="">Choose section</option>{secs.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
              <label className="block text-sm font-medium">Roll numbers (comma, space or new line separated)<textarea value={bulk.rolls} onChange={e => setBulk({ ...bulk, rolls: e.target.value })} rows={3} placeholder="01, 02, 03 ..." className={field} /></label>
              <p className="text-xs text-slate-400">Students must have created an account first.{unassigned > 0 ? ` ${unassigned} student(s) currently have no section.` : ''}</p>
              <button className="inline-flex items-center gap-2 rounded-lg bg-cyan-400 px-5 py-2.5 text-sm font-medium text-slate-900"><Plus className="size-4" />Add students</button></form></div>
          {secMsg && <p role="status" className={`text-sm ${secMsg.ok ? 'text-emerald-300' : 'text-red-400'}`}>{secMsg.text}</p>}
          <div className="overflow-x-auto rounded-2xl border border-white/10 bg-[#101623]"><table className="w-full text-sm"><thead><tr>{['Section', 'Department', 'Students', 'Periods', ''].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
            <tbody>{secs.length === 0 && <tr><td colSpan={5} className="p-4 text-slate-500">No sections yet. Add CSE-A above.</td></tr>}
              {secs.map(x => <tr key={x.id} className="border-t border-white/10"><td className="p-3 font-medium">{x.name}</td><td>{x.department}</td><td className="font-mono">{x.students}</td><td className="font-mono">{x.periods}</td>
                <td className="pr-3 text-right"><button onClick={() => removeSection(x)} aria-label="Delete section" className="text-slate-500 hover:text-red-400"><Trash2 className="size-4" /></button></td></tr>)}</tbody></table></div></>}

        {tab === 'Reports' && <div className="rounded-2xl border border-white/10 bg-[#101623] p-6 space-y-5">
          <div className="flex flex-wrap gap-3">
            <a href={admin.attendanceCsvUrl} className="flex items-center gap-2 rounded-lg bg-cyan-400 px-4 py-2 text-sm font-medium text-slate-900"><Download className="size-4" />Attendance report (CSV)</a>
            <button onClick={async () => { try { setLow((await admin.lowAttendance()).students) } catch (e) { fail(e) } }} className="rounded-lg border border-white/15 px-4 py-2 text-sm">Low-attendance list</button></div>
          {low && (low.length === 0 ? <p className="text-sm text-slate-400">No student is below the attendance threshold.</p>
            : <table className="w-full text-sm"><thead><tr>{['Roll', 'Name', 'Section', 'Present', '%'].map(h => <th key={h} className={th}>{h}</th>)}</tr></thead>
              <tbody>{low.map(s => <tr key={s.roll} className="border-t border-white/10"><td className="p-3 font-mono">{s.roll}</td><td>{s.name}</td><td>{s.section}</td><td className="font-mono">{s.present}/{s.total}</td><td className="font-mono text-red-300">{s.pct}%</td></tr>)}</tbody></table>)}
        </div>}
        <p className="text-xs text-slate-500">Signed in as {user.name}</p>
      </div>
    </div>
  )
}
