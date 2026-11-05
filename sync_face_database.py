"""Re-build faces from dataset/<roll>/ photos into the database (only students with no faces yet).

    python sync_face_database.py            # every dataset folder whose name is a roll number
    python sync_face_database.py 21CS001    # just this roll number
"""
import os
import sys

from app import create_app
from models import FaceEmbedding, Student
from services.live_recognizer import IMAGE_EXT, LiveRecognizer, resolve_label


def main() -> int:
    app = create_app()
    with app.app_context():
        rec = LiveRecognizer(app)
        ok, msg = rec.fs.models_available()
        if not ok:
            print(msg)
            return 1
        root = rec.dataset_dir
        wanted = sys.argv[1:] or [d for d in sorted(os.listdir(root)) if os.path.isdir(os.path.join(root, d))
                                  and any(f.lower().endswith(IMAGE_EXT) for f in os.listdir(os.path.join(root, d)))]
        for label in wanted:
            st = resolve_label(label, loose=True)
            if st is None:
                print(f"  {label}: no student with this roll number - skipped")
            elif not sys.argv[1:] and FaceEmbedding.query.filter_by(student_id=st.id).first():
                print(f"  {label}: already in the database")
            else:
                try:
                    print(f"  {label}: {rec.rebuild_person(st)} face samples saved")
                except Exception as exc:
                    print(f"  {label}: {exc}")
        rec.export_backup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
