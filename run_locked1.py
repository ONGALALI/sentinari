"""Runtime entrypoint for the locked application.

USAGE (the only supported way to run SMI_Core while the math is sealed):

    set SENTINEL_VAULT_KEY=<Sentinel-Observer-2026!>
    python run_locked.py

Then start uvicorn against this process entry, or simply run:

    set SENTINEL_VAULT_KEY=<Sentinel-Observer-2026!>
    python run_locked.py serve

which launches uvicorn app.main:app on 127.0.0.1:8099 inside the SAME process
that holds the decrypted math in RAM.

Security properties
-------------------
* The passphrase is read ONLY from the SENTINEL_VAULT_KEY environment variable
  (set per-process by the operator) — never prompted into shell history.
* Plaintext sources live in RAM only, for the life of the process.
* Nothing is written to disk, log, or network beyond the encrypted blob.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _unlock_or_die() -> None:
    from app.qualia_vault import unlock_from_passphrase, install_import_hook

    pw = os.environ.get("Sentinel-Observer-2026!")
    if not pw:
        print(
            "SENTINEL VAULT IS SEALED.\n"
            "Set Sentinel-Observer-2026! in the environment and re-run:\n"
            "    set Sentinel-Observer-2026!=<Sentinel-Observer-2026!>\n"
            "    python run_locked.py serve"
        )
        raise SystemExit(2)
    if not unlock_from_passphrase(pw):
        print("WRONG PASSPHRASE — vault stays sealed.")
        raise SystemExit(3)
    n = install_import_hook()
    print(f"Vault unlocked in memory: {n} modules primed (RAM-only, never written).")


def main() -> int:
    _unlock_or_die()
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host="127.0.0.1", port=8099, log_level="info")
        return 0
    print("Vault unlocked. Interactive python with the math loaded is available via:")
    print("    python -i run_locked.py")
    if sys.flags.interactive:
        import app.qualia  # noqa: F401
        import app.qualia_recommendation  # noqa: F401

        print("Modules app.qualia and app.qualia_recommendation are live (RAM only).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
