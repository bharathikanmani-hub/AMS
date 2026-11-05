import { useEffect, useState } from 'react'
import { ClipboardCheck, CalendarDays, GraduationCap, LayoutDashboard, LogOut, Table2, Sparkles, ShieldCheck, Users, BookOpen, User as UserIcon, Eye, EyeOff } from 'lucide-react'
import { AuthError, emptyDash, forgotPassword, getDashboard, login, logout, me, resetPassword, signup, type Dash, type Role, type User } from './lib/api'
import FaceModule from './FaceModule'
import AdminConsole from './AdminConsole'
import StudentDashboard from './StudentDashboard'
import FacultyRecords from './FacultyRecords'

const roles: { id: Role; label: string; desc: string; icon: React.ReactNode }[] = [
  { id: 'admin', label: 'Admin', desc: 'Institution setup, users, audit', icon: <ShieldCheck className="size-5" /> },
  { id: 'faculty', label: 'Faculty', desc: 'Mark & correct attendance', icon: <BookOpen className="size-5" /> },
  { id: 'student', label: 'Student', desc: 'Your attendance & timetable', icon: <UserIcon className="size-5" /> },
]
const idField: Record<Role, [string, string]> = {
  admin: ['Admin ID or Email', 'Enter Admin ID or email'],
  faculty: ['Faculty ID or Email', 'Enter Faculty ID or email'],
  student: ['Roll Number or Email', 'Enter roll number or email'],
}
type Tab = { name: string; icon: React.ReactNode }
const T = {
  dash: { name: 'Dashboard', icon: <LayoutDashboard className="size-4" /> },
  mark: { name: 'Mark attendance', icon: <ClipboardCheck className="size-4" /> },
  rec: { name: 'Records', icon: <Table2 className="size-4" /> },
  ins: { name: 'Insights', icon: <Sparkles className="size-4" /> },
  tt: { name: 'Timetable', icon: <CalendarDays className="size-4" /> },
  stu: { name: 'Students', icon: <Users className="size-4" /> },
}
const nav: Record<Role, Tab[]> = {
  admin: [T.dash, T.stu, T.rec, T.tt],
  faculty: [T.dash, T.mark, T.rec, T.ins, T.tt],
  student: [T.dash, T.rec, T.tt],
}
const pc = (a: number, b: number) => (b ? Math.round((a / b) * 1000) / 10 : 0)
const THRESHOLD = 75
const Logo = ({ dark = true }: { dark?: boolean }) => (
  <div className={`flex items-center gap-2 font-semibold ${dark ? 'text-white' : 'text-navy'}`}><GraduationCap className="size-5" />AttendAI</div>
)

