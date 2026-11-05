"""Collect cropped face photos for one student ID."""

import os
import time

import cv2

from config import CAPTURE_DELAY_SECONDS, DATASET_FOLDER, PHOTOS_PER_STUDENT
from face_utils import create_detector, open_camera, window_was_closed


def main():
    student_id = input("Enter Student ID: ").strip()
    if not student_id:
        print("Student ID cannot be empty.")
        return

    save_folder = os.path.join(DATASET_FOLDER, student_id)
    os.makedirs(save_folder, exist_ok=True)

    detector = create_detector()
    camera = open_camera()
    window_name = "Collect Student Faces"

    photo_count = 0
    capturing = False
    last_capture_time = 0

    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    print(f"Student: {student_id}")
    print("Press C to start capture, Q to quit.")

    while True:
        ok, frame = camera.read()
        if not ok:
            print("Could not read a camera frame.")
            break

        height, width = frame.shape[:2]
        detector.setInputSize((width, height))
        _, faces = detector.detect(frame)
        face_detected = faces is not None and len(faces) > 0

        if face_detected:
            for face in faces:
                x, y, w, h = face[:4].astype(int)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
                cv2.putText(
                    frame,
                    "Face detected",
                    (x, max(y - 10, 20)),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                )

        cv2.putText(
            frame,
            f"Student: {student_id}",
            (20, 35),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            f"Photos: {photo_count}/{PHOTOS_PER_STUDENT}",
            (20, 70),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            frame,
            "CAPTURING..." if capturing else "Press C to start",
            (20, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (0, 255, 0),
            2,
        )

        cv2.imshow(window_name, frame)
        key = cv2.waitKey(1) & 0xFF

        if key in (ord("c"), ord("C")):
            if face_detected:
                capturing = True
                last_capture_time = 0
                print("Capture started.")
            else:
                print("Stand in front of the camera so a face is visible.")

        if capturing and face_detected:
            now = time.time()
            if now - last_capture_time >= CAPTURE_DELAY_SECONDS:
                face = faces[0]
                x, y, w, h = face[:4].astype(int)
                pad_x = int(w * 0.15)
                pad_y = int(h * 0.20)
                x1, y1 = max(0, x - pad_x), max(0, y - pad_y)
                x2, y2 = min(width, x + w + pad_x), min(height, y + h + pad_y)
                face_image = frame[y1:y2, x1:x2]

                if face_image.size:
                    filename = os.path.join(
                        save_folder, f"{photo_count + 1:03d}.jpg"
                    )
                    if cv2.imwrite(filename, face_image):
                        photo_count += 1
                        last_capture_time = now
                        print(f"Saved {photo_count}/{PHOTOS_PER_STUDENT}")

                if photo_count >= PHOTOS_PER_STUDENT:
                    print(f"Finished collecting photos for {student_id}.")
                    break

        if key in (ord("q"), ord("Q")) or window_was_closed(window_name):
            break

    camera.release()
    cv2.destroyAllWindows()
    print(f"Saved {photo_count} photos in {os.path.abspath(save_folder)}")


if __name__ == "__main__":
    main()
