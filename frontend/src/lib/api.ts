// API client for the Flask backend.
// All calls go to the SAME origin ("/api"): in development Vite proxies /api to Flask
// (see vite.config.ts), and in production Flask serves this app itself. So the session
// cookie and CSRF token work with no CORS setup.
export type Role = 'admin' | 'faculty' | 'student'
export type User = { name: string; identifier: string; role: Role }
const BASE = (import.meta as any).env?.VITE_API_URL ?? '/api'

// Set to true to require real ID + password login against the Flask backend.
export const REQUIRE_LOGIN = true

export class AuthError extends Error {}

const NO_SERVER = `Cannot reach the server at ${BASE}. Check that Flask is running.`

// ---- CSRF: Flask hands out a token; every POST sends it back in a header -------------------
let csrf: string | null = null
async function csrfToken(force = false): Promise<string> {
  if (!csrf || force) {
    const r = await fetch(`${BASE}/auth/csrf`, { credentials: 'include' })
    csrf = (await r.json()).csrf_token as string
  }
  return csrf
}
async function send(path: string, init: RequestInit, retry = true): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...init, credentials: 'include',
    headers: { ...(init.headers as Record<string, string>), 'X-CSRFToken': await csrfToken() },
  })
  if (res.status === 400 && retry) { await csrfToken(true); return send(path, init, false) } // token expired
  return res
}
const postJson = (path: string, body: unknown = {}) =>
  send(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
const readJson = (r: Response) => r.json().catch(() => null)

// ---- Authentication -----------------------------------------------------------------------
export async function login(identifier: string, password: string, role: Role): Promise<User> {
  let r: Response
  try { r = await postJson('/auth/login', { identifier, password, role }) } catch { throw new Error(NO_SERVER) }
  const body = await readJson(r)
  if (r.status === 429) throw new Error(body?.message || 'Too many attempts. Please wait a few minutes.')
  if (r.status === 401 || r.status === 403) throw new Error(body?.message || 'Invalid ID, password, or role.')
  if (r.status >= 500) throw new Error('Server error. Please try again later.')
  if (!r.ok || !body?.user) throw new Error(body?.message || `Unexpected response (${r.status}).`)
  return body.user
}
export type SignupForm = { name: string; email: string; role: Role; rollNumber?: string; password: string }
/** Create an account. Students are active at once; faculty/admin wait for administrator approval. */
export async function signup(f: SignupForm): Promise<{ message: string; pending: boolean }> {
  let r: Response
  try { r = await postJson('/auth/signup', f) } catch { throw new Error(NO_SERVER) }
  const body = await readJson(r)
  if (!r.ok) throw new Error(body?.message || (r.status >= 500 ? 'Server error. Please try again later.' : `Sign up failed (${r.status}).`))
  return { message: body?.message || 'Account created.', pending: !!body?.pending }
}
/** Step 1 of password reset: e-mail a 6-digit code. `delivery` is 'console' when the server has no SMTP set up. */
export async function forgotPassword(email: string): Promise<{ message: string; delivery: 'email' | 'console' }> {
  let r: Response
  try { r = await postJson('/auth/forgot', { email }) } catch { throw new Error(NO_SERVER) }
  const body = await readJson(r)
  if (!r.ok) throw new Error(body?.message || 'Could not send the code. Please try again.')
  return { message: body.message, delivery: body.delivery }
}
/** Step 2: check the code and set the new password. */
export async function resetPassword(email: string, otp: string, newPassword: string): Promise<string> {
  let r: Response
  try { r = await postJson('/auth/reset', { email, otp, new_password: newPassword }) } catch { throw new Error(NO_SERVER) }
  const body = await readJson(r)
  if (!r.ok) throw new Error(body?.message || 'Could not reset the password.')
  return body.message
}
export async function logout() { await postJson('/auth/logout').catch(() => {}); csrf = null }

/** Restore the signed-in user after a page refresh (null if not signed in). */
export async function me(): Promise<User | null> {
  try {
    const r = await fetch(`${BASE}/auth/me`, { credentials: 'include' })
    return r.ok ? (await r.json()).user : null
  } catch { return null }
}

// ---- Dashboards (real data from MySQL) ---------------------------------------------------------
export type Dash = {
  subjects: { code: string; name: string; present: number; total: number }[]
  recent: string[][]
  timetable: string[][]
  students: { roll: string; name: string; pct: number }[]
}
export const emptyDash: Dash = { subjects: [], recent: [], timetable: [], students: [] }
export type StudentDash = {
  name: string; roll: string; section: string | null; present: number; absent: number; total: number; overall: number
  records: { date: string; period: number; subject: string; code: string; status: 'present' | 'absent'; entry: string | null; exit: string | null }[]
  timetable: string[][]
}
export const getDashboard = () => liveGet<Dash>('/dashboard')                 // faculty
export const getStudentDashboard = () => liveGet<StudentDash>('/student/dashboard')
// ---- Live Attendance ------------------------------------------------------------------------
export type LiveOptions = {
  subjects: { id: number; name: string; code: string; section_ids: number[] }[]
  sections: { id: number; name: string }[]
  recognition_ready: boolean
  recognition_message: string
}
export type FaceState = 'entered' | 'already_inside' | 'exited' | 'just_exited' | 'not_inside' | 'unknown' | 'not_in_section' | 'no_section' | 'unregistered' | 'not_in_subject'
export type Mode = 'entry' | 'exit'
export type LiveFace = {
  box: { x: number; y: number; w: number; h: number } // fractions (0..1) of the frame
  score: number; state: FaceState; roll_number: string | null; name: string | null
}
export type LiveRecord = { roll_number: string; name: string; subject: string; entry: string | null; exit: string | null; inside: boolean; status: string }
export type LiveSummary = { present: number; absent: number; total: number; inside: number; period_minutes: number; min_minutes: number }
export type HistorySession = { session_id: number; date: string; period: number; subject: string; code: string; section: string; present: number; absent: number; total: number; finished: boolean }
export type HistoryStudent = { roll: string; name: string; subject: string; status: string; entry: string | null; exit: string | null; inside: boolean }
async function liveGet<T>(path: string): Promise<T> {
  const r = await fetch(`${BASE}${path}`, { credentials: 'include' })
  const body = await readJson(r)
  if (r.status === 401) throw new AuthError('Session expired')
  if (!r.ok) throw new Error(body?.message || `Request failed (${r.status}).`)
  return body as T
}
async function livePost<T>(path: string, body?: unknown): Promise<T> {
  const r = body instanceof FormData ? await send(path, { method: 'POST', body }) : await postJson(path, body ?? {})
  const json = await readJson(r)
  if (r.status === 401) throw new AuthError('Session expired')
  if (!r.ok) throw new Error(json?.message || `Request failed (${r.status}).`)
  return json as T
}
export const live = {
  options: () => liveGet<LiveOptions>('/live/options'),
  start: (subject_id: number, section_id: number) =>
    livePost<{ session: { id: number; period: number }; present_count: number; enrolled_count: number }>('/live/sessions', { subject_id, section_id }),
  frame: (sessionId: number, jpeg: Blob, mode: Mode) => {
    const f = new FormData(); f.append('frame', jpeg, 'frame.jpg'); f.append('mode', mode)
    return livePost<{ faces: LiveFace[]; faces_in_frame: number; latency_ms: number; present_count: number; inside_count: number; newly_marked: number; outside_schedule: boolean }>(`/live/sessions/${sessionId}/frame`, f)
  },
  records: (sessionId: number) =>
    liveGet<{ records: LiveRecord[]; summary: LiveSummary; session_status: string }>(`/live/sessions/${sessionId}/records`),
  history: (date = '') => liveGet<{ sessions: HistorySession[] }>(`/live/history?date=${encodeURIComponent(date)}`),
  historySession: (sessionId: number) => liveGet<{ students: HistoryStudent[]; finished: boolean }>(`/live/history/session/${sessionId}`),
  csvUrl: (sessionId: number) => `${BASE}/live/sessions/${sessionId}/export.csv`,
  end: (sessionId: number) => livePost<{ present: number; absent: number }>(`/live/sessions/${sessionId}/end`),
}

// ---- Admin ----------------------------------------------------------------------------------------
export type AdminUser = { id: number; student_id: number | null; name: string; role: string; identifier: string; email: string | null; section: string | null; active: boolean; pending: boolean; requested_role: string | null }
export type SectionInfo = { id: number; name: string; department: string; students: number; periods: number }
export type AttSession = { session_id: number; section: string; subject: string; code: string; faculty: string; period: number; status: string; total: number; present: number; absent: number; finished: boolean }
export type AttStudent = { roll: string; name: string; subject: string; status: string; entry: string | null; exit: string | null }
export type Period = { id: number; day: string; no: number; start: string; end: string; section: string; subject: string; code: string; faculty: string; faculty_id: number; room: string }
export type NewPeriod = { day: string; no: number; start: string; end: string; section: string; subject: string; faculty_id: number; room: string }
export const admin = {
  overview: () => liveGet<{ users: number; faculty: number; periods: number; records: number; students: number; sections: number; pending: number }>('/admin/overview'),
  users: () => liveGet<{ users: AdminUser[]; sections: string[] }>('/admin/users'),
  createUser: (b: { name: string; email: string; password: string; role: 'faculty' | 'admin' | 'student'; roll_number?: string; section?: string }) =>
    livePost<{ id: number; message: string }>('/admin/users', b),
  approve: (id: number) => livePost<{ message: string }>(`/admin/users/${id}/approve`),
  reject: (id: number) => livePost<{ message: string }>(`/admin/users/${id}/reject`),
  setEmail: (id: number, email: string) => livePost<{ email: string }>(`/admin/users/${id}/email`, { email }),
  sections: () => liveGet<{ sections: SectionInfo[]; unassigned: number }>('/admin/sections'),
  createSection: (name: string) => livePost<{ id: number; message: string }>('/admin/sections', { name }),
  deleteSection: (id: number) => livePost<{ ok: boolean }>(`/admin/sections/${id}/delete`),
  addStudentsToSection: (id: number, rolls: string) => livePost<{ assigned: number; not_found: string[]; message: string }>(`/admin/sections/${id}/students`, { rolls }),
  attendance: (date: string) => liveGet<{ date: string; sessions: AttSession[] }>(`/admin/attendance?date=${encodeURIComponent(date)}`),
  attendanceDetail: (sessionId: number) => liveGet<{ students: AttStudent[]; status: string }>(`/admin/attendance/session/${sessionId}`),
  setActive: (id: number, active: boolean) => livePost<{ active: boolean }>(`/admin/users/${id}/active`, { active }),
  setSection: (studentId: number, section: string) => livePost<{ section: string | null }>(`/admin/students/${studentId}/section`, { section }),
  timetable: () => liveGet<{ periods: Period[]; faculty: { id: number; name: string }[]; sections: string[] }>('/admin/timetable'),
  addPeriod: (b: NewPeriod) => livePost<{ message: string }>('/admin/timetable', b),
  deletePeriod: (id: number) => livePost<{ ok: boolean }>(`/admin/timetable/${id}/delete`),
  attendanceCsvUrl: `${BASE}/admin/reports/attendance.csv`,
  lowAttendance: () => liveGet<{ threshold: number; students: { roll: string; name: string; section: string; present: number; total: number; pct: number }[] }>('/admin/reports/low-attendance'),
}

// ---- Face enrolment -----------------------------------------------------------------------------
export type EnrollStudent = { id: number; roll_number: string; name: string; section: string | null; section_id: number | null; enrolled: boolean; samples: number }
export const enroll = {
  students: (q = '') => liveGet<{ students: EnrollStudent[]; sections: { id: number; name: string }[]; min_samples: number; can_replace?: boolean }>(`/enroll/students?q=${encodeURIComponent(q)}`),
  sample: (studentId: number, jpeg: Blob, o: { fresh?: boolean; replace?: boolean } = {}) => {
    const f = new FormData(); f.append('frame', jpeg, 'frame.jpg'); f.append('consent', 'true')
    if (o.fresh) f.append('fresh', '1')
    if (o.replace) f.append('replace', '1')
    return livePost<{ accepted: boolean; samples: number; message: string }>(`/enroll/${studentId}/samples`, f)
  },
  finish: (studentId: number, b: { name?: string; section_id?: number | null }) =>
    livePost<{ embeddings: number; message: string }>(`/enroll/${studentId}/finish`, b),
}
