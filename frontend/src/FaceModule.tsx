import { useLive } from './lib/useLive'
import { AuthError, enroll, type EnrollStudent, type LiveFace } from './lib/api'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Camera, LogIn, LogOut, Users, UserCheck } from 'lucide-react'
import FacultyRecords from './FacultyRecords'

const Stat = ({ t, v, i }: { t: string; v: string | number; i?: React.ReactNode }) => (
  <div className="rounded-xl border border-white/10 bg-[#101826] p-4">
    <div className="flex justify-between text-[11px] tracking-widest text-slate-400 uppercase">{t}{i}</div>
    <div className="mt-2 font-mono text-2xl text-white">{v}</div></div>
)
type CamApi = { videoRef: React.RefObject<HTMLVideoElement | null>; on: boolean; error: string; start: () => Promise<boolean>; stop: () => void }
function useCamera(): CamApi {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [on, setOn] = useState(false)
  const [error, setError] = useState('')
  const stop = () => { streamRef.current?.getTracks().forEach(t => t.stop()); streamRef.current = null; setOn(false) }
  const start = async () => {
    setError('')
    if (streamRef.current) return true
    try {
      const st = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480, facingMode: 'user' }, audio: false })
      streamRef.current = st; setOn(true)
      requestAnimationFrame(() => { if (videoRef.current) { videoRef.current.srcObject = st; videoRef.current.play().catch(() => {}) } })
      return true
    } catch (e: any) {
      setError(e?.name === 'NotAllowedError' ? (window.self !== window.top ? 'Camera is blocked. This preview is embedded in a frame that does not allow camera access. Open the app in its own browser tab, then allow the camera.' : 'Camera permission was denied. Click the camera/lock icon in the address bar, set Camera to Allow, then reload.') : e?.name === 'NotFoundError' ? 'No camera found on this device.' : e?.name === 'NotReadableError' ? 'The camera is in use by another app. Close it and retry.' : 'Could not start the camera.')
      return false
    }
  }
  useEffect(() => stop, [])
  return { videoRef, on, error, start, stop }
}
const Cam = ({ cam, big, note, blocked }: { cam: CamApi; big?: boolean; note?: string; blocked?: string }) => (
  <div className={`relative overflow-hidden rounded-xl border border-white/10 bg-[#03060c] grid place-items-center text-slate-400 ${big ? 'min-h-80' : 'min-h-64'}`}>
    <video ref={cam.videoRef} muted playsInline className={`absolute inset-0 size-full object-cover -scale-x-100 ${cam.on ? '' : 'hidden'}`} />
    {!cam.on && <div className="text-center space-y-2 p-4"><Camera className="mx-auto size-8 text-slate-500" /><p className="text-sm">Camera is off</p>
      <button onClick={cam.start} disabled={!!blocked} className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950 disabled:opacity-40 disabled:cursor-not-allowed"><Camera className="size-4" />Start Camera</button>
      {blocked && <p className="text-xs text-amber-400">{blocked}</p>}
      {cam.error && <p className="text-xs text-red-400 max-w-xs">{cam.error}</p>}
      {note && <p className="text-xs text-slate-500">{note}</p>}</div>}
  </div>
)

const fmtTime = (iso: string | null) => iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '—'
const faceStyle: Record<LiveFace['state'], string> = {
  entered: 'border-emerald-400', already_inside: 'border-emerald-400/60', exited: 'border-sky-400', just_exited: 'border-sky-400/60',
  not_inside: 'border-amber-400', unknown: 'border-amber-400',
  not_in_section: 'border-orange-400', not_in_subject: 'border-orange-400', no_section: 'border-orange-400', unregistered: 'border-slate-400',
}
const faceLabel = (f: LiveFace) =>
  f.state === 'entered' ? `${f.name ?? f.roll_number} · Entry marked`
  : f.state === 'already_inside' ? `${f.name ?? f.roll_number} · already inside (press Exit to leave)`
  : f.state === 'exited' ? `${f.name ?? f.roll_number} · Exit marked`
  : f.state === 'just_exited' ? `${f.name ?? f.roll_number} · exited`
  : f.state === 'not_inside' ? `${f.name ?? f.roll_number} · no entry yet, Exit not available`
  : f.state === 'not_in_section' ? `${f.roll_number} · not in this section`
  : f.state === 'not_in_subject' ? `${f.name ?? f.roll_number} · not in this subject`
  : f.state === 'no_section' ? `${f.name ?? f.roll_number} · no section assigned`
  : f.state === 'unregistered' ? 'Not registered' : 'Unknown'
