"""Face detection and recognition service using OpenCV YuNet + SFace."""

import os
import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple, List, Dict

import cv2
import numpy as np

from extensions import db

logger = logging.getLogger(__name__)


class FaceService:
    """Manages face detection, recognition, enrollment, and live attendance."""
    
    def __init__(self, app=None):
        self.detector = None
        self.recognizer = None
        self.yunet_path = None
        self.sface_path = None
        self.threshold = 0.363
        self.dataset_folder = None
        self.database_file = None
        self.known_embeddings = None
        self.known_names = None
        self.photos_per_student = 15
        self.capture_delay = 1.0
        self._active_sessions = {}  # session_id -> SessionWorker
        self._lock = threading.Lock()
        
        if app:
            self.init_app(app)
    
    def init_app(self, app):
        """Initialize with Flask app config."""
        self.yunet_path = app.config.get('YUNET_MODEL')
        self.sface_path = app.config.get('SFACE_MODEL')
        self.threshold = app.config.get('RECOGNITION_THRESHOLD', 0.363)
        self.dataset_folder = app.config.get('DATASET_FOLDER')
        self.database_file = app.config.get('DATABASE_FILE')
        self.photos_per_student = app.config.get('PHOTOS_PER_STUDENT', 15)
        self.capture_delay = app.config.get('CAPTURE_DELAY_SECONDS', 1.0)
        self.coverage_threshold = app.config.get('ATTENDANCE_COVERAGE_THRESHOLD', 0.70)
        app.face_service = self
    
    def models_available(self) -> Tuple[bool, str]:
        """Check if ONNX model files exist."""
        missing = []
        if not self.yunet_path or not os.path.exists(self.yunet_path):
            missing.append(f'YuNet model: {self.yunet_path}')
        if not self.sface_path or not os.path.exists(self.sface_path):
            missing.append(f'SFace model: {self.sface_path}')
        if missing:
            return False, 'Missing models: ' + '; '.join(missing)
        return True, 'Models available'
    
    def _init_detector(self):
        """Initialize YuNet face detector."""
        if self.detector is None:
            ok, msg = self.models_available()
            if not ok:
                raise RuntimeError(msg)
            self.detector = cv2.FaceDetectorYN.create(
                self.yunet_path, '', (320, 320), 0.6, 0.3, 5000
            )
        return self.detector
    
    def _init_recognizer(self):
        """Initialize SFace recognizer."""
        if self.recognizer is None:
            ok, msg = self.models_available()
            if not ok:
                raise RuntimeError(msg)
            self.recognizer = cv2.FaceRecognizerSF.create(self.sface_path, '')
        return self.recognizer
    
    def load_embeddings(self) -> bool:
        """Load face embeddings from npz file."""
        if not self.database_file or not os.path.exists(self.database_file):
            logger.warning('Face database file not found: %s', self.database_file)
            return False
        try:
            data = np.load(self.database_file)
            self.known_embeddings = data['embeddings'].astype(np.float32)
            self.known_names = data['names']
            logger.info('Loaded %d face embeddings', len(self.known_names))
            return True
        except Exception as e:
            logger.error('Failed to load face database: %s', e)
            return False
    
    def detect_faces(self, frame):
        """Detect faces in a frame. Returns an array of detections (or None)."""
        detector = self._init_detector()
        h, w = frame.shape[:2]
        detector.setInputSize((w, h))
        _, faces = detector.detect(frame)
        return faces

    def detect_with_image(self, frame):
        """Like detect_faces, but small / tightly cropped photos (e.g. dataset/<roll>/001.jpg) get a second try after
        being enlarged and padded, because YuNet misses faces that fill the whole image.
        Returns (faces, image_the_faces_refer_to)."""
        faces = self.detect_faces(frame)
        if faces is not None and len(faces) > 0:
            return faces, frame
        h, w = frame.shape[:2]
        scale = max(1.0, 320.0 / min(h, w))
        big = cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC) if scale > 1 else frame
        pad = int(0.4 * max(big.shape[:2]))
        big = cv2.copyMakeBorder(big, pad, pad, pad, pad, cv2.BORDER_REPLICATE)
        faces = self.detect_faces(big)
        return (faces, big) if faces is not None and len(faces) > 0 else (None, frame)

    def get_embedding(self, frame, face):
        """SFace embedding of an aligned face, averaged with its mirror image (more stable across head turns)."""
        recognizer = self._init_recognizer()
        aligned = recognizer.alignCrop(frame, face)
        feat = recognizer.feature(aligned).astype(np.float32).flatten()
        flipped = recognizer.feature(cv2.flip(aligned, 1)).astype(np.float32).flatten()
        n1, n2 = float(np.linalg.norm(feat)), float(np.linalg.norm(flipped))
        if n1 > 0 and n2 > 0:
            feat = feat / n1 + flipped / n2
        return feat.reshape(1, -1)

    def identify(self, feature) -> Tuple[str, float]:
        """Identify a face against known embeddings.
        
        Returns (name, score). Returns ('Unknown', score) if no match.
        """
        if self.known_embeddings is None or len(self.known_embeddings) == 0:
            return 'Unknown', 0.0
        
        recognizer = self._init_recognizer()
        best_score = -1.0
        best_name = 'Unknown'
        
        for idx, stored in enumerate(self.known_embeddings):
            score = recognizer.match(
                feature, stored.reshape(1, -1),
                cv2.FaceRecognizerSF_FR_COSINE
            )
            if score > best_score:
                best_score = score
                best_name = str(self.known_names[idx])
        
        if best_score >= self.threshold:
            return best_name, best_score
        return 'Unknown', best_score
    
    def build_database(self) -> Tuple[bool, str]:
        """Rebuild face_database.npz from dataset/ folder."""
        if not self.dataset_folder or not os.path.isdir(self.dataset_folder):
            return False, 'No dataset folder found'
        
        detector = self._init_detector()
        recognizer = self._init_recognizer()
        
        embeddings = []
        names = []
        students = [
            name for name in os.listdir(self.dataset_folder)
            if os.path.isdir(os.path.join(self.dataset_folder, name))
        ]
        
        if not students:
            return False, 'No student folders in dataset/'
        
        for student_id in students:
            folder = os.path.join(self.dataset_folder, student_id)
            samples = 0
            
            for filename in os.listdir(folder):
                if not filename.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                image = cv2.imread(os.path.join(folder, filename))
                if image is None:
                    continue
                faces, used = self.detect_with_image(image)
                if faces is None or len(faces) == 0:
                    continue
                best = faces[int(np.argmax(faces[:, 2] * faces[:, 3]))]
                feature = self.get_embedding(used, best).flatten()
                embeddings.append(feature)
                names.append(student_id)
                samples += 1
            
            logger.info('Student %s: %d embeddings', student_id, samples)
        
        if not embeddings:
            return False, 'No face embeddings created from dataset photos'
        
        np.savez(
            self.database_file,
            embeddings=np.array(embeddings, dtype=np.float32),
            names=np.array(names)
        )
        self.load_embeddings()
        return True, f'Built database with {len(names)} embeddings from {len(students)} students'
    
    def start_session_recognition(self, session_id: int, app) -> Tuple[bool, str]:
        """Start background webcam recognition for an attendance session."""
        with self._lock:
            if session_id in self._active_sessions:
                return False, 'Recognition already running for this session'
        
        if not self.load_embeddings():
            return False, 'Face database not available. Run build_database first.'
        
        worker = SessionWorker(session_id, self, app)
        with self._lock:
            self._active_sessions[session_id] = worker
        worker.start()
        return True, 'Camera recognition started'
    
    def stop_session_recognition(self, session_id: int) -> Tuple[bool, str]:
        """Stop background webcam recognition."""
        with self._lock:
            worker = self._active_sessions.get(session_id)
        if not worker:
            return False, 'No active recognition for this session'
        worker.stop()
        with self._lock:
            self._active_sessions.pop(session_id, None)
        return True, 'Camera recognition stopped'
    
    def get_session_status(self, session_id: int) -> Optional[dict]:
        """Get live status of recognition session."""
        with self._lock:
            worker = self._active_sessions.get(session_id)
        if not worker:
            return None
        return worker.get_status()


