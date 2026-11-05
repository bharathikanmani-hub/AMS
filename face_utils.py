"""Helpers for YuNet detection, SFace recognition, and the webcam."""

import os
import sys

import cv2

from config import SFACE_MODEL, YUNET_MODEL


def require_file(path, label):
    if not os.path.exists(path):
        print(f"Missing {label}: {path}")
        sys.exit(1)


def create_detector():
    require_file(YUNET_MODEL, "YuNet model")
    return cv2.FaceDetectorYN.create(
        YUNET_MODEL,
        "",
        (320, 320),
        0.7,
        0.3,
        5000,
    )


def create_recognizer():
    require_file(SFACE_MODEL, "SFace model")
    return cv2.FaceRecognizerSF.create(SFACE_MODEL, "")


def open_camera():
    camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
    if not camera.isOpened():
        camera = cv2.VideoCapture(0)
    if not camera.isOpened():
        print("Could not open the webcam.")
        sys.exit(1)
    return camera


def window_was_closed(window_name):
    try:
        return cv2.getWindowProperty(window_name, cv2.WND_PROP_VISIBLE) < 1
    except cv2.error:
        return True