function Login({ onDone }: { onDone: (u: User) => void }) {
  type View = 'in' | 'up' | 'forgot'
  const [role, setRole] = useState<Role>('student')
  const [view, setView] = useState<View>('in')
  const [ident, setIdent] = useState('')
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [roll, setRoll] = useState('')
  const [pw, setPw] = useState('')
  const [pw2, setPw2] = useState('')
  const [code, setCode] = useState('')
  const [step, setStep] = useState<1 | 2>(1)
  const [show, setShow] = useState(false)
  const [err, setErr] = useState('')
  const [ok, setOk] = useState('')
  const [busy, setBusy] = useState(false)
  const up = view === 'up', forgot = view === 'forgot'
  const [idLabel, idPlaceholder] = idField[role]
  const label = roles.find(r => r.id === role)!.label
  const reset = () => { setErr(''); setOk('') }
  const go = (v: View) => { setView(v); reset(); setPw(''); setPw2(''); setCode(''); setStep(1); if (v === 'up') setRole('student') }
  const emailOk = /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.trim())

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    reset()
    try {
      if (forgot) {
        if (!emailOk) { setErr('Enter a valid e-mail address.'); return }
        if (step === 1) {
          setBusy(true)
          const r = await forgotPassword(email.trim())
          setOk(r.delivery === 'console'
            ? 'E-mail is not set up on this server, so the code was printed in the server (terminal) window.'
            : 'If this e-mail is registered, a 6-digit code has been sent. It is valid for 10 minutes.')
          setStep(2)
        } else {
          if (!/^\d{6}$/.test(code.trim())) { setErr('Enter the 6-digit code from the e-mail.'); return }
          if (pw.length < 8) { setErr('Password must be at least 8 characters.'); return }
          if (pw !== pw2) { setErr('Passwords do not match.'); return }
          setBusy(true)
          const msg = await resetPassword(email.trim(), code.trim(), pw)
          go('in'); setOk(msg)
        }
      } else if (up) {
        if (name.trim().length < 2) { setErr('Enter your full name.'); return }
        if (!emailOk) { setErr('Enter a valid e-mail address.'); return }
        if (role === 'student' && !roll.trim()) { setErr('Roll number is required for students.'); return }
        if (pw.length < 8) { setErr('Password must be at least 8 characters.'); return }
        if (pw !== pw2) { setErr('Passwords do not match.'); return }
        setBusy(true)
        const r = await signup({ name: name.trim(), email: email.trim(), role, rollNumber: role === 'student' ? roll.trim() : undefined, password: pw })
        go('in'); setOk(r.message)
      } else {
        if (!ident.trim() || !pw) { setErr(`${idLabel} and password are required.`); return }
        setBusy(true)
        onDone(await login(ident.trim(), pw, role))
      }
    } catch (x: any) { setErr(x.message) }
    setBusy(false)
  }
  const input = 'mt-1 w-full rounded-lg border bg-white px-3 py-2.5 text-sm font-normal outline-none focus:border-navy'
  const lab = 'block text-sm font-medium text-slate-700'
  const title = forgot ? 'Reset password' : up ? 'Create account' : 'Sign in'
  const sub = forgot ? (step === 1 ? 'Enter your account e-mail and we will send you a 6-digit code.' : 'Enter the code we sent and choose a new password.')
    : up ? 'Tell us who you are and choose a password.' : 'Choose your role, then enter your ID and password.'
  const pwField = (value: string, set: (v: string) => void, text: string, ph: string) => (
    <label className={lab}>{text}
      <div className="relative mt-1"><input type={show ? 'text' : 'password'} value={value} onChange={e => set(e.target.value)} placeholder={ph} autoComplete={view === 'in' ? 'current-password' : 'new-password'} className={input.replace('mt-1 ', '') + ' pr-10'} />
        <button type="button" aria-label={show ? 'Hide password' : 'Show password'} onClick={() => setShow(!show)} className="absolute right-3 top-3 text-slate-500">{show ? <EyeOff className="size-4" /> : <Eye className="size-4" />}</button></div></label>)
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex flex-col justify-between bg-navy p-12 text-white">
        <Logo />
        <div className="max-w-md space-y-5">
          <h1 className="font-serif text-5xl leading-tight font-bold">Attendance, recorded once and understood by everyone.</h1>
        </div>
        <span />
      </div>
      <div className="bg-[#f6f8fb] grid place-items-center p-6">
        <form noValidate onSubmit={submit} className="w-full max-w-md space-y-4">
          <div className="lg:hidden"><Logo dark={false} /></div>
          <div><h2 className="font-serif text-3xl font-bold text-navy">{title}</h2><p className="text-slate-500 text-sm mt-1">{sub}</p></div>
          {!forgot && <div className="inline-flex rounded-xl border bg-white p-1 text-sm">
            {(['in', 'up'] as const).map(m => <button type="button" key={m} onClick={() => go(m)}
              className={`px-5 py-1.5 rounded-lg font-medium ${view === m ? 'bg-navy text-white' : 'text-slate-600'}`}>{m === 'in' ? 'Sign In' : 'Sign Up'}</button>)}</div>}

          {view === 'in' && <>
            <div className="grid grid-cols-3 gap-3">
              {roles.map(r => <button type="button" key={r.id} onClick={() => { setRole(r.id); setIdent(''); reset() }}
                className={`text-left rounded-lg border p-3 transition ${role === r.id ? 'bg-indigo-100 border-indigo-400' : 'bg-white hover:border-slate-300'}`}>
                <span className="text-indigo-600">{r.icon}</span><p className="font-medium text-navy mt-1">{r.label}</p></button>)}
            </div>
            <label className={lab}>{idLabel}<input value={ident} onChange={e => setIdent(e.target.value)} placeholder={idPlaceholder} autoComplete="username" className={input} /></label>
            {pwField(pw, setPw, 'Password', 'Enter your password')}
            <button type="button" onClick={() => go('forgot')} className="text-xs text-indigo-700 underline">Forgot password?</button>
          </>}

          {up && <>
            <label className={lab}>Full name<input value={name} onChange={e => setName(e.target.value)} placeholder="Your full name" autoComplete="name" className={input} /></label>
            <label className={lab}>E-mail<input type="email" value={email} onChange={e => setEmail(e.target.value)} placeholder="you@college.edu" autoComplete="email" className={input} /></label>
            <div><p className={lab}>I am a</p>
              <div className="mt-1 grid grid-cols-3 gap-2">{roles.slice().reverse().map(r => <button type="button" key={r.id} onClick={() => { setRole(r.id); reset() }}
                className={`rounded-lg border px-3 py-2 text-sm font-medium ${role === r.id ? 'bg-indigo-100 border-indigo-400 text-navy' : 'bg-white text-slate-600'}`}>{r.label}</button>)}</div></div>
            {role === 'student' && <label className={lab}>Roll Number<input value={roll} onChange={e => setRoll(e.target.value)} placeholder="Enter Student Roll Number" className={input} /></label>}
            {pwField(pw, setPw, 'Password', 'At least 8 characters')}
            <label className={lab}>Confirm password<input type={show ? 'text' : 'password'} value={pw2} onChange={e => setPw2(e.target.value)} placeholder="Re-enter your password" autoComplete="new-password" className={input} /></label>
            {role !== 'student' && <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-lg p-2.5">{label} accounts must be approved by an administrator before you can sign in.</p>}
          </>}

          {forgot && <>
            <label className={lab}>Account e-mail<input type="email" value={email} onChange={e => setEmail(e.target.value)} disabled={step === 2} placeholder="you@college.edu" autoComplete="email" className={input + ' disabled:bg-slate-100'} /></label>
            {step === 2 && <>
              <label className={lab}>6-digit code<input value={code} onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))} inputMode="numeric" placeholder="123456" autoComplete="one-time-code" className={input + ' font-mono tracking-[.3em]'} /></label>
              {pwField(pw, setPw, 'New password', 'At least 8 characters')}
              <label className={lab}>Confirm new password<input type={show ? 'text' : 'password'} value={pw2} onChange={e => setPw2(e.target.value)} placeholder="Re-enter the new password" autoComplete="new-password" className={input} /></label>
            </>}
          </>}

          {ok && <p role="status" className="text-sm text-emerald-700">{ok}</p>}
          {err && <p role="alert" className="text-sm text-red-600">{err}</p>}
          <button disabled={busy} className="w-full rounded-lg bg-navy py-2.5 font-medium text-white disabled:opacity-60">
            {busy ? 'Please wait…' : forgot ? (step === 1 ? 'Send code' : 'Reset password') : up ? 'Create account' : `Sign in as ${label}`}</button>
          {forgot && <div className="flex justify-between text-xs">
            <button type="button" onClick={() => go('in')} className="text-indigo-700 underline">Back to sign in</button>
            {step === 2 && <button type="button" onClick={() => { setStep(1); setCode(''); reset() }} className="text-indigo-700 underline">Send a new code</button>}</div>}
        </form>
      </div>
    </div>
  )
}

