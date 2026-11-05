"""Face recognition and enrolment. Faces are stored permanently in the database (face_embeddings).

The browser sends one JPEG frame at a time; YuNet detects, SFace embeds, and the match is the
student with the best mean of their top-3 similarities (and a clear margin over the runner-up).
"""

from __future__ import annotations

import os
import re
import shutil
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Tuple

import cv2
import numpy as np

from services.face_service import FaceService

_DB_WRITE_LOCK = threading.Lock()         # one writer of face_database.npz at a time
LABEL_RE = re.compile(r"^[A-Za-z0-9_.-]{1,50}$")
IMAGE_EXT = (".jpg", ".jpeg", ".png")
DUPLICATE_FACE_SCORE = 0.55   # a new face this similar to ANOTHER student is refused
HEAL_EVERY = 60.0             # seconds between "does any student have photos but no stored face?" checks
MIN_FACE_FRACTION = 0.05      # faces narrower than 5 % of the frame are too small to recognise reliably
MAX_ENROLL_WIDTH = 640
TOPK = 3                 # a student's score = mean of their 3 best matching samples
MARGIN = 0.05            # best student must beat the runner-up by this much
CHECK_EVERY = 3.0        # seconds between 'did the face table change?' checks

MAX_WIDTH = 640   # frames wider than this are scaled down before detection
MAX_FACES = 20    # ignore anything beyond this many faces per frame


class SampleRejected(Exception):
    """A captured enrolment frame is not usable (message is shown to the user)."""


@dataclass
class FaceHit:
    x: float          # box, normalised 0..1 so the UI can overlay it at any size
    y: float
    w: float
    h: float
    label: Optional[str]   # roll number of the matched student, if confident
    score: float           # mean of the student's 3 best cosine similarities


