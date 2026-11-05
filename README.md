# AttendAI — Classroom Face Attendance

Mini project for automatic classroom attendance using a webcam, YuNet face detection, and SFace recognition.

## What this project does

1. Faculty or admin starts a camera session from the web dashboard.
2. The camera detects faces and matches them with registered student photos.
3. Recognized students are marked **Present**.
4. When the session is finished (press **Q**), remaining registered students are marked **Absent**.
5. Admin, faculty, and student dashboards read the same `attendance.csv` file.

## Required model files

Keep these in the project folder (same place as `app.py`):

- `face_detection_yunet_2026may.onnx`
- `face_recognition_sface_2021dec.onnx`

They come from the OpenCV Zoo face-detection and face-recognition models.

## Setup

```bash
pip install -r requirements.txt
```

Optional: copy `.env.example` to `.env` and add a Gmail app password if you want Forgot Password emails.

Default admin login after first run:

- Email: `admin@attendai.local`
- Password: `Admin@123`
- Role: Admin

## How to run a class

1. Collect student faces:

   ```bash
   python collect_faces.py
   ```

   Enter a Student ID such as `01`. Press **C** to capture 15 photos, **Q** to quit.

2. Build the recognition database:

   ```bash
   python build_database.py
   ```

3. Start the website:

   ```bash
   python app.py
   ```

   Open [http://127.0.0.1:5000](http://127.0.0.1:5000)

4. Log in as Admin or Faculty and click **Start attendance**.
   A camera window opens. Students face the camera. Press **Q** to finish.

You can also run the camera directly:

```bash
python recognition.py
```

## Project layout

| File | Purpose |
| --- | --- |
| `app.py` | Website + login APIs + start camera |
| `collect_faces.py` | Save student face photos |
| `build_database.py` | Create `face_database.npz` |
| `recognition.py` | Live recognition and attendance |
| `attendance.csv` | Present / absent records |
| `users.json` | Login accounts |
| `dataset/` | One folder per Student ID |

## Roles

- **Admin** — overview, student percentages, start attendance, reports
- **Faculty** — start a class session and view today's log
- **Student** — view personal history using the same Student ID used for photos


## GitHub and privacy

This repository intentionally excludes local user records, attendance exports, face photographs, generated face embeddings, and backup copies. These files may contain personal or biometric information and must remain local/private. The `.gitignore` file excludes these runtime files. Never commit `.env` or real database/email credentials; use `.env.example` only as a placeholder template. Before deploying, set a strong unique `FLASK_SECRET_KEY` and secure database credentials.
