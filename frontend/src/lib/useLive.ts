// Live Attendance logic: subject/section choices, Entry / Exit mode, session, frame loop, records.
// It reuses the camera object from FaceModule's useCamera() so there is only one camera.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { live, type LiveFace, type LiveOptions, type LiveRecord, type LiveSummary, type Mode } from './api'

const FRAME_INTERVAL_MS = 600 // ~2 frames/second is plenty for attendance
const FRAME_WIDTH = 640
const JPEG_QUALITY = 0.85

export type CamLike = {
  videoRef: React.RefObject<HTMLVideoElement | null>
  start: () => Promise<boolean>
  stop: () => void
}
const emptySummary: LiveSummary = { present: 0, absent: 0, total: 0, inside: 0, period_minutes: 45, min_minutes: 20 }

export function useLive(cam: CamLike) {
  const timer = useRef<number | null>(null)
  const busy = useRef(false)          // never send a new frame while one is still in flight
  const sessionRef = useRef<number | null>(null)
  const modeRef = useRef<Mode | null>(null)

  const [options, setOptions] = useState<LiveOptions | null>(null)
  const [subjectId, setSubjectId] = useState<number | null>(null)
  const [sectionId, setSectionId] = useState<number | null>(null)
  const [sessionId, setSessionId] = useState<number | null>(null)
  const [mode, setModeState] = useState<Mode | null>(null)
  const [running, setRunning] = useState(false)
  const [faces, setFaces] = useState<LiveFace[]>([])
  const [present, setPresent] = useState(0)
  const [inside, setInside] = useState(0)
  const [enrolled, setEnrolled] = useState(0)
  const [records, setRecords] = useState<LiveRecord[]>([])
  const [summary, setSummary] = useState<LiveSummary>(emptySummary)
  const [outside, setOutside] = useState(false)
  const [ended, setEnded] = useState(false)
  const [error, setError] = useState('')
  const [loadingOptions, setLoadingOptions] = useState(true)

  useEffect(() => {
    live.options().then(setOptions).catch(e => setError(e.message)).finally(() => setLoadingOptions(false))
  }, [])

  const sections = useMemo(() => {
    const subj = options?.subjects.find(s => s.id === subjectId)
    return subj && options ? options.sections.filter(s => subj.section_ids.includes(s.id)) : []
  }, [options, subjectId])
  useEffect(() => {
    if (sections.length && !sections.some(s => s.id === sectionId)) setSectionId(sections[0].id)
    if (!sections.length) setSectionId(null)
  }, [sections, sectionId])

  const refreshRecords = useCallback(async () => {
    const id = sessionRef.current
    if (id == null) return
    try {
      const r = await live.records(id)
      setRecords(r.records); setSummary(r.summary); setInside(r.summary.inside); setPresent(r.summary.present)
      setEnded(r.session_status === 'completed')
    } catch { /* keep the last good list */ }
  }, [])

  const grab = useCallback((): Promise<Blob | null> => {
    const v = cam.videoRef.current
    if (!v || !v.videoWidth) return Promise.resolve(null)
    const c = document.createElement('canvas')
    c.width = FRAME_WIDTH
    c.height = Math.round((v.videoHeight / v.videoWidth) * FRAME_WIDTH)
    c.getContext('2d')!.drawImage(v, 0, 0, c.width, c.height)   // un-mirrored: the server sees the real frame
    return new Promise(res => c.toBlob(res, 'image/jpeg', JPEG_QUALITY))
  }, [cam.videoRef])

  const halt = useCallback(() => {
    if (timer.current != null) window.clearInterval(timer.current)
    timer.current = null
    setRunning(false); setFaces([])
  }, [])

  const tick = useCallback(async () => {
    const id = sessionRef.current
    const m = modeRef.current
    if (busy.current || id == null || m == null) return
    busy.current = true
    try {
      const blob = await grab()
      if (!blob) return
      const r = await live.frame(id, blob, m)
      setError('')
      setFaces(r.faces); setPresent(r.present_count); setInside(r.inside_count); setOutside(r.outside_schedule)
      if (r.newly_marked > 0) refreshRecords()
    } catch (e: any) {
      setError(e.message || 'Frame failed.')
      if (/ended|session expired|not your session/i.test(e.message || '')) { halt(); cam.stop() }
    } finally { busy.current = false }
  }, [grab, refreshRecords, halt, cam])

  /** Choose Entry or Exit. It can be switched at any time while the camera is running. */
  const setMode = useCallback((m: Mode) => { modeRef.current = m; setModeState(m); setFaces([]) }, [])

  /** "Start Camera": open (or resume) today's session, then the camera, then the frame loop. Needs Entry or Exit. */
  const begin = useCallback(async () => {
    if (subjectId == null || sectionId == null) { setError('Select a subject before starting the camera.'); return }
    if (modeRef.current == null) { setError('Choose Entry or Exit first.'); return }
    if (timer.current != null) return
    setError('')
    try {
      const s = await live.start(subjectId, sectionId)
      sessionRef.current = s.session.id
      setSessionId(s.session.id); setPresent(s.present_count); setEnrolled(s.enrolled_count); setEnded(false)
    } catch (e: any) { setError(e.message); return }
    if (!(await cam.start())) return                      // useCamera shows its own permission error
    setRunning(true)
    refreshRecords()
    timer.current = window.setInterval(tick, FRAME_INTERVAL_MS)
  }, [subjectId, sectionId, cam, tick, refreshRecords])

  /** Turn the camera off but keep the session open (you can resume it). */
  const pause = useCallback(() => { halt(); cam.stop() }, [halt, cam])

  /** End the class: open entries are closed, students under 20 minutes or never seen become absent. */
  const finish = useCallback(async () => {
    pause()
    const id = sessionRef.current
    if (id == null) return
    try { await live.end(id) } catch (e: any) { setError(e.message) }
    await refreshRecords()
  }, [pause, refreshRecords])

  useEffect(() => halt, [halt])  // stop the loop if the component unmounts

  return {
    options, loadingOptions, sections, subjectId, setSubjectId, sectionId, setSectionId,
    sessionId, running, faces, facesInFrame: faces.length, present, inside, enrolled,
    records, summary, ended, error, outside, mode, setMode, begin, pause, finish, halt, refreshRecords,
    csvUrl: sessionId != null ? live.csvUrl(sessionId) : null,
  }
}
