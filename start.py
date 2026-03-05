#!/usr/bin/env python3
"""
BPM Video Controller
Nasłuchuje mikrofonu, wykrywa BPM i kontroluje prędkość odtwarzania wideo.
"""

import tkinter as tk
from tkinter import filedialog, ttk
import threading
import queue
import time
import numpy as np
import subprocess
import sys
import os

# ── Auto-install brakujących paczek ─────────────────────────────────────────
def install_if_missing(package, import_name=None):
    import_name = import_name or package
    try:
        __import__(import_name)
    except ImportError:
        print(f"Instaluję {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "--quiet"])

install_if_missing("pyaudio")
install_if_missing("librosa")
install_if_missing("opencv-python", "cv2")
install_if_missing("pillow", "PIL")

import pyaudio
import librosa
import cv2
from PIL import Image, ImageTk

# ── Stałe ───────────────────────────────────────────────────────────────────
CHUNK        = 2048
RATE         = 22050
CHANNELS     = 1
FORMAT       = pyaudio.paFloat32
HISTORY_SIZE = 8   # ile ostatnich BPM uśredniamy

# ── Detektor BPM z mikrofonu ─────────────────────────────────────────────────
class BPMDetector:
    def __init__(self, bpm_callback):
        self.bpm_callback = bpm_callback
        self.running = False
        self._thread = None
        self.current_bpm = 0.0

    def start(self):
        self.running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self.running = False

    def _loop(self):
        pa = pyaudio.PyAudio()
        stream = pa.open(
            format=FORMAT, channels=CHANNELS,
            rate=RATE, input=True,
            frames_per_buffer=CHUNK
        )
        buffer = []
        history = []

        while self.running:
            try:
                raw = stream.read(CHUNK, exception_on_overflow=False)
                samples = np.frombuffer(raw, dtype=np.float32)
                buffer.extend(samples.tolist())

                # analizujemy co ~1 sekundę
                if len(buffer) >= RATE:
                    audio = np.array(buffer[:RATE], dtype=np.float32)
                    buffer = buffer[RATE // 2:]  # 50% overlap

                    # librosa tempo detection
                    tempo, _ = librosa.beat.beat_track(y=audio, sr=RATE)
                    bpm = float(np.atleast_1d(tempo)[0])

                    if 40 < bpm < 220:
                        history.append(bpm)
                        if len(history) > HISTORY_SIZE:
                            history.pop(0)
                        smoothed = float(np.mean(history))
                        self.current_bpm = smoothed
                        self.bpm_callback(smoothed)

            except Exception:
                pass

        stream.stop_stream()
        stream.close()
        pa.terminate()


# ── Odtwarzacz wideo ─────────────────────────────────────────────────────────
class VideoPlayer:
    def __init__(self, canvas, status_var):
        self.canvas = canvas
        self.status_var = status_var
        self.cap = None
        self.video_path = None
        self.playing = False
        self.base_fps = 25.0
        self.speed_factor = 1.0
        self._thread = None
        self.frame_queue = queue.Queue(maxsize=2)
        self._photo = None   # referencja, żeby GC nie usunął

    def load(self, path):
        if self.cap:
            self.cap.release()
        self.cap = cv2.VideoCapture(path)
        self.video_path = path
        fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.base_fps = fps if fps > 0 else 25.0
        total = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.status_var.set(f"Wczytano: {os.path.basename(path)}  |  FPS: {self.base_fps:.1f}  |  Klatek: {total}")

    def play(self):
        if not self.cap:
            return
        self.playing = True
        self._thread = threading.Thread(target=self._decode_loop, daemon=True)
        self._thread.start()
        self._render_loop()

    def pause(self):
        self.playing = False

    def set_speed(self, factor):
        self.speed_factor = max(0.1, min(factor, 8.0))

    def _decode_loop(self):
        while self.playing and self.cap:
            ret, frame = self.cap.read()
            if not ret:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # pętla
                continue
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            try:
                self.frame_queue.put(frame_rgb, timeout=0.1)
            except queue.Full:
                pass

    def _render_loop(self):
        if not self.playing:
            return
        delay_ms = max(1, int(1000 / (self.base_fps * self.speed_factor)))
        try:
            frame = self.frame_queue.get_nowait()
            self._display_frame(frame)
        except queue.Empty:
            pass
        self.canvas.after(delay_ms, self._render_loop)

    def _display_frame(self, frame_rgb):
        cw = self.canvas.winfo_width()
        ch = self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        img = Image.fromarray(frame_rgb)
        img.thumbnail((cw, ch), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(img)
        self.canvas.create_image(cw // 2, ch // 2, anchor="center", image=self._photo)


# ── Główne GUI ───────────────────────────────────────────────────────────────
class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🎵 BPM Video Controller")
        self.configure(bg="#1a1a2e")
        self.geometry("900x620")
        self.resizable(True, True)

        self.base_bpm   = tk.DoubleVar(value=120.0)
        self.current_bpm_var = tk.StringVar(value="BPM: --")
        self.speed_var  = tk.StringVar(value="Prędkość: 1.00×")
        self.status_var = tk.StringVar(value="Brak wideo – otwórz plik...")
        self.listening  = False

        self._build_ui()

        self.player   = VideoPlayer(self.canvas, self.status_var)
        self.detector = BPMDetector(self._on_bpm)

    # ── UI ───────────────────────────────────────────────────────────────────
    def _build_ui(self):
        # ---- górny pasek ----
        top = tk.Frame(self, bg="#16213e", pady=6)
        top.pack(fill="x")

        tk.Button(top, text="📂 Otwórz wideo", command=self._open_video,
                  bg="#0f3460", fg="white", relief="flat",
                  padx=12, pady=4, cursor="hand2").pack(side="left", padx=8)

        self.play_btn = tk.Button(top, text="▶ Play", command=self._toggle_play,
                                  bg="#533483", fg="white", relief="flat",
                                  padx=12, pady=4, cursor="hand2")
        self.play_btn.pack(side="left", padx=4)

        self.mic_btn = tk.Button(top, text="🎤 Start nasłuchu", command=self._toggle_mic,
                                 bg="#e94560", fg="white", relief="flat",
                                 padx=12, pady=4, cursor="hand2")
        self.mic_btn.pack(side="left", padx=4)

        # BPM bazowy
        tk.Label(top, text="  BPM bazowy:", bg="#16213e", fg="#aaa").pack(side="left")
        tk.Spinbox(top, from_=40, to=220, increment=1,
                   textvariable=self.base_bpm, width=5,
                   bg="#0f3460", fg="white", buttonbackground="#0f3460",
                   command=self._recalc_speed).pack(side="left", padx=4)

        # ---- canvas wideo ----
        self.canvas = tk.Canvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=8, pady=4)

        # ---- dolny panel ----
        bot = tk.Frame(self, bg="#16213e", pady=6)
        bot.pack(fill="x")

        # BPM gauge
        self.bpm_label = tk.Label(bot, textvariable=self.current_bpm_var,
                                  bg="#16213e", fg="#e94560",
                                  font=("Courier", 22, "bold"))
        self.bpm_label.pack(side="left", padx=16)

        self.speed_label = tk.Label(bot, textvariable=self.speed_var,
                                    bg="#16213e", fg="#00b4d8",
                                    font=("Courier", 16))
        self.speed_label.pack(side="left", padx=8)

        # pasek BPM
        self.bpm_bar = ttk.Progressbar(bot, orient="horizontal",
                                        length=300, maximum=220)
        self.bpm_bar.pack(side="left", padx=16)

        tk.Label(bot, textvariable=self.status_var,
                 bg="#16213e", fg="#888").pack(side="right", padx=12)

        # ---- styl ----
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TProgressbar", troughcolor="#0f3460",
                        background="#e94560", thickness=14)

    # ── Akcje ────────────────────────────────────────────────────────────────
    def _open_video(self):
        path = filedialog.askopenfilename(
            filetypes=[("Wideo", "*.mp4 *.avi *.mov *.mkv *.webm"), ("Wszystkie", "*.*")]
        )
        if path:
            self.player.load(path)

    def _toggle_play(self):
        if not self.player.playing:
            self.player.play()
            self.play_btn.config(text="⏸ Pauza")
        else:
            self.player.pause()
            self.play_btn.config(text="▶ Play")

    def _toggle_mic(self):
        if not self.listening:
            self.listening = True
            self.detector.start()
            self.mic_btn.config(text="⏹ Stop nasłuchu", bg="#555")
            self.status_var.set("🎤 Nasłuchuję mikrofonu...")
        else:
            self.listening = False
            self.detector.stop()
            self.mic_btn.config(text="🎤 Start nasłuchu", bg="#e94560")

    def _on_bpm(self, bpm: float):
        """Callback wywoływany z wątku detektora."""
        self.after(0, self._apply_bpm, bpm)

    def _apply_bpm(self, bpm: float):
        self.current_bpm_var.set(f"BPM: {bpm:.1f}")
        self.bpm_bar["value"] = min(bpm, 220)
        self._recalc_speed(bpm)

    def _recalc_speed(self, detected_bpm=None):
        if detected_bpm is None:
            detected_bpm = self.detector.current_bpm or self.base_bpm.get()
        base = self.base_bpm.get()
        factor = detected_bpm / base if base > 0 else 1.0
        factor = max(0.1, min(factor, 8.0))
        self.speed_var.set(f"Prędkość: {factor:.2f}×")
        self.player.set_speed(factor)

    def on_close(self):
        self.detector.stop()
        self.player.pause()
        if self.player.cap:
            self.player.cap.release()
        self.destroy()


# ── Uruchomienie ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = App()
    app.protocol("WM_DELETE_WINDOW", app.on_close)
    app.mainloop()
