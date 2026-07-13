#!/usr/bin/env python
"""
Local dev orchestrator -- NO DOCKER required.

    python scripts/dev.py        (run from the backend/ directory)

What it does, in order:
  1. Forces UTF-8 stdout/stderr (Windows cp1252 crashes on unicode otherwise).
  2. Copies .env.example -> .env if .env does not exist yet.
  3. Loads .env.
  4. Starts `python -m moto.server -p 5000` (pure-Python AWS emulator; the
     ONLY emulator this script starts -- EMR and Snowflake are pure in-process
     mocks selected by EMR_MODE/SNOWFLAKE_MODE=mock; moto does not meaningfully
     emulate emr-serverless and no local Snowflake emulator exists, so do NOT
     go looking for a mock endpoint for either).
  5. Waits for moto to answer HTTP.
  6. Runs scripts/create_tables.py then scripts/seed_demo_data.py.
  7. Registers cleanup so Ctrl+C stops moto together with uvicorn.
  8. Runs uvicorn (foreground, --reload).
"""
import atexit
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# --- Step 1: force UTF-8 BEFORE any print (Windows cp1252 protection) --------
for s in (sys.stdout, sys.stderr):
    if hasattr(s, "reconfigure"):
        s.reconfigure(encoding="utf-8", errors="replace")

BACKEND_DIR = Path(__file__).resolve().parent.parent
# Offset ports (moto 5001, API 8001, frontend 3001) so TMS and TMT dev
# stacks can run side by side.
MOTO_PORT = 5001
MOTO_URL = f"http://127.0.0.1:{MOTO_PORT}/"

_moto_proc = None


def _child_env() -> dict:
    """Every child process needs PYTHONIOENCODING=utf-8 merged in -- a fresh
    interpreter otherwise inherits the OS default codepage (cp1252 on Windows)
    and crashes on the first unicode character it prints."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _cleanup() -> None:
    global _moto_proc
    if _moto_proc is not None and _moto_proc.poll() is None:
        print("Stopping moto server ...")
        _moto_proc.terminate()
        try:
            _moto_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _moto_proc.kill()
    _moto_proc = None


def _fail(message: str) -> None:
    print(f"❌ {message}")
    _cleanup()
    sys.exit(1)


def main() -> None:
    os.chdir(BACKEND_DIR)

    # --- Step 2: .env bootstrap ----------------------------------------------
    env_file = BACKEND_DIR / ".env"
    env_example = BACKEND_DIR / ".env.example"
    if not env_file.exists():
        if not env_example.exists():
            _fail(".env.example is missing -- cannot bootstrap .env")
        shutil.copyfile(env_example, env_file)
        print("✅ Created .env from .env.example")

    # --- Step 3: load .env ----------------------------------------------------
    try:
        from dotenv import load_dotenv
    except ImportError:
        _fail("python-dotenv is not installed. Run: pip install -r requirements.txt -r requirements-dev.txt")
    load_dotenv(env_file, override=True)

    # --- Step 4: start moto server (the only emulator; see module docstring) --
    global _moto_proc
    print(f"Starting moto server on port {MOTO_PORT} ...")
    _moto_proc = subprocess.Popen(
        [sys.executable, "-m", "moto.server", "-p", str(MOTO_PORT)],
        env=_child_env(),
        cwd=str(BACKEND_DIR),
    )
    atexit.register(_cleanup)

    # --- Step 5: wait until moto answers HTTP ---------------------------------
    deadline = time.monotonic() + 20
    ready = False
    while time.monotonic() < deadline:
        if _moto_proc.poll() is not None:
            _fail(f"moto server exited early with code {_moto_proc.returncode}")
        try:
            urllib.request.urlopen(MOTO_URL, timeout=2)
            ready = True
            break
        except urllib.error.HTTPError:
            # Any HTTP response (even an error body) means it's listening.
            ready = True
            break
        except Exception:
            time.sleep(0.5)
    if not ready:
        _fail("moto server did not become reachable within 20s")
    print(f"✅ moto server ready at {MOTO_URL}")

    # --- Step 6: create tables + seed demo data --------------------------------
    for script in ("create_tables.py", "seed_demo_data.py"):
        print(f"Running scripts/{script} ...")
        result = subprocess.run(
            [sys.executable, str(BACKEND_DIR / "scripts" / script)],
            env=_child_env(),
            cwd=str(BACKEND_DIR),
        )
        if result.returncode != 0:
            _fail(f"scripts/{script} failed with exit code {result.returncode}")
    print("✅ Tables created and demo data seeded")

    # --- Step 8: summary ---------------------------------------------------------
    role = os.environ.get("DEV_USER_ROLE", "LeadDataScientist")
    tenant = os.environ.get("DEV_USER_TENANT_ID", "acme-capital")
    print()
    print("=" * 72)
    print("  Truist Model Serving (TMS) -- local dev")
    print("=" * 72)
    print(f"  API           → http://localhost:8001")
    print(f"  API docs      → http://localhost:8001/docs")
    print(f"  moto (DDB)    → {MOTO_URL}")
    print(f"  Dev identity  → role={role} tenant={tenant}")
    print()
    print("  Demo tenants: acme-capital, blue-harbor-bank")
    print("  To switch roles: edit DEV_USER_ROLE (and DEV_USER_TENANT_ID) in")
    print("  .env, then RESTART this script -- env vars are read once at")
    print("  startup; editing .env alone changes nothing while running.")
    print("  Roles: LeadDataScientist (writes), DataScientist (read-only),")
    print("         PlatformAdmin (cross-tenant read-only, tenant forced null)")
    print("=" * 72)
    print()

    # --- Step 9: uvicorn in the foreground (Ctrl+C stops everything) -------------
    try:
        subprocess.run(
            [
                sys.executable, "-m", "uvicorn", "app.main:app",
                "--reload", "--host", "0.0.0.0", "--port", "8001",
            ],
            env=_child_env(),
            cwd=str(BACKEND_DIR),
        )
    except KeyboardInterrupt:
        pass
    finally:
        _cleanup()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        _cleanup()