class SessionWorker(threading.Thread):
    """Background thread that reads webcam frames and recognizes faces."""
    
    def __init__(self, session_id: int, face_service: FaceService, app):
        super().__init__(daemon=True)
        self.session_id = session_id
        self.face_service = face_service
        self.app = app
        self._running = False
        self._status = {
            'camera_active': False,
            'recognized': {},  # student_id -> {name, confidence, first_seen, last_seen, total_seconds}
            'unknown_count': 0,
            'frame_count': 0,
            'error': None,
            'started_at': None,
        }
        self._lock = threading.Lock()
    
    def run(self):
        """Main recognition loop."""
        self._running = True
        self._status['started_at'] = datetime.now(timezone.utc).isoformat()
        
        try:
            camera = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not camera.isOpened():
                camera = cv2.VideoCapture(0)
            if not camera.isOpened():
                self._status['error'] = 'Could not open webcam'
                self._status['camera_active'] = False
                logger.error('Could not open webcam for session %d', self.session_id)
                return
            
            self._status['camera_active'] = True
            logger.info('Camera opened for session %d', self.session_id)
            
            # Update session in database
            with self.app.app_context():
                from models import AttendanceSession
                session = db.session.get(AttendanceSession, self.session_id)
                if session:
                    session.camera_active = True
                    session.status = 'in_progress'
                    db.session.commit()
            
            last_recognition_time = {}
            recognition_interval = 2.0  # seconds between recognitions per student
            
            while self._running:
                ok, frame = camera.read()
                if not ok:
                    self._status['error'] = 'Camera frame read failed'
                    break
                
                with self._lock:
                    self._status['frame_count'] += 1
                
                faces = self.face_service.detect_faces(frame)
                now = time.time()
                
                if faces is not None:
                    for face in faces:
                        feature = self.face_service.get_embedding(frame, face)
                        name, score = self.face_service.identify(feature)
                        
                        if name != 'Unknown' and score >= self.face_service.threshold:
                            last_time = last_recognition_time.get(name, 0)
                            
                            with self._lock:
                                if name not in self._status['recognized']:
                                    self._status['recognized'][name] = {
                                        'name': name,
                                        'confidence': round(float(score), 3),
                                        'first_seen': datetime.now(timezone.utc).isoformat(),
                                        'last_seen': datetime.now(timezone.utc).isoformat(),
                                        'observations': 1,
                                    }
                                else:
                                    self._status['recognized'][name]['last_seen'] = datetime.now(timezone.utc).isoformat()
                                    self._status['recognized'][name]['observations'] += 1
                                    if score > self._status['recognized'][name]['confidence']:
                                        self._status['recognized'][name]['confidence'] = round(float(score), 3)
                            
                            # Record in database periodically
                            if now - last_time >= recognition_interval:
                                last_recognition_time[name] = now
                                self._record_observation(name, score)
                        else:
                            with self._lock:
                                self._status['unknown_count'] += 1
                
                # Small sleep to prevent CPU spinning
                time.sleep(0.1)
        
        except Exception as e:
            logger.error('Recognition error in session %d: %s', self.session_id, e)
            self._status['error'] = str(e)
        finally:
            if 'camera' in dir() and camera is not None:
                camera.release()
            self._status['camera_active'] = False
            
            # Update session
            with self.app.app_context():
                from models import AttendanceSession
                session = db.session.get(AttendanceSession, self.session_id)
                if session:
                    session.camera_active = False
                    db.session.commit()
    
    def _record_observation(self, student_dataset_id: str, confidence: float):
        """Record a face observation in the database."""
        try:
            with self.app.app_context():
                from models import (
                    AttendanceRecord, AttendanceSession, Student,
                    ObservationInterval, FaceRecognitionLog
                )
                from extensions import db
                
                session_obj = db.session.get(AttendanceSession, self.session_id)
                if not session_obj:
                    return
                
                # Find student by roll_number or dataset ID matching
                student = Student.query.filter_by(roll_number=student_dataset_id).first()
                if not student:
                    # Log unmatched recognition
                    log = FaceRecognitionLog(
                        session_id=self.session_id,
                        confidence_score=confidence,
                        capture_time=datetime.now(timezone.utc),
                        recognition_status='unknown',
                        frame_number=self._status['frame_count']
                    )
                    db.session.add(log)
                    db.session.commit()
                    return
                
                # Get or create attendance record
                record = AttendanceRecord.query.filter_by(
                    session_id=self.session_id,
                    student_id=student.id
                ).first()
                
                now = datetime.now(timezone.utc)
                
                if not record:
                    record = AttendanceRecord(
                        session_id=self.session_id,
                        student_id=student.id,
                        status='needs_review',
                        first_seen_at=now,
                        last_seen_at=now,
                        total_observed_seconds=0,
                        coverage_percentage=0,
                        confidence_score=confidence,
                    )
                    db.session.add(record)
                    db.session.flush()
                
                # Update record
                record.last_seen_at = now
                if confidence > (record.confidence_score or 0):
                    record.confidence_score = confidence
                
                # Add observation interval
                interval = ObservationInterval(
                    record_id=record.id,
                    start_time=now,
                    end_time=now
                )
                db.session.add(interval)
                
                # Log recognition
                log = FaceRecognitionLog(
                    session_id=self.session_id,
                    student_id=student.id,
                    confidence_score=confidence,
                    capture_time=now,
                    recognition_status='recognized',
                    frame_number=self._status['frame_count']
                )
                db.session.add(log)
                
                db.session.commit()
        except Exception as e:
            logger.error('Error recording observation: %s', e)
    
    def stop(self):
        """Signal the worker to stop."""
        self._running = False
    
    def get_status(self) -> dict:
        """Get current status."""
        with self._lock:
            return {
                'camera_active': self._status['camera_active'],
                'recognized_count': len(self._status['recognized']),
                'recognized_students': list(self._status['recognized'].values()),
                'unknown_count': self._status['unknown_count'],
                'frame_count': self._status['frame_count'],
                'error': self._status['error'],
                'started_at': self._status['started_at'],
            }
