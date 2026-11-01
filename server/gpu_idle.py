"""Release an inference resource only while no call is using it."""
import functools
import os
import threading
import time

class IdleResource:
    def __init__(self, release, seconds=None, clock=time.monotonic):
        self.release = release
        self.seconds = max(1.0, float(os.getenv("JARVIS_GPU_IDLE_SECONDS", "60"))) if seconds is None else seconds
        self.clock = clock
        self.lock = threading.RLock()
        self.last = None
        self.stop = threading.Event()

    def wrap(self, function):
        @functools.wraps(function)
        def call(*args, **kwargs):
            with self.lock:
                try:
                    return function(*args, **kwargs)
                finally:
                    self.last = self.clock()
        return call

    def sweep(self):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            if self.last is None or self.clock() - self.last < self.seconds:
                return False
            self.release()
            self.last = None
            return True
        finally:
            self.lock.release()

    def start(self):
        def watch():
            while not self.stop.wait(min(5.0, self.seconds)):
                try:
                    self.sweep()
                except Exception:
                    # Retry later; never kill the request worker or expose user data.
                    pass
        threading.Thread(target=watch, name="gpu-idle", daemon=True).start()