// Camera panel for Live Attendance: draws a box (mirrored to match the mirrored video) around every face.
function LiveCam({ cam, faces, blocked, onStart }: { cam: CamApi; faces: LiveFace[]; blocked?: string; onStart: () => void }) {
  const [aspect, setAspect] = useState(4 / 3)
  return (
    <div className="relative w-full overflow-hidden rounded-xl border border-white/10 bg-[#03060c] grid place-items-center text-slate-400" style={{ aspectRatio: aspect }}>
      <video ref={cam.videoRef} muted playsInline onLoadedMetadata={e => { const v = e.currentTarget; if (v.videoWidth) setAspect(v.videoWidth / v.videoHeight) }}
        className={`absolute inset-0 size-full object-cover -scale-x-100 ${cam.on ? '' : 'hidden'}`} />
      {cam.on && faces.map((f, i) => (
        <div key={i} className={`absolute rounded-md border-2 ${faceStyle[f.state]}`}
          style={{ left: `${(1 - f.box.x - f.box.w) * 100}%`, top: `${f.box.y * 100}%`, width: `${f.box.w * 100}%`, height: `${f.box.h * 100}%` }}>
          <span className="absolute left-0 top-0 max-w-full truncate rounded-br bg-black/70 px-1.5 py-0.5 font-mono text-[11px] text-white">{faceLabel(f)}</span>
        </div>))}
      {!cam.on && <div className="text-center space-y-2 p-4"><Camera className="mx-auto size-8 text-slate-500" /><p className="text-sm">Camera is off</p>
        <button onClick={onStart} disabled={!!blocked} className="inline-flex items-center gap-2 rounded-md bg-emerald-500 px-3 py-1.5 text-sm font-medium text-emerald-950 disabled:opacity-40 disabled:cursor-not-allowed"><Camera className="size-4" />Start Camera</button>
        {blocked && <p className="text-xs text-amber-400">{blocked}</p>}
        {cam.error && <p className="text-xs text-red-400 max-w-xs mx-auto">{cam.error}</p>}</div>}
    </div>
  )
}

const TARGET = 8 // samples per student; each is embedded and stored by the server immediately, so saving is instant

