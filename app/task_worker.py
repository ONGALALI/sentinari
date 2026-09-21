import time
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import requests

from .db import get_connection
from .config import get_settings
from .operator_control import update_task, update_task_feedback

class TaskWorker:
    def __init__(self):
        self.running = False
        self.thread = None
        self.settings = get_settings()
        worker_cfg = self.settings.get("task_worker", {}) if isinstance(self.settings.get("task_worker", {}), dict) else {}
        self.local_agent_url = str(worker_cfg.get("local_agent_url") or "http://127.0.0.1:8099/api/chat").strip()
        self.poll_seconds = max(2, int(worker_cfg.get("poll_seconds") or 10))
        self.timeout_seconds = max(10, int(worker_cfg.get("timeout_seconds") or 300))

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        print("Task Worker started.")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _run(self):
        while self.running:
            try:
                self._process_pending_tasks()
            except Exception as e:
                print(f"Task Worker Error: {e}")
            time.sleep(self.poll_seconds)

    def _process_pending_tasks(self):
        conn = get_connection()
        try:
            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            tasks = conn.execute(
                "SELECT * FROM smi_tasks WHERE status = 'pending' AND (target_datetime <= ? OR target_datetime = '')",
                (now,)
            ).fetchall()

            for task in tasks:
                self._handle_task(task)
        finally:
            conn.close()

    def _handle_task(self, task):
        task_id = task["id"]
        instruction = task["task_to_perform"]
        repo_path = task["knowledge_library_applicable"]
        
        print(f"Processing Task {task_id}: {instruction}")
        
        conn = get_connection()
        try:
            update_task(conn, task_id, status='in_progress')
            
            # Simple path check
            is_coding = repo_path and Path(repo_path).exists()
            
            payload = {
                "instruction": instruction,
                "repo_path": repo_path if is_coding else ""
            }
            
            try:
                resp = requests.post(self.local_agent_url, json=payload, timeout=self.timeout_seconds)
                if resp.ok:
                    data = resp.json()
                    if data.get("ok"):
                        patch = data.get("patch", "")
                        feedback = f"SMI Proposed Patch:\n\n{patch}"
                        update_task_feedback(conn, task_id, feedback=feedback, evaluation="Success")
                        update_task(conn, task_id, status="completed")
                    else:
                        error = data.get("detail") or "Unknown error"
                        update_task_feedback(conn, task_id, feedback=f"Error: {error}", evaluation="Failed")
                        update_task(conn, task_id, status="blocked")
                else:
                    update_task_feedback(conn, task_id, feedback=f"Backend Error: {resp.status_code}", evaluation="Failed")
                    update_task(conn, task_id, status="blocked")
            except Exception as e:
                update_task_feedback(conn, task_id, feedback=f"Error: {str(e)}", evaluation="Failed")
                update_task(conn, task_id, status="blocked")
                
        finally:
            conn.close()

_worker = TaskWorker()

def start_task_worker():
    _worker.start()

def stop_task_worker():
    _worker.stop()

