"""
Sentinari Sovereign Desktop Help-Agent & Companion Chatbot
Conceived & Engineered by Dr. Pierre C. Wepener (Inspirari Research Initiative).
An offline, zero-cloud desktop companion providing interactive operational guidance,
forensic methodology explanations, and real-time connectivity to Sentinari Core.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import ttk, scrolledtext

# -----------------------------------------------------------------------------
# DETERMINISTIC OFFLINE KNOWLEDGE ENGINE
# -----------------------------------------------------------------------------
OFFLINE_KNOWLEDGE = {
    "start": (
        "STUDIO START COCKPIT (/ui/start):\n"
        "• Central launchpad displaying health diagnostics, local engine state, and workspace navigation.\n"
        "• Verifies isolation guards and connects to local Gemma / Ollama / ONNX on port 8100.\n"
        "• Governed strictly by the 100-Year Sentinari Constitution (Articles I - VIII)."
    ),
    "playground": (
        "SCIENTIFIC PLAYGROUND & INGESTION (/ui/playground):\n"
        "• Curates 21 Sentinel scientific disciplines across 15,041+ scholarly works.\n"
        "• Autonomous SQLite WAL ingestion daemons stream chunks into local vector indices.\n"
        "• Verifiable academic provenance without corporate narrative filtering."
    ),
    "pattern": (
        "NEW PATTERN DISCOVERY & 7-D GAUSSIAN MATRIX (/ui/patterns):\n"
        "• Identifies interdisciplinary cross-domain scientific resonances.\n"
        "• Calibrates Dr. Wepener's 7-dimensional Gaussian sustainability model.\n"
        "• Baseline derivations lift Knowledge and Scientific Impact to Level 3 (+65% to +85% yield).\n"
        "• Generates peer-review KaTeX R&D papers with verified .ZIP appendices."
    ),
    "qualia": (
        "QUALIA LAB & FORENSIC DECEPTION AUDIT (/ui/qualia):\n"
        "• Modeled on Dr. Pierre C. Wepener's real-world courtroom forensic cross-examination.\n"
        "• Puts claims upon the witness stand with zero bias and strict pre-trial orientation.\n"
        "• Detects semantic drift, flags hallucinations, and outputs printable A4 audit sheets."
    ),
    "learning": (
        "LEARNING INDEX & BENCHMARKS (/ui/learning):\n"
        "• Tracks cognitive progression against Humanity's Last Exam (HLE) and SWE-Bench.\n"
        "• Verifies solutions against deterministic automated test suites to ensure genuine reasoning."
    ),
    "video": (
        "VIDEO STUDIO & WORKSPACE TOUR RECORDER (/ui/video):\n"
        "• Autonomous Gemma scriptwriter creates narration scripts tailored to live telemetry.\n"
        "• Edge-TTS neural voiceover (en-US-AndrewNeural) with synchronized karaoke word highlight.\n"
        "• 1080p canvas displays authentic Playground UI with auto-pausing drawing tools (Box, Line, Tick, Pen).\n"
        "• Smooth focal zoom on discussed topics ending with an animated bright yellow checkmark."
    ),
    "ace": (
        "ACE-STEP 1.5 SOVEREIGN AI MUSIC STUDIO (/ui/ace-step):\n"
        "• Integrates the state-of-the-art open-source music foundation model by ACE Studio & StepFun.\n"
        "• Generates ambient pads, epistemic drones, and multi-segment compositions locally.\n"
        "• One-click dispatch routes fresh tracks into the Video Studio ambient music mixer!"
    ),
    "wan": (
        "WAN 2.1 T2V-14B CINEMATIC STUDIO (/ui/wan21):\n"
        "• Fourteen-billion parameter diffusion transformer (DiT) text-to-video foundation model.\n"
        "• Produces 1080p photorealistic cinematic scenes, camera orbits, crane sweeps, and lighting.\n"
        "• Runs with FP8 and BF16 local quantization with zero cloud API reliance."
    ),
    "healing": (
        "AUTONOMOUS SELF-HEALING SYSTEM (/api/system/self-healing):\n"
        "• 100% self-healing architecture with 6 concurrent automated health probes.\n"
        "• Monitors SQLite WAL checkpoints, vector store sockets, Gemma gateways, and disk limits.\n"
        "• Executes automated surgical recovery routines to maintain 99.99% system availability."
    ),
    "music": (
        "BACKGROUND MUSIC & AUDIO UPLOAD:\n"
        "• Select from built-in ambient tracks (Ambient Discovery, Epistemic Flow, Sovereign Clarity).\n"
        "• Or click 'Upload Track' in the Video Studio to upload your own MP3/WAV/M4A/OGG files.\n"
        "• The system mixes ambient music at your chosen volume with automatic ducking under narration."
    ),
    "wepener": (
        "CHIEF ARCHITECT DR. PIERRE C. WEPENER:\n"
        "• Founder and Chief Architect of Sentinari (Inspirari Research Initiative).\n"
        "• PSIRA Grade A Certified Forensic Investigator (one of only two in South Africa).\n"
        "• Directed high-profile forensic R&D on landmark cases including the Oscar Pistorius trial.\n"
        "• Applied ruthless courtroom evidentiary standards directly into Sentinari's architecture."
    ),
}


def query_knowledge_base(query: str) -> str:
    """Deterministic offline answer matching."""
    q = query.lower()
    matches = []
    for key, text in OFFLINE_KNOWLEDGE.items():
        if key in q:
            matches.append(text)

    if "self-healing" in q or "self healing" in q or "health" in q or "patch" in q:
        return OFFLINE_KNOWLEDGE["healing"]
    if "record" in q or "draw" in q or "box" in q or "tick" in q or "zoom" in q:
        return OFFLINE_KNOWLEDGE["video"]
    if "music" in q or "sound" in q or "audio" in q or "track" in q or "upload" in q:
        return OFFLINE_KNOWLEDGE["music"] + "\n\n" + OFFLINE_KNOWLEDGE["ace"]
    if "wan" in q or "video clip" in q or "t2v" in q or "14b" in q:
        return OFFLINE_KNOWLEDGE["wan"]
    if "paper" in q or "katex" in q or "math" in q or "appendices" in q or "zip" in q:
        return OFFLINE_KNOWLEDGE["pattern"]
    if "qualia" in q or "deception" in q or "court" in q or "audit" in q or "investigat" in q:
        return OFFLINE_KNOWLEDGE["qualia"]
    if "who" in q or "author" in q or "wepener" in q or "pierre" in q or "psira" in q:
        return OFFLINE_KNOWLEDGE["wepener"]

    if matches:
        return "\n\n---\n\n".join(matches)

    return (
        "SENTINARI SOVEREIGN ASSISTANT:\n"
        f"I received your inquiry regarding '{query}'.\n\n"
        "Core System Quick Links:\n"
        "• Landing Page: http://127.0.0.1:8099/\n"
        "• Studio Cockpit: http://127.0.0.1:8099/ui/start\n"
        "• Video Studio: http://127.0.0.1:8099/ui/video\n"
        "• ACE-Step 1.5 Music: http://127.0.0.1:8099/ui/ace-step\n"
        "• Wan 2.1 T2V-14B: http://127.0.0.1:8099/ui/wan21\n"
        "• Offline Help Manual: http://127.0.0.1:8099/ui/help (or open docs/help.html)\n\n"
        "You can ask me about recording video tours, uploading music, the 7-D Gaussian Matrix, "
        "courtroom deception audits, or the 100-Year Constitution!"
    )


# -----------------------------------------------------------------------------
# DESKTOP GUI COMPANION APPLICATION
# -----------------------------------------------------------------------------
class SentinariHelpAgentApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Sentinari Sentinel • Sovereign Desktop Co-Pilot")
        self.root.geometry("640x780")
        self.root.minsize(480, 560)
        self.root.configure(bg="#07090e")

        self.server_url = "http://127.0.0.1:8099"
        self.server_connected = False

        self.build_ui()
        self.check_server_async()

    def build_ui(self):
        # 1. Header Frame
        hdr = tk.Frame(self.root, bg="#0d1322", padx=16, pady=12, highlightthickness=1, highlightbackground="#1e293b")
        hdr.pack(fill=tk.X)

        lbl_brand = tk.Label(hdr, text="SENTINARI SENTINEL", font=("Segoe UI", 13, "bold"), fg="#38bdf8", bg="#0d1322")
        lbl_brand.pack(side=tk.LEFT)

        self.lbl_status = tk.Label(hdr, text="● Checking Core...", font=("Segoe UI", 9, "bold"), fg="#fbbf24", bg="#0d1322")
        self.lbl_status.pack(side=tk.RIGHT)

        lbl_sub = tk.Label(self.root, text="Sovereign Offline AI Companion & Architectural Guide • Dr. Pierre C. Wepener",
                           font=("Segoe UI", 8), fg="#64748b", bg="#07090e", pady=4)
        lbl_sub.pack(fill=tk.X)

        # 2. Quick Suggestion Pills
        pills_frame = tk.Frame(self.root, bg="#07090e", padx=12, pady=6)
        pills_frame.pack(fill=tk.X)

        suggestions = [
            ("🎥 Video Tour", "How do I record a video tour with yellow ticks?"),
            ("🎵 Custom Music", "How do I select or upload background music?"),
            ("🎹 ACE-Step 1.5", "Tell me about the ACE-Step 1.5 Music Studio"),
            ("🎬 Wan 2.1 14B", "How does the Wan 2.1 T2V-14B video model work?"),
            ("⚖️ Qualia Audit", "How does the Qualia courtroom deception audit work?"),
            ("🛠️ Self-Healing", "Is Sentinari self-healing and how does it auto-repair?"),
        ]

        for label, query_text in suggestions:
            btn = tk.Button(
                pills_frame, text=label, font=("Segoe UI", 8),
                bg="#131b2e", fg="#94a3b8", activebackground="#1e293b", activeforeground="#ffffff",
                relief=tk.FLAT, bd=1, padx=6, pady=3, cursor="hand2",
                command=lambda q=query_text: self.submit_query(q)
            )
            btn.pack(side=tk.LEFT, padx=3, pady=2)

        # 3. Chat History Display
        self.chat_area = scrolledtext.ScrolledText(
            self.root, wrap=tk.WORD, font=("Segoe UI", 10),
            bg="#0b0f19", fg="#e2e8f0", insertbackground="#38bdf8",
            padx=16, pady=14, relief=tk.FLAT, bd=0
        )
        self.chat_area.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)

        # Configure tags
        self.chat_area.tag_configure("user", foreground="#38bdf8", font=("Segoe UI", 10, "bold"))
        self.chat_area.tag_configure("agent", foreground="#f8fafc", font=("Segoe UI", 10))
        self.chat_area.tag_configure("meta", foreground="#64748b", font=("Segoe UI", 8, "italic"))

        # Welcome message
        self.append_agent_message(
            "Greetings! I am the Sentinari Sovereign Desktop Co-Pilot.\n\n"
            "I operate 100% locally on your machine with zero cloud leakage, grounded unconditionally "
            "in the 100-Year Constitution. How may I assist you with your research, workspaces, or video tours today?"
        )

        # 4. Input Bar
        input_frame = tk.Frame(self.root, bg="#0d1322", padx=12, pady=10, highlightthickness=1, highlightbackground="#1e293b")
        input_frame.pack(fill=tk.X)

        self.txt_input = tk.Entry(
            input_frame, font=("Segoe UI", 10),
            bg="#07090e", fg="#ffffff", insertbackground="#38bdf8",
            relief=tk.FLAT, bd=6
        )
        self.txt_input.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.txt_input.bind("<Return>", lambda e: self.on_send())
        self.txt_input.focus_set()

        btn_send = tk.Button(
            input_frame, text="Ask Co-Pilot", font=("Segoe UI", 9, "bold"),
            bg="#6366f1", fg="#ffffff", activebackground="#4f46e5", activeforeground="#ffffff",
            relief=tk.FLAT, padx=14, pady=6, cursor="hand2",
            command=self.on_send
        )
        btn_send.pack(side=tk.RIGHT)

    def append_user_message(self, text: str):
        self.chat_area.insert(tk.END, f"\nYou: {text}\n", "user")
        self.chat_area.see(tk.END)

    def append_agent_message(self, text: str):
        self.chat_area.insert(tk.END, f"\nCo-Pilot:\n{text}\n", "agent")
        self.chat_area.insert(tk.END, "-" * 55 + "\n", "meta")
        self.chat_area.see(tk.END)

    def on_send(self):
        q = self.txt_input.get().strip()
        if not q:
            return
        self.txt_input.delete(0, tk.END)
        self.submit_query(q)

    def submit_query(self, query: str):
        self.append_user_message(query)

        def worker():
            # Try server query first if connected
            answer = None
            if self.server_connected:
                try:
                    payload = json.dumps({"query": query}).encode("utf-8")
                    req = urllib.request.Request(
                        f"{self.server_url}/api/help-agent/query",
                        data=payload,
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        res = json.loads(resp.read().decode("utf-8"))
                        if res.get("ok"):
                            answer = res.get("answer")
                except Exception:
                    pass

            if not answer:
                # Deterministic sovereign offline fallback
                answer = query_knowledge_base(query)

            self.root.after(0, lambda: self.append_agent_message(answer))

        threading.Thread(target=worker, daemon=True).start()

    def check_server_async(self):
        def worker():
            try:
                req = urllib.request.Request(f"{self.server_url}/health")
                with urllib.request.urlopen(req, timeout=2) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if data.get("ok"):
                        self.server_connected = True
                        self.root.after(0, lambda: self.lbl_status.config(text="● Core Online (8099)", fg="#34d399"))
                        return
            except Exception:
                pass
            self.server_connected = False
            self.root.after(0, lambda: self.lbl_status.config(text="○ Offline Knowledge Mode", fg="#94a3b8"))

        threading.Thread(target=worker, daemon=True).start()


def main():
    root = tk.Tk()
    app = SentinariHelpAgentApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
