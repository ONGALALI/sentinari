"""
Automated Model Downloader for Sentinari Foundation Models:
1. ACE-Step 1.5 (https://github.com/ace-step/ACE-Step-1.5.git)
2. Wan 2.1 T2V-14B (https://huggingface.co/Wan-AI/Wan2.1-T2V-14B)

Conceived & Engineered by Dr. Pierre C. Wepener.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

MODELS_DIR = Path("D:/Sentinari/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)


def clone_ace_step():
    print("\n[1/2] Checking ACE-Step 1.5 Repository...")
    target = MODELS_DIR / "ace-step-1.5"
    if target.exists() and (target / ".git").exists():
        print(f"  ✓ ACE-Step 1.5 is already cloned at {target}")
        print("  Pulling latest updates...")
        subprocess.run(["git", "-C", str(target), "pull"], check=False)
    else:
        print(f"  Cloning https://github.com/ace-step/ACE-Step-1.5.git into {target}...")
        res = subprocess.run(["git", "clone", "https://github.com/ace-step/ACE-Step-1.5.git", str(target)])
        if res.returncode == 0:
            print("  ✓ ACE-Step 1.5 cloned successfully!")
        else:
            print("  ⚠️ Git clone encountered an issue. Ensure git is installed.")


def download_wan21():
    print("\n[2/2] Checking Wan 2.1 T2V-14B Foundation Model...")
    target = MODELS_DIR / "wan2.1-t2v-14b"
    print(f"  Target path: {target}")
    print("  Note: Wan 2.1 T2V-14B is a 14.2-Billion parameter foundation model (~28GB).")
    print("  Sentinari includes an instant local procedural synthesizer so you can render immediately.")
    print("  If you wish to download the full 14B weights, install huggingface_hub:")
    print("      pip install huggingface_hub")
    print("      huggingface-cli download Wan-AI/Wan2.1-T2V-14B --local-dir D:/Sentinari/models/wan2.1-t2v-14b")
    
    try:
        from huggingface_hub import snapshot_download
        choice = input("\n  Do you want to begin downloading Wan 2.1 14B weights now? (y/N): ").strip().lower()
        if choice == 'y':
            print("  Starting snapshot download with resume support...")
            snapshot_download(repo_id="Wan-AI/Wan2.1-T2V-14B", local_dir=str(target), resume_download=True)
            print("  ✓ Wan 2.1 14B weights downloaded successfully!")
        else:
            print("  Skipping heavy weight download. Sentinari local synthesis studio is active and ready.")
    except ImportError:
        print("  huggingface_hub not installed in this environment. Sentinari local synthesis is active and ready.")


def main():
    print("=================================================================")
    print("  SENTINARI FOUNDATION MODEL SETUP (ACE-STEP 1.5 & WAN 2.1 14B)  ")
    print("  Conceived by Dr. Pierre C. Wepener • Inspirari Initiative     ")
    print("=================================================================")
    clone_ace_step()
    download_wan21()
    print("\nSetup check complete. Launch Sentinari via launch-sentinari.bat")


if __name__ == "__main__":
    main()
