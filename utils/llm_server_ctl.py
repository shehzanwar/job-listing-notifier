"""Start/stop/check the llama.cpp server as a detached background process.

Unlike main_filter.py's start_llama_server() (which owns the subprocess for
the lifetime of one filter run and shuts it down when done), this is for
leaving the server running across multiple separate commands -- e.g. while
iterating on filters/llm_judge.py's prompt/parsing during calibration.

Usage:
    python -m utils.llm_server_ctl start
    python -m utils.llm_server_ctl status
    python -m utils.llm_server_ctl stop
"""
import sys
import time
import subprocess
from pathlib import Path

import httpx
import yaml

PID_FILE = Path(".llm_server.pid")


def load_llm_config():
    with open("config/settings.yaml") as f:
        return yaml.safe_load(f)["llm"]


def is_healthy(llm_cfg) -> bool:
    try:
        r = httpx.get(f"http://{llm_cfg['server_host']}:{llm_cfg['server_port']}/health", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def start():
    llm_cfg = load_llm_config()

    if PID_FILE.exists() and is_healthy(llm_cfg):
        print(f"Already running (pid {PID_FILE.read_text().strip()}), reachable on "
              f"{llm_cfg['server_host']}:{llm_cfg['server_port']}.")
        return

    cmd = [
        llm_cfg.get("llama_server_path", "llama-server"),
        "-m", llm_cfg["model_path"],
        "--host", llm_cfg["server_host"],
        "--port", str(llm_cfg["server_port"]),
        "-ngl", str(llm_cfg["gpu_layers"]),
        "-c", str(llm_cfg["context_size"]),
        "--flash-attn", "on" if llm_cfg.get("flash_attn", True) else "off",
        "-t", str(llm_cfg["threads"]),
        "--temp", str(llm_cfg["temperature"]),
        "--top-p", str(llm_cfg["top_p"]),
    ]

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS

    log = open("logs/llm_server.log", "a")
    process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=creationflags)
    PID_FILE.write_text(str(process.pid))

    print(f"Starting llama-server (pid {process.pid}), logging to logs/llm_server.log ...")
    startup_wait = llm_cfg.get("startup_wait", 30)
    for _ in range(startup_wait * 2):
        time.sleep(0.5)
        if is_healthy(llm_cfg):
            print(f"Ready on {llm_cfg['server_host']}:{llm_cfg['server_port']}")
            return
    print("Warning: server did not report healthy within the startup window; "
          "check logs/llm_server.log")


def status():
    llm_cfg = load_llm_config()
    if not PID_FILE.exists():
        print("Not running (no pid file).")
        return
    pid = PID_FILE.read_text().strip()
    if is_healthy(llm_cfg):
        print(f"Running (pid {pid}), healthy on {llm_cfg['server_host']}:{llm_cfg['server_port']}.")
    else:
        print(f"Pid file exists ({pid}) but server is not responding to /health.")


def stop():
    if not PID_FILE.exists():
        print("Not running (no pid file).")
        return
    pid = PID_FILE.read_text().strip()
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", pid, "/F", "/T"], capture_output=True)
    else:
        import os
        import signal
        os.kill(int(pid), signal.SIGTERM)
    PID_FILE.unlink()
    print(f"Stopped (pid {pid}).")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    {"start": start, "stop": stop, "status": status}.get(
        action, lambda: print(__doc__)
    )()
