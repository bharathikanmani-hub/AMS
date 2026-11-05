"""Build face_database.npz from photos in dataset/<student_id>/."""

import os
import sys

import cv2
import numpy as np

from config import DATABASE_FILE, DATASET_FOLDER
from face_utils import create_detector, create_recognizer


def main():
    if not os.path.isdir(DATASET_FOLDER):
        print("No dataset folder found. Run collect_faces.py first.")
        sys.exit(1)

    detector = create_detector()
    recognizer = create_recognizer()

    embeddings = []
    names = []
    students = [
        name
        for name in os.listdir(DATASET_FOLDER)
        if os.path.isdir(os.path.join(DATASET_FOLDER, name))
    ]

    if not students:
        print("No student folders found inside dataset/.")
        sys.exit(1)

    for student_id in students:
        folder = os.path.join(DATASET_FOLDER, student_id)
        samples = 0
        print(f"Processing {student_id}...")

        for filename in os.listdir(folder):
            if not filename.lower().endswith((".jpg", ".jpeg", ".png")):
                continue

            image = cv2.imread(os.path.join(folder, filename))
            if image is None:
                continue

            height, width = image.shape[:2]
            detector.setInputSize((width, height))
            _, faces = detector.detect(image)
            if faces is None or len(faces) == 0:
                print(f"  No face in {filename}")
                continue

            aligned = recognizer.alignCrop(image, faces[0])
            feature = recognizer.feature(aligned).astype(np.float32).flatten()
            embeddings.append(feature)
            names.append(student_id)
            samples += 1

        print(f"  {samples} embeddings")

    if not embeddings:
        print("No face embeddings were created. Check the dataset photos.")
        sys.exit(1)

    np.savez(
        DATABASE_FILE,
        embeddings=np.array(embeddings, dtype=np.float32),
        names=np.array(names),
    )
    print(f"Saved {len(names)} samples to {DATABASE_FILE}")


if __name__ == "__main__":
    main()