const Card = ({ t, v, s, c = '' }: { t: string; v: React.ReactNode; s?: string; c?: string }) => (
  <div className="rounded-xl border bg-white p-5 shadow-sm"><p className="text-xs tracking-wider text-slate-500 uppercase">{t}</p><p className={`text-3xl font-semibold mt-1 ${c || 'text-navy'}`}>{v}</p>{s && <p className="text-xs text-slate-500 mt-1">{s}</p>}</div>
)
const Panel = ({ title, sub, children }: { title: string; sub?: string; children: React.ReactNode }) => (
  <section className="rounded-xl border bg-white p-6 shadow-sm"><h2 className="font-semibold text-navy">{title}</h2>{sub && <p className="text-sm text-slate-500">{sub}</p>}<div className="mt-4">{children}</div></section>
)
const Table = ({ head, rows }: { head: string[]; rows: (string | number)[][] }) => (
  <div className="overflow-x-auto rounded-xl border bg-white"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr>{head.map(h => <th key={h} className="p-3 font-medium">{h}</th>)}</tr></thead>
    <tbody>{rows.map((r, i) => <tr key={i} className="border-t">{r.map((c, j) => <td key={j} className="p-3">{c}</td>)}</tr>)}</tbody></table></div>
)
const Pill = ({ ok, children }: { ok: boolean; children: React.ReactNode }) => (
  <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${ok ? 'bg-emerald-100 text-emerald-700' : 'bg-red-100 text-red-700'}`}>{children}</span>
)

function Shell({ user, onOut }: { user: User; onOut: () => void }) {
  const [tab, setTab] = useState('Dashboard')
  const [d, setD] = useState<Dash>(emptyDash)
  const [loadErr, setLoadErr] = useState('')
  useEffect(() => {  // real data from MySQL, refreshed every 20 s so new attendance shows up
    let stop = false
    const load = () => getDashboard().then(r => { if (!stop) { setD(r); setLoadErr('') } })
      .catch(e => { if (e instanceof AuthError) onOut(); else if (!stop) setLoadErr(e.message || 'Could not load data.') })
    load(); const id = window.setInterval(load, 20000)
    return () => { stop = true; window.clearInterval(id) }
  }, [])
  const att = d.subjects.reduce((s, x) => s + x.present, 0), held = d.subjects.reduce((s, x) => s + x.total, 0)
  const overall = pc(att, held)
  const canMiss = Math.max(0, Math.floor(att / (THRESHOLD / 100) - held))
  const first = user.name.split(' ').filter(w => !/^prof\.?$/i.test(w))[0] ?? user.name
  const faceTab = tab === 'Mark attendance'
  const risk = d.students.filter(s => s.pct < 80)
  return (
    <div className="min-h-screen flex flex-col md:flex-row bg-[#f6f8fb]">
      <aside className="md:w-60 shrink-0 bg-navy text-white p-3 flex md:flex-col gap-1 overflow-x-auto">
        <div className="px-3 py-3 md:mb-3"><Logo /></div>
        {nav[user.role].map(n => <button key={n.name} onClick={() => setTab(n.name)}
          className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm whitespace-nowrap ${tab === n.name ? 'bg-white/10' : 'text-slate-300 hover:bg-white/5'}`}>{n.icon}{n.name}</button>)}
      </aside>
      <div className="flex-1 min-w-0">
        <header className="bg-white border-b px-5 md:px-8 py-3 flex items-center justify-between">
          <span />
          <div className="flex items-center gap-4"><div className="text-right text-sm"><p className="font-medium text-navy">{user.name}</p><p className="text-xs text-slate-500 capitalize">{user.identifier ? `${user.role} · ${user.identifier}` : user.role}</p></div>
            <button onClick={onOut} className="flex items-center gap-2 rounded-lg border px-3 py-1.5 text-sm font-medium"><LogOut className="size-4" />Sign out</button></div>
        </header>
        <main className="p-5 md:p-8 space-y-6">
          {loadErr && <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">Could not load your data: {loadErr}</p>}
          {faceTab && <FaceModule />}
          {tab === 'Dashboard' && <>
            <div className="flex items-end justify-between"><div><h1 className="font-serif text-3xl font-bold text-navy">{user.role === 'faculty' ? 'Good day' : 'Hello'}, {first}</h1>
              <p className="text-slate-500 text-sm mt-1">{new Date().toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' })}</p></div>
              {user.role === 'faculty' && <button onClick={() => setTab('Mark attendance')} className="rounded-lg bg-navy px-4 py-2 text-sm font-medium text-white">Mark attendance</button>}</div>
            <div className="grid sm:grid-cols-3 gap-4">
              <Card t={user.role === 'student' ? 'Overall attendance' : 'Avg attendance'} v={`${overall}%`} s={`${att} attended of ${held} classes`} c={overall >= THRESHOLD ? 'text-emerald-700' : 'text-red-600'} />
              <Card t={user.role === 'student' ? 'Can still miss' : 'Students to watch'} v={user.role === 'student' ? canMiss : risk.length} s={user.role === 'student' ? `to stay at or above ${THRESHOLD}%` : `below 80% attendance`} />
              <Card t="Subjects" v={d.subjects.length} />
            </div>
            <div className="grid gap-6">
              {user.role === 'faculty' && <Panel title="Recent classes" sub="Present and absent students in your latest classes">{d.recent.length === 0 && <p className="text-sm text-slate-500">No class has been marked yet.</p>}{d.recent.map((r, i) => <div key={i} className="flex justify-between gap-3 py-2.5 border-b last:border-0 text-sm"><span>{r[0]}</span><span className="font-medium text-navy whitespace-nowrap">{r[1]}</span></div>)}</Panel>}
              {user.role === 'student'
                ? <Panel title="Recent records">{d.recent.map((r, i) => <div key={i} className="flex justify-between py-2.5 border-b last:border-0 text-sm"><span>{r[0]}</span><Pill ok={r[1] === 'Present'}>{r[1]}</Pill></div>)}</Panel>
                : <Panel title="Students to watch" sub="By heuristic risk rules">{d.students.length === 0 && <p className="text-sm text-slate-500">No attendance has been recorded yet. Mark attendance to see students here.</p>}{d.students.map(s => <div key={s.roll} className="flex justify-between py-2.5 border-b last:border-0 text-sm"><span>{s.name} <span className="text-slate-400">{s.roll}</span></span>
                    <span className="flex items-center gap-2">{s.pct}% <span className={`rounded-full px-2 py-0.5 text-xs ${s.pct < THRESHOLD ? 'bg-red-100 text-red-700' : 'bg-amber-100 text-amber-700'}`}>{s.pct < THRESHOLD ? 'High risk' : 'Watch'}</span></span></div>)}</Panel>}
            </div></>}
          {tab === 'Students' && <><h1 className="font-serif text-3xl font-bold text-navy">Students</h1><Table head={['Roll', 'Name', 'Attendance']} rows={d.students.map(s => [s.roll, s.name, `${s.pct}%`])} /></>}
          {tab === 'Records' && <><h1 className="font-serif text-3xl font-bold text-navy">Records</h1><FacultyRecords onAuthError={onOut} /></>}
          {tab === 'Timetable' && <><h1 className="font-serif text-3xl font-bold text-navy">Timetable</h1><Table head={['Day', 'Time', 'Subject', 'Room']} rows={d.timetable} /></>}
          {tab === 'Insights' && <><h1 className="font-serif text-3xl font-bold text-navy">Insights</h1><Panel title="Low-attendance alerts" sub={`Students below ${THRESHOLD}%`}>{d.students.filter(s => s.pct < THRESHOLD).map(s => <p key={s.roll} className="text-sm py-1">{s.name} ({s.roll}): {s.pct}%</p>)}</Panel></>}
        </main>
      </div>
    </div>
  )
}

export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [checking, setChecking] = useState(true)
  // After a page refresh the server session is still valid: restore it instead of asking to sign in again.
  useEffect(() => { me().then(u => { if (u) setUser(u) }).finally(() => setChecking(false)) }, [])
  if (checking) return <div className="min-h-screen grid place-items-center bg-[#f6f8fb] text-sm text-slate-500">Loading…</div>
  if (user?.role === 'admin') return <AdminConsole user={user} onOut={() => { logout(); setUser(null) }} />
  if (user?.role === 'student') return <StudentDashboard user={user} onOut={() => { logout(); setUser(null) }} />
  return user ? <Shell user={user} onOut={() => { logout(); setUser(null) }} /> : <Login onDone={setUser} />
}