class LiveRecognizer:
    """Faces live in the database (table face_embeddings) so they survive restarts and days.
    Recognition returns the student's ROLL NUMBER, so a face can never fail to match its student row."""

    def __init__(self, app):
        self.fs = FaceService(app)
        self.app = app
        self.dataset_dir = app.config.get("DATASET_FOLDER") or os.path.join(app.root_path, "dataset")
        self._lock = threading.Lock()
        self._sig = None
        self._checked = 0.0
        self._emb = None          # (N,128) L2-normalised
        self._sids = None         # (N,) student ids
        self._groups = {}         # student_id -> row indices
        self._rolls = {}          # student_id -> roll number
        self._legacy_done = False
        self._healed = 0.0
        self.unmapped = []

    # ---- database cache --------------------------------------------------
    def invalidate(self):
        self._checked = 0.0
        self._sig = None

    def _ensure_database(self) -> bool:
        from sqlalchemy import func
        from extensions import db
        from models import FaceEmbedding, Student
        now = time.time()
        if self._emb is not None and now - self._checked < CHECK_EVERY:
            return len(self._emb) > 0
        self._checked = now
        if not self._legacy_done:
            self._legacy_done = True
            try:
                self._import_legacy_npz()
            except Exception:
                db.session.rollback()
                self.app.logger.exception("Legacy face database import failed")
        if now - self._healed > HEAL_EVERY:
            self._healed = now
            try:
                self._heal_missing_faces()
            except Exception:
                db.session.rollback()
                self.app.logger.exception("Rebuilding missing faces from dataset/ failed")
        sig = db.session.query(func.count(FaceEmbedding.id), func.max(FaceEmbedding.id)).one()
        sig = (int(sig[0] or 0), int(sig[1] or 0))
        if sig == self._sig and self._emb is not None:
            return len(self._emb) > 0
        rows = db.session.query(FaceEmbedding.student_id, FaceEmbedding.vector, Student.roll_number) \
            .join(Student, Student.id == FaceEmbedding.student_id).all()
        if not rows:
            self._emb = np.zeros((0, 128), np.float32)
            self._sids = np.zeros((0,), np.int64)
            self._groups, self._rolls, self._sig = {}, {}, sig
            return False
        emb = np.vstack([np.frombuffer(r[1], dtype=np.float32) for r in rows]).astype(np.float32)
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._emb = emb / norms
        self._sids = np.array([r[0] for r in rows], dtype=np.int64)
        self._rolls = {r[0]: r[2] for r in rows}
        self._groups = {int(s): np.where(self._sids == s)[0] for s in np.unique(self._sids)}
        self._sig = sig
        return True

    def _import_legacy_npz(self):
        """Copy faces from the old face_database.npz into the database, matching its labels (01, 02 ...) to students.
        Only students that have NO stored face yet are filled, so running it again never duplicates anything."""
        from extensions import db
        from models import FaceEmbedding, FaceEnrollment
        path = self.fs.database_file
        if not path or not os.path.exists(path):
            return
        with np.load(path, allow_pickle=False) as d:
            emb, names = d["embeddings"].astype(np.float32), d["names"].astype(str)
        self.unmapped = []
        for label in sorted(set(names.tolist())):
            st = resolve_label(label, loose=True)
            if st is None:
                self.unmapped.append(label)
                continue
            if FaceEmbedding.query.filter_by(student_id=st.id).first():
                continue
            for v in emb[names == label]:
                db.session.add(FaceEmbedding(student_id=st.id, vector=v.tobytes()))
            if not FaceEnrollment.query.filter_by(student_id=st.id).first():
                db.session.add(FaceEnrollment(student_id=st.id, embedding_index=0))
        db.session.commit()
        if self.unmapped:
            self.app.logger.warning("Old face labels with no matching student (run migrate_legacy_faces.py): %s", self.unmapped)

    def _heal_missing_faces(self):
        """A student whose photos are in dataset/<roll>/ but who has no stored face would be shown as 'Unknown'.
        Re-embed such photos into the database automatically (students that already have faces are never touched)."""
        from extensions import db
        from models import FaceEmbedding, Student
        have = {sid for (sid,) in db.session.query(FaceEmbedding.student_id).distinct()}
        root = self.dataset_dir
        if not os.path.isdir(root):
            return
        for label in sorted(os.listdir(root)):
            folder = os.path.join(root, label)
            if not os.path.isdir(folder) or not any(f.lower().endswith(IMAGE_EXT) for f in os.listdir(folder)):
                continue
            st = resolve_label(label, loose=True)
            if st is None or st.id in have:
                continue
            try:
                n = self.rebuild_person(st, folder=folder)
                self.app.logger.info("Student %s: %d face samples rebuilt from %s", st.roll_number, n, folder)
            except Exception as exc:
                db.session.rollback()
                self.app.logger.warning("Could not rebuild faces for %s: %s", label, exc)

    def readiness(self) -> Tuple[bool, str]:
        ok, msg = self.fs.models_available()
        if not ok:
            return False, msg
        if not self._ensure_database():
            return False, "No faces enrolled yet. Enrol students first."
        return True, "Ready"

    def enrolled_labels(self) -> set:
        return {str(r).upper() for r in self._rolls.values()} if self._ensure_database() else set()

    def count_samples(self, student_id: int) -> int:
        from models import FaceEmbedding
        return FaceEmbedding.query.filter_by(student_id=student_id).count()

    # ---- recognition -----------------------------------------------------
    def _best_student(self, feat_n, exclude_sid=None):
        """(student_id, score, runner_up_score) using the mean of each student's top-3 similarities."""
        sims = self._emb @ feat_n
        best, best_s, second_s = None, -1.0, -1.0
        for sid, idx in self._groups.items():
            if exclude_sid is not None and sid == exclude_sid:
                continue
            v = np.sort(sims[idx])[-TOPK:]
            s = float(v.mean())
            if s > best_s:
                best, second_s, best_s = sid, best_s, s
            elif s > second_s:
                second_s = s
        return best, best_s, second_s

    def analyse(self, jpeg_bytes: bytes) -> Tuple[List[FaceHit], int]:
        started = time.perf_counter()
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("Could not decode image.")
        ready, msg = self.readiness()
        if not ready:
            raise RuntimeError(msg)
        h0, w0 = img.shape[:2]
        if w0 > MAX_WIDTH:
            img = cv2.resize(img, (MAX_WIDTH, int(h0 * MAX_WIDTH / float(w0))), interpolation=cv2.INTER_AREA)
        H, W = img.shape[:2]
        hits: List[FaceHit] = []
        with self._lock:
            faces = self.fs.detect_faces(img)
            if faces is not None:
                for face in faces[:MAX_FACES]:
                    label, score = None, 0.0
                    big_enough = float(face[2]) >= MIN_FACE_FRACTION * W
                    feat = self.fs.get_embedding(img, face).flatten() if big_enough else np.zeros(128, np.float32)
                    norm = float(np.linalg.norm(feat))
                    if norm > 0:
                        sid, score, second = self._best_student(feat / norm)
                        if sid is not None and score >= self.fs.threshold and (score - max(second, 0.0) >= MARGIN or second < self.fs.threshold):
                            label = self._rolls.get(sid)
                    x, y, w, h = [float(v) for v in face[:4]]
                    x, y = max(x, 0.0), max(y, 0.0)
                    hits.append(FaceHit(x / W, y / H, min(w, W - x) / W, min(h, H - y) / H, label, score))
        return hits, int((time.perf_counter() - started) * 1000)

    # ---- enrolment -------------------------------------------------------
    def person_dir(self, label: str) -> str:
        if not LABEL_RE.match(label or "") or label in (".", ".."):
            raise ValueError("Unsafe roll number for a folder name.")
        root = os.path.realpath(self.dataset_dir)
        path = os.path.realpath(os.path.join(root, label))
        if os.path.commonpath([root, path]) != root:
            raise ValueError("Unsafe roll number for a folder name.")
        return path

    def validate_and_embed(self, jpeg_bytes: bytes, student) -> Tuple[np.ndarray, np.ndarray]:
        """Check one captured frame. Returns (face crop for the dataset folder, embedding of the FULL frame)."""
        img = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise SampleRejected("Could not read the camera frame.")
        ok, msg = self.fs.models_available()
        if not ok:
            raise RuntimeError(msg)
        if img.shape[1] > MAX_ENROLL_WIDTH:
            img = cv2.resize(img, (MAX_ENROLL_WIDTH, int(img.shape[0] * MAX_ENROLL_WIDTH / float(img.shape[1]))), interpolation=cv2.INTER_AREA)
        H, W = img.shape[:2]
        with self._lock:
            faces = self.fs.detect_faces(img)
            if faces is None or len(faces) == 0:
                raise SampleRejected("No face detected. Look straight at the camera.")
            if len(faces) > 1:
                raise SampleRejected("Only one person should be in the frame.")
            face = faces[0]
            x, y, w, h = [float(v) for v in face[:4]]
            if float(face[14]) < 0.8:
                raise SampleRejected("Face is not clear enough. Improve the lighting.")
            if w < 0.14 * W:
                raise SampleRejected("Move closer to the camera.")
            if x < 0.005 * W or y < 0.005 * H or x + w > 0.995 * W or y + h > 0.995 * H:
                raise SampleRejected("Keep your whole face inside the frame.")
            feat = self.fs.get_embedding(img, face).flatten().astype(np.float32)
        pad_x, pad_y = int(w * 0.15), int(h * 0.20)
        crop = img[max(0, int(y) - pad_y):min(H, int(y + h) + pad_y), max(0, int(x) - pad_x):min(W, int(x + w) + pad_x)]
        if crop.size == 0:
            raise SampleRejected("Could not crop the face. Try again.")
        if cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var() < 12:
            raise SampleRejected("Image is blurry. Hold still.")
        norm = float(np.linalg.norm(feat))
        if norm > 0 and self._ensure_database():
            sid, score, _ = self._best_student(feat / norm, exclude_sid=student.id)
            if sid is not None and score >= DUPLICATE_FACE_SCORE:
                raise SampleRejected(f"This face already belongs to student {self._rolls.get(sid)}. Check that the correct student is selected.")
        return crop, feat

    def save_sample(self, student, crop: np.ndarray, feat: np.ndarray) -> int:
        """Store the embedding in the database (permanent) and the photo in dataset/<roll>/. Returns the sample count."""
        from extensions import db
        from models import FaceEmbedding
        db.session.add(FaceEmbedding(student_id=student.id, vector=np.asarray(feat, np.float32).tobytes()))
        db.session.commit()
        try:
            folder = self.person_dir(student.roll_number)
            os.makedirs(folder, exist_ok=True)
            nums = [int(m.group(1)) for f in os.listdir(folder) if (m := re.match(r"^(\d+)\.", f))]
            cv2.imwrite(os.path.join(folder, f"{(max(nums) + 1 if nums else 1):03d}.jpg"), crop, [cv2.IMWRITE_JPEG_QUALITY, 85])
        except (ValueError, OSError):
            pass                                    # the photo is only a keepsake; the embedding is what matters
        self.invalidate()
        return self.count_samples(student.id)

    def clear_student(self, student_id: int):
        from extensions import db
        from models import FaceEmbedding
        FaceEmbedding.query.filter_by(student_id=student_id).delete()
        db.session.commit()
        self.invalidate()

    def rebuild_person(self, student, folder: Optional[str] = None) -> int:
        """Re-embed dataset/<roll>/ photos into the database (used by auto-heal and the sync/migration scripts)."""
        from extensions import db
        from models import FaceEmbedding, FaceEnrollment
        folder = folder or self.person_dir(student.roll_number)
        if not os.path.isdir(folder):
            raise ValueError("No photos found for this student.")
        feats = []
        for name in sorted(os.listdir(folder)):
            if not name.lower().endswith(IMAGE_EXT):
                continue
            image = cv2.imread(os.path.join(folder, name))
            if image is None:
                continue
            with self._lock:
                faces, used = self.fs.detect_with_image(image)     # tight crops are enlarged + padded when needed
                if faces is not None and len(faces) > 0:
                    best = faces[int(np.argmax(faces[:, 2] * faces[:, 3]))]
                    feats.append(self.fs.get_embedding(used, best).flatten().astype(np.float32))
        if not feats:
            raise ValueError("No usable faces were found in the saved photos.")
        FaceEmbedding.query.filter_by(student_id=student.id).delete()
        for v in feats:
            db.session.add(FaceEmbedding(student_id=student.id, vector=v.tobytes()))
        if not FaceEnrollment.query.filter_by(student_id=student.id).first():
            db.session.add(FaceEnrollment(student_id=student.id, embedding_index=0))
        db.session.commit()
        self.invalidate()
        return len(feats)

    def export_backup(self):
        """Write face_database.npz as a plain backup copy of the database faces."""
        from models import FaceEmbedding, Student
        rows = FaceEmbedding.query.join(Student, Student.id == FaceEmbedding.student_id) \
            .with_entities(Student.roll_number, FaceEmbedding.vector).all()
        if not rows:
            return
        tmp = self.fs.database_file + ".tmp.npz"
        np.savez(tmp, embeddings=np.vstack([np.frombuffer(v, np.float32) for _, v in rows]),
                 names=np.array([r for r, _ in rows], dtype=str))
        os.replace(tmp, self.fs.database_file)


def _pad(img):
    h, w = img.shape[:2]
    s = max(1.0, 320.0 / min(h, w))
    img = cv2.resize(img, None, fx=s, fy=s) if s > 1 else img
    p = int(0.4 * max(img.shape[:2]))
    return cv2.copyMakeBorder(img, p, p, p, p, cv2.BORDER_REPLICATE)


def resolve_label(label: str, loose: bool = False):
    """Match an old dataset label to a Student by roll number, admission number or exact name.
    loose=True (manual migration only) also tries 'trailing digits equal' (01 -> 21CS001) when that is unique."""
    import re as _re
    from sqlalchemy import func
    from models import Student, User
    lab = (label or "").strip()
    if not lab:
        return None
    u = lab.upper()
    st = Student.query.filter((func.upper(Student.roll_number) == u) | (func.upper(Student.admission_number) == u)).first()
    if st:
        return st
    st = Student.query.join(User, User.id == Student.user_id).filter(func.lower(User.name) == lab.lower()).first()
    if st or not (loose and lab.isdigit()):
        return st
    hits = [x for x in Student.query.all() if (m := _re.search(r"(\d+)$", x.roll_number)) and int(m.group(1)) == int(lab)]
    return hits[0] if len(hits) == 1 else None
