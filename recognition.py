"""Mark attendance from the webcam using YuNet + SFace."""

import os
import sys
from datetime import datetime

import cv2
import numpy as np

from attendance_store import (
    append_record,
    records_for_date,
    registered_students,
    student_marked_today,
)
from config import DATABASE_FILE, RECOGNITION_THRESHOLD
from face_utils import (
    create_detector,
    create_recognizer,
    open_camera,
    require_file,
    window_was_closed,
)


def identify(recognizer, feature, known_embeddings, known_names):
    best_score = -1.0
    best_name = "Unknown"

    for index, stored in enumerate(known_embeddings):
        score = recognizer.match(
            feature,
            stored.reshape(1, -1),
            cv2.FaceRecognizerSF_FR_COSINE,
        )
        if score > best_score:
            best_score = score
            best_name = str(known_names[index])

    if best_score >= RECOGNITION_THRESHOLD:
        return best_name, best_score
    return "Unknown", best_score


def main():
    require_file(DATABASE_FILE, "face database")
    students = registered_students()
    if not students:
        print("No registered students found in dataset/.")
        sys.exit(1)

    data = np.load(DATABASE_FILE)
    known_embeddings = data["embeddings"].astype(np.float32)
    known_names = data["names"]

    detector = create_detector()
    recognizer = create_recognizer()
    camera = open_camera()

    today = datetime.now().strftime("%Y-%m-%d")
    marked_present = {
        student_id
        for student_id in students
        if student_marked_today(student_id, today)
    }

    window_name = "Face Recognition Attendance"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    print("Show student faces to the camera. Press Q when the class is done.")

    while True:
        ok, frame = camera.read()
        if not ok:
            print("Could not read a camera frame.")
            break

        height, width = frame.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(frame)

        if faces is not None:
            for face in faces:
                x, y, w, h = face[:4].astype(int)
                aligned = recognizer.alignCrop(frame, face)
                feature = recognizer.feature(aligned).astype(np.float32)
                name, score = identify(
                    recognizer, feature, known_embeddings, known_names
                )

                color = (0, 255, 0) if name != "Unknown" else (0, 255, 255)
                cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                cv2.putText(
                    frame,
                    f"{name} ({score:.2f})",
                    (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                )

                if name != "Unknown" and name not in marked_present:
                    marked_present.add(name)
                    append_record(name, "Present", today)
                    print(f"{name} marked Present")

                cv2.putText(
                    frame,
                    "PRESENT" if name != "Unknown" else "UNKNOWN",
                    (x, y + h + 30),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    color,
                    2,
                )

        present_count = len(marked_present)
        remaining = max(len(students) - present_count, 0)
        cv2.putText(
            frame,
            f"Present {present_count}/{len(students)}  Remaining {remaining}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            "Q = finish attendance",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q")) or window_was_closed(window_name):
            break

    camera.release()
    cv2.destroyAllWindows()

    now = datetime.now().strftime("%H:%M:%S")
    already_saved = {row["student_id"] for row in records_for_date(today)}
    absent = [student for student in students if student not in marked_present]
    for student_id in absent:
        if student_id not in already_saved:
            append_record(student_id, "Absent", today, now)

    print("Attendance complete")
    print(f"Present: {len(marked_present)}")
    print(f"Absent: {len(absent)}")


if __name__ == "__main__":
    main()
