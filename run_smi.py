"""SMI_Core launcher.

USAGE:

    python run_smi.py serve

which launches uvicorn app.main:app on 127.0.0.1:8099.

No passphrase, no sealed vault, nothing to unlock — the qualia mathematics
(app.qualia, app.qualia_recommendation) lives as plain source files in app/.

The old name ``run_locked.py`` is kept working via a thin shim so existing
launch scripts (launch-smi-core.bat, 1-run-key.txt) continue to run unchanged;
they are updated to call run_smi.py directly.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn
        import argparse

        parser = argparse.ArgumentParser()
        parser.add_argument("--config", type=str, default=None)
        parser.add_argument("--port", type=int, default=8099)
        args, unknown = parser.parse_known_args()

        if args.config:
            import os
            os.environ["SMI_CONFIG_PATH"] = args.config

        uvicorn.run("app.main:app", host="127.0.0.1", port=args.port, log_level="info")
        return 0
    print("Usage: python run_smi.py serve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
