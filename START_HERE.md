# AttendAI - start here

## One-time setup (skip what you already did)
1. Copy your `.env` next to `app.py`. Make sure MySQL is running.
2. In a terminal in this folder (`.venv` active):
   ```
   pip install -r requirements.txt
   python create_database.py
   python init_db.py            <- creates any NEW tables (safe to re-run) and shows the Admin ID
   ```
   **Updating from the previous version?** Just run `python init_db.py` once: it adds the two new tables
   (password-reset codes and sign-up requests). Your existing data is not touched.
3. Double-click **build_frontend.bat** (needs Node.js 22). Run it again after any frontend change.
4. Double-click **run_attendai.bat** -> http://127.0.0.1:5000
5. (Optional) e-mail for password-reset codes: follow **EMAIL_SETUP.md**.

## Accounts and sign-in
* **Sign Up** asks for name, e-mail, role and password (students also give their roll number).
  - **Student** - active immediately.
  - **Faculty / Admin** - waits until an administrator approves it (Admin > Users > "Waiting for approval").
* **Sign In**: Student = roll number or e-mail; Faculty/Admin = numeric ID or e-mail. Existing accounts keep working.
* **Forgot password?** -> enter e-mail -> 6-digit code (valid 10 min) -> choose a new password.
  Old accounts need a real e-mail first: Admin > Users > pencil icon.

## Daily workflow
1. **Admin > Sections**: add CSE-A, CSE-B, CSE-C ... and paste roll numbers to put students into a section.
2. **Admin > Users**: approve faculty requests, or add faculty directly (shows their sign-in ID).
3. **Admin > Timetable**: add periods (day, period, times, section, subject, faculty, room).
   The faculty member immediately sees that subject + section in Live Attendance.
   Maria teaches only Computer Vision? Then she only ever sees Computer Vision and only her section's students.
4. **Faculty > Mark attendance > Enroll**: capture a student's face (saved in `dataset\<roll>\` and the face database).
5. **Faculty > Mark attendance > Live Attendance**: choose subject > Start Camera. Recognised students of that
   section become **present**. Press **End class**: everyone in the section who was not recognised becomes **absent**
   (CSE-A has 30 students: 22 recognised = 22 present, 8 absent).
6. **Admin > Attendance**: pick a date to see, for every class, Present / Absent / Total out of the section, and
   click a class to see each student. It refreshes by itself while a class is running.
7. **Students** see their history per subject, time in class and timetable on their dashboard.

## Re-entry and re-exit (in reference of the timetable)
* Each stretch a student is seen is a "presence segment". Not seen for more than 30 seconds = they left the room;
  seen again = **re-entry** (shown as ↺ in the tables, e.g. "2 (left 1x)").
* "Time in class" = total of the segments; "Coverage" = that time out of the timetable period length.
* A student counts as **present** once recognised; coverage and re-entries are shown alongside.
* If a class is run outside its timetable slot, Live Attendance shows a notice. To BLOCK that completely, set
  `ENFORCE_TIMETABLE=true` in `.env`.
* A class left open from a previous day is closed automatically (unseen students become absent).

## Existing dataset folders (e.g. students 10 and 11)
```
python sync_face_database.py
```
Adds dataset folders that are missing from `face_database.npz` (never removes anyone; keeps a `.bak` backup).

## Notes
* A student is marked present only if: the face matches, the roll number exists, AND the student is in the selected section.
* Roll numbers must equal dataset folder names (dataset\01, dataset\02 ...).
* `_original_backup\` has your original app.py, config.py and routes\auth.py.

## What changed in this version (run once after updating)
1. `python init_db.py` - creates the new tables (`face_embeddings`, `student_subjects`). Existing data is untouched.
2. `python migrate_legacy_faces.py` - moves your OLD face_database.npz (labels 01, 02 ...) into the database and ties each
   to a real student. Unmatched labels are listed; map them by hand: `python migrate_legacy_faces.py 01=21CS001 02=21CS002`.
   (Or just re-enrol those students - enrolment now takes a few seconds.)
3. `python add_periods_subjects.py` - adds periods 1-8 (Mon-Fri) to every section and gives Gayathri extra subjects.
4. Double-click **build_frontend.bat** again (frontend changed), then **run_attendai.bat**.
5. E-mail: fill `.env` (see EMAIL_SETUP.md) and test with `python test_email.py you@gmail.com`.

* Faces are stored permanently in the database; a student enrolled today is recognised on any later day. A student can be
  enrolled only once (admins can tick "re-enrol" to replace a face).
* Attendance is per class: a student recognised in Maria's Computer Vision session is marked only in that session, never in
  Hema's. Students who do not take a subject (see `student_subjects`) are not marked in it.
* Admin > Users can now add students (roll number + optional section) as well as faculty/admin.

## What changed in this version (face recognition + Entry/Exit)
**Face recognition (YuNet detection + SFace recognition)**
* Enrolled students no longer show as "Unknown": photos in `dataset\<roll>\` (and the old `face_database.npz`) are matched to
  students and re-embedded **automatically** (also by roll-number tail, e.g. folder `01` -> `21CS001` when unique). Tight face
  crops that YuNet misses are enlarged/padded and retried. Run `python sync_face_database.py` to do it by hand.
* Each face is embedded together with its mirror image (steadier across head turns); threshold 0.38 with a 0.05 margin over
  the runner-up (`RECOGNITION_THRESHOLD` in `.env`). Faces narrower than 5 % of the frame are ignored.
* All faces live in MySQL (`face_embeddings`); `face_database.npz` is only a backup.

**Entry / Exit, 45-minute periods**
* Live Attendance asks for **Entry** or **Exit** before the camera starts (switch any time).
* Entry marks the student present with the time. Exit is only possible after an Entry; a second Entry only after an Exit.
  Re-entry and re-exit simply add more in/out pairs.
* Every period is 45 minutes. Time in class under 20 minutes = absent. When the class ends, anyone still inside is exited,
  and students who never entered are marked absent.

**Dashboards**
* Removed "Hours present / Time in class", "Coverage", "Entries", "Confidence" and "First/Last seen" columns.
* Faculty: Records tab is read from the database (date picker, Present / Absent / Total per class, then each student with
  Subject, Entry, Exit, Status). Works the same for every faculty, including ones added later.
* Student: every started class is listed, with All / Present / Absent filters.
* Admin timetable: End time is set automatically to start + 45 minutes.

After updating: `build_frontend.bat`, then `run_attendai.bat`. No new tables or columns are needed.
