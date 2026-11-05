"""Move the OLD face_database.npz (labels like 01, 02 ...) into the database, tied to real students.

    python migrate_legacy_faces.py                  # auto-match labels to roll number / name / trailing digits (shown before saving)
    python migrate_legacy_faces.py 01=21CS001 02=21CS002   # map labels by hand

Faces are stored permanently in the database (table face_embeddings). Re-run any time; it only adds.
"""
import os
import sys

import numpy as np

from app import create_app
from extensions import db
from models import FaceEmbedding, FaceEnrollment, Student
from services.live_recognizer import resolve_label


def main() -> int:
    app = create_app()
    manual = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    with app.app_context():
        path = app.config["DATABASE_FILE"]
        if not os.path.exists(path):
            print("No face_database.npz found - nothing to migrate.")
            return 0
        with np.load(path, allow_pickle=False) as d:
            emb, names = d["embeddings"].astype(np.float32), d["names"].astype(str)
        for label in sorted(set(names.tolist())):
            roll = manual.get(label)
            st = Student.query.filter(db.func.upper(Student.roll_number) == roll.upper()).first() if roll else resolve_label(label, loose=True)
            if st is None:
                print(f"  {label}: no matching student - use  {label}=<roll number>")
                continue
            if FaceEmbedding.query.filter_by(student_id=st.id).first():
                print(f"  {label}: {st.roll_number} already has faces - skipped")
                continue
            for v in emb[names == label]:
                db.session.add(FaceEmbedding(student_id=st.id, vector=v.tobytes()))
            if not FaceEnrollment.query.filter_by(student_id=st.id).first():
                db.session.add(FaceEnrollment(student_id=st.id, embedding_index=0))
            db.session.commit()
            print(f"  {label} -> {st.roll_number}: {int((names == label).sum())} samples saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