export default function FaceModule() {
  const [tab, setTab] = useState<'Live Attendance' | 'Enroll' | 'Attendance Records'>('Live Attendance')
  const cam = useCamera()
  const L = useLive(cam)
  const [shots, setShots] = useState<string[]>([])
  const [capturing, setCapturing] = useState(false)
  const [msg, setMsg] = useState('')
  const [roster, setRoster] = useState<EnrollStudent[]>([])
  const [mySections, setMySections] = useState<{ id: number; name: string }[]>([])
  const [search, setSearch] = useState('')
  const [studentId, setStudentId] = useState<number | null>(null)
  const [fullName, setFullName] = useState('')
  const [sectionId, setSectionId] = useState('')
  const [consent, setConsent] = useState(false)
  const [saving, setSaving] = useState(false)
  const [done, setDone] = useState('')
  const timer = useRef<number | null>(null)
  const running = useRef(false)
  const [replace, setReplace] = useState(false)
  const [canReplace, setCanReplace] = useState(false)
  const busy = useRef(false)
  const finishing = useRef(false)
  const accepted = useRef(0)
  const latest = useRef({ fullName: '', sectionId: '' })
  latest.current = { fullName, sectionId }       // read at save time (the capture timer outlives this render)
  const selected = roster.find(x => x.id === studentId) ?? null
  const halt = () => { running.current = false; if (timer.current) clearInterval(timer.current); timer.current = null; setCapturing(false) }
  useEffect(() => halt, [])

  const loadRoster = useCallback(async (q = '') => {
    try { const r = await enroll.students(q); setRoster(r.students); setMySections(r.sections); setCanReplace(!!r.can_replace) } catch (e: any) { setMsg(e.message || 'Could not load students.') }
  }, [])
  useEffect(() => {  // load / search students from the database while the Enroll tab is open
    if (tab !== 'Enroll') return
    const id = window.setTimeout(() => loadRoster(search.trim()), 250)
    return () => window.clearTimeout(id)
  }, [tab, search, loadRoster])
  const pick = (id: number | null) => {
    halt(); setReplace(false); setStudentId(id); setShots([]); accepted.current = 0; setDone(''); setMsg(''); setSectionId('')
    const st = roster.find(x => x.id === id)
    setFullName(st && st.name !== st.roll_number ? st.name : '')
  }
  const grab = (): Promise<Blob | null> => {
    const v = cam.videoRef.current
    if (!v || !v.videoWidth) return Promise.resolve(null)
    const w = Math.min(v.videoWidth, 640), c = document.createElement('canvas')
    c.width = w; c.height = Math.round((v.videoHeight / v.videoWidth) * w)
    c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height)   // real (un-mirrored) frame, same as a normal camera photo
    return new Promise(res => c.toBlob(res, 'image/jpeg', 0.8))
  }
  const snap = async () => {  // the SERVER validates the frame (one clear face, not another student) and saves it to dataset/<roll>/
    if (busy.current || studentId == null) return false
    busy.current = true
    try {
      const blob = await grab()
      if (!blob) return false
      const r = await enroll.sample(studentId, blob, { fresh: accepted.current === 0, replace: replace && accepted.current === 0 })
      if (!r.accepted) { setMsg(r.message); return false }
      setShots(p => [...p, URL.createObjectURL(blob)]); accepted.current += 1; setMsg('')
      return true
    } catch (e: any) { if (e instanceof AuthError) { halt(); setMsg('Session expired. Please sign in again.') } else setMsg(e.message || 'Capture failed.'); return false }
    finally { busy.current = false }
  }
  const finish = async () => {
    if (studentId == null || finishing.current) return
    finishing.current = true; setSaving(true); setMsg('')
    try {
      const { fullName: nm, sectionId: sec } = latest.current
      const r = await enroll.finish(studentId, { name: nm.trim() || undefined, section_id: sec ? Number(sec) : undefined })
      setDone(r.message); loadRoster(search.trim())
    } catch (e: any) { setMsg(e.message || 'Could not save the enrolment.') }
    finishing.current = false; setSaving(false)
  }
  const startEnroll = async () => {
    if (capturing) return
    if (studentId == null) { setMsg('Select a student first.'); return }
    if (!consent) { setMsg('Please confirm that the student has given consent.'); return }
    setShots([]); accepted.current = 0; setDone(''); setMsg('Turn your head slightly left, right, up and down between captures.')
    if (!(await cam.start())) return
    setCapturing(true); running.current = true
    let fails = 0   // back-to-back captures (no fixed 1.2 s wait): the next frame is sent as soon as the last one is saved
    while (running.current && accepted.current < TARGET && fails < 40) {
      const ok = await snap()
      fails = ok ? 0 : fails + 1
      await new Promise(r => setTimeout(r, ok ? 150 : 300))
    }
    if (!running.current) return
    halt(); cam.stop()
    if (accepted.current >= 5) await finish(); else setMsg('Could not capture enough clear photos. Improve the lighting and try again.')
  }
  const goTab = (t: typeof tab) => {
    halt()
    if (tab === 'Live Attendance' && t !== 'Live Attendance') L.pause()      // stops the frame loop AND the camera
    else if (t !== 'Live Attendance' && t !== 'Enroll') cam.stop()
    if (t === 'Live Attendance' && tab === 'Enroll') cam.stop()
    setTab(t)
  }
  return (
    <div className="-m-5 md:-m-8 min-h-screen bg-[#0a0e16] text-slate-100">
      <div className="border-b border-white/10">
        <div className="mx-auto max-w-6xl px-5 py-3 flex items-center justify-end">
          <nav className="flex gap-1 text-sm">{(['Live Attendance', 'Enroll', 'Attendance Records'] as const).map(t =>
            <button key={t} onClick={() => goTab(t)} className={`px-3 py-1.5 rounded-lg ${tab === t ? 'bg-emerald-500/15 text-emerald-400' : 'text-slate-400 hover:text-white'}`}>{t}</button>)}</nav>
        </div></div>
      <div className="mx-auto max-w-6xl px-5 py-8 space-y-6">
        {tab === 'Live Attendance' && <>
          <h1 className="text-3xl font-semibold">Live Attendance</h1>
          <p className="text-slate-400 text-sm max-w-xl">Choose <b>Entry</b> or <b>Exit</b>, then start the camera. Each period is 45 minutes; a student with less than 20 minutes in class is marked absent. A student must press Exit after Entry, and cannot enter again until they have exited.</p>
          {L.running && L.outside && <p role="status" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-300">This class is running outside its timetable period. Attendance is still being recorded.</p>}
          {L.options && !L.options.recognition_ready && <p role="alert" className="rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-300">Face recognition is not ready: {L.options.recognition_message}</p>}
          {L.options && L.options.subjects.length === 0 && <p className="rounded-lg border border-white/10 bg-[#101623] p-3 text-sm text-slate-300">No subjects are assigned to your account yet. Ask the administrator to assign you a subject and section.</p>}
          <div className="rounded-xl border border-white/10 bg-[#101623] p-5 grid sm:grid-cols-3 gap-4 text-sm">
            <label className="sm:col-span-2 font-medium">Subject for this attendance session
              <select value={L.subjectId ?? ''} onChange={e => { L.setSubjectId(e.target.value ? Number(e.target.value) : null); if (cam.on) L.pause() }} className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#0a0e16] px-3 py-2.5 text-slate-100">
                <option value="">{L.loadingOptions ? 'Loading…' : 'Select subject'}</option>{L.options?.subjects.map(x => <option key={x.id} value={x.id}>{x.code} · {x.name}</option>)}</select></label>
            <label className="font-medium">Section
              <select value={L.sectionId ?? ''} onChange={e => { L.setSectionId(Number(e.target.value)); if (cam.on) L.pause() }} disabled={!L.sections.length} className="mt-1.5 w-full rounded-lg border border-white/10 bg-[#0a0e16] px-3 py-2.5 text-slate-100 disabled:opacity-50">
                {!L.sections.length && <option value="">—</option>}{L.sections.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>
            {L.subjectId != null && L.sectionId != null && <p className="sm:col-span-3 text-xs text-emerald-300">Marking attendance for {L.options?.subjects.find(x => x.id === L.subjectId)?.name} · {L.sections.find(x => x.id === L.sectionId)?.name}</p>}</div>
          <div className="grid grid-cols-2 gap-3 max-w-xl" role="group" aria-label="Entry or Exit">
            <button type="button" onClick={() => L.setMode('entry')} aria-pressed={L.mode === 'entry'}
              className={`flex items-center justify-center gap-2 rounded-xl border px-4 py-4 text-lg font-semibold ${L.mode === 'entry' ? 'border-emerald-400 bg-emerald-500/20 text-emerald-200' : 'border-white/10 bg-[#101623] text-slate-300 hover:border-white/30'}`}><LogIn className="size-5" />Entry</button>
            <button type="button" onClick={() => L.setMode('exit')} aria-pressed={L.mode === 'exit'}
              className={`flex items-center justify-center gap-2 rounded-xl border px-4 py-4 text-lg font-semibold ${L.mode === 'exit' ? 'border-sky-400 bg-sky-500/20 text-sky-200' : 'border-white/10 bg-[#101623] text-slate-300 hover:border-white/30'}`}><LogOut className="size-5" />Exit</button>
            {L.mode == null && <p className="col-span-2 text-xs text-amber-300">Select Entry or Exit to begin.</p>}
          </div>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4"><Stat t="Faces in frame" v={L.facesInFrame} /><Stat t="Present" v={L.present} i={<Users className="size-4 text-emerald-400" />} /><Stat t="Inside now" v={L.inside} /><Stat t="Enrolled students" v={L.enrolled} i={<UserCheck className="size-4 text-indigo-400" />} /></div>
          <div className="grid lg:grid-cols-3 gap-4"><div className="lg:col-span-2 space-y-3">
            <LiveCam cam={cam} faces={L.faces} onStart={L.begin} blocked={L.subjectId == null || L.sectionId == null ? 'Select a subject before starting the camera.' : L.mode == null ? 'Choose Entry or Exit first.' : undefined} />
            {(cam.on || L.sessionId != null) && <div className="flex flex-wrap items-center gap-2 text-sm">
              {cam.on && <button onClick={L.pause} className="rounded-md bg-white/5 px-3 py-1.5 text-slate-300">Stop camera</button>}
              {L.sessionId != null && !L.ended && <button onClick={() => { if (window.confirm('End this class? Students still inside are exited now. Students who never entered, or were in class for less than 20 minutes, are marked absent.')) L.finish() }} className="rounded-md bg-red-500/15 px-3 py-1.5 text-red-300">End class</button>}
              {L.ended && <span className="text-xs text-slate-400">Class ended. Records are final.</span>}</div>}
            {L.error && <p role="alert" className="text-xs text-red-400">{L.error}</p>}</div>
            <div className="rounded-xl border border-white/10 bg-[#101826] p-5"><h2 className="font-semibold">Present in this class</h2>
              {L.subjectId != null && L.sectionId != null && <p className="text-xs text-emerald-300 mt-1">{L.options?.subjects.find(x => x.id === L.subjectId)?.name} · {L.sections.find(x => x.id === L.sectionId)?.name}</p>}
              {L.records.filter(r => r.status === 'present' || r.status === 'late').length === 0 && <p className="mt-4 text-sm text-slate-500">No one has entered yet.</p>}
              {L.records.filter(r => r.status === 'present' || r.status === 'late').map(e => <div key={e.roll_number} className="flex justify-between items-center py-3 border-b border-white/5 last:border-0"><div><p className="font-medium">{e.name}</p><p className="font-mono text-xs text-slate-400">{e.roll_number} · {e.subject}</p></div>
                <div className="text-right font-mono text-xs"><p className="text-emerald-300">In {fmtTime(e.entry)}</p><p className={e.inside ? 'text-slate-500' : 'text-sky-300'}>{e.inside ? 'inside' : `Out ${fmtTime(e.exit)}`}</p></div></div>)}</div></div></>}
        {tab === 'Enroll' && <>
          <h1 className="text-3xl font-semibold">Enroll Students</h1>
          <p className="text-slate-400 text-sm max-w-2xl">Pick a student who has created an account, then capture face samples: front, slight left and right, up, down. Each sample is checked by the server (exactly one clear face) and saved to the face dataset. Enrolment is one-time, permanent and requires student consent.</p>
          <div className="grid lg:grid-cols-5 gap-4"><div className="lg:col-span-3 space-y-3"><Cam cam={cam} big blocked={studentId == null ? 'Select a student first.' : !consent ? 'Tick the consent box first.' : undefined} />
            <div className="flex flex-wrap gap-2 text-sm">
              <button disabled={studentId == null || !consent} onClick={async () => { if (await cam.start()) snap() }} className="rounded-md bg-white/5 px-3 py-1.5 text-slate-300 disabled:opacity-40">Capture Sample</button>
              {cam.on && <button onClick={() => { halt(); cam.stop() }} className="rounded-md bg-white/5 px-3 py-1.5 text-slate-300">Stop Camera</button>}</div>
            <div className="grid grid-cols-5 gap-2">{Array.from({ length: TARGET }).map((_, i) => shots[i]
              ? <img key={i} src={shots[i]} alt={`Sample ${i + 1}`} className="aspect-square rounded-lg object-cover -scale-x-100" />
              : <div key={i} className="aspect-square rounded-lg border border-dashed border-white/15" />)}</div></div>
            <div className="lg:col-span-2 rounded-xl border border-white/10 bg-[#101826] p-5 space-y-3 text-sm"><h2 className="font-semibold">Student</h2>
              <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search roll number or name…" className="w-full rounded-md bg-[#0a0e16] border border-white/10 px-3 py-2 placeholder:text-slate-500" />
              <select value={studentId ?? ''} onChange={e => pick(e.target.value ? Number(e.target.value) : null)} className="w-full rounded-md bg-[#0a0e16] border border-white/10 px-3 py-2">
                <option value="">{roster.length ? 'Select a student' : 'No students found'}</option>
                {roster.map(x => <option key={x.id} value={x.id}>{x.roll_number}{x.name !== x.roll_number ? ` · ${x.name}` : ''}{x.enrolled ? ' ✓ enrolled' : ''}</option>)}</select>
              {selected && <p className="text-xs text-slate-400">Roll {selected.roll_number} · {selected.section ?? 'no section yet'} · {selected.samples} photo(s) already in dataset{selected.enrolled ? ' · face already enrolled (saved permanently)' : ''}</p>}
              {selected?.enrolled && canReplace && !capturing && <label className="flex items-center gap-2 text-xs text-amber-300"><input type="checkbox" checked={replace} onChange={e => setReplace(e.target.checked)} />Admin: replace this student's existing face (re-enrol)</label>}
              {selected && <input value={fullName} onChange={e => setFullName(e.target.value)} placeholder="Student's full name" className="w-full rounded-md bg-[#0a0e16] border border-white/10 px-3 py-2 placeholder:text-slate-500" />}
              {selected && !selected.section_id && <label className="block text-xs text-slate-400">Assign to section (needed for attendance)
                <select value={sectionId} onChange={e => setSectionId(e.target.value)} className="mt-1 w-full rounded-md bg-[#0a0e16] border border-white/10 px-3 py-2 text-sm text-slate-100"><option value="">Choose section</option>{mySections.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select></label>}
              <label className="flex items-start gap-2 text-xs text-slate-300"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} className="mt-0.5" />The student has given consent to store their face photos for attendance.</label>
              <button disabled={saving || (!!selected?.enrolled && !replace)} onClick={capturing ? halt : startEnroll} className="w-full rounded-md bg-emerald-600 px-3 py-2 font-medium disabled:opacity-50">{saving ? 'Saving…' : selected?.enrolled && !replace ? 'Already enrolled' : capturing ? `Capturing ${shots.length}/${TARGET}… (stop)` : shots.length >= TARGET ? 'Capture again' : 'Enroll (start capturing faces)'}</button>
              {!capturing && !saving && !done && shots.length >= 5 && shots.length < TARGET && <button onClick={() => { cam.stop(); finish() }} className="w-full rounded-md bg-white/10 px-3 py-2">Save with {shots.length} samples</button>}
              {msg && <p role="alert" className="text-xs text-amber-300">{msg}</p>}
              {done && <p role="status" className="text-xs text-emerald-300">{done}</p>}
              <p className="text-xs text-slate-500">{shots.length} of {TARGET} samples captured in this session. Photos are saved to the dataset folder and the face database is updated automatically.</p></div></div></>}

        {tab === 'Attendance Records' && <>
          <h1 className="text-3xl font-semibold">Attendance Records</h1>
          <p className="text-slate-400 text-sm">Saved permanently in the database. Pick a date to see every class you took, with present and absent students.</p>
          <FacultyRecords dark /></>}
      </div></div>
  )
}
