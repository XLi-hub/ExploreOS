#!/usr/bin/env python3
"""Foreground service lifecycle for a persistent ExploreOS installation."""
from __future__ import annotations

import argparse
import fcntl
import json
import signal
import sys
import threading

from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.cloud import runtime


def health():
    record = json.loads(runtime.RECORD.read_text())
    if not runtime.owned(record):
        raise RuntimeError("The owned collaboration service is not running")
    runtime.api("GET", "/workshops")
    if not record.get("frontend_enabled"):
        raise RuntimeError("The native product frontend is disabled")
    import urllib.request
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f"http://127.0.0.1:{record['frontend_port']}/api/v1/exploreos/ui", timeout=5) as response:
        if response.status != 200:
            raise RuntimeError("The product frontend is unavailable")


def serve():
    """Supervise the existing service, leaving all research dispatch explicit."""
    runtime.SERVICE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (runtime.SERVICE / "supervisor.lock").open("a") as lock:
        record = None
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError("Another product supervisor owns this installation") from None
        if runtime.RECORD.exists():
            existing = json.loads(runtime.RECORD.read_text())
            if runtime.alive(int(existing["pid"])):
                raise RuntimeError("Stop the current managed service before starting supervised mode")
        stopping = threading.Event()
        for kind in (signal.SIGTERM, signal.SIGINT):
            signal.signal(kind, lambda *_: stopping.set())
        try:
            runtime.start()
            record = json.loads(runtime.RECORD.read_text())
            print("ExploreOS is ready. No exploration or paid schedule has been started.", flush=True)
            while not stopping.wait(1):
                if not runtime.owned(record):
                    raise RuntimeError("The collaboration service stopped; retained calls must be reconciled before continuing")
                if json.loads(runtime.RECORD.read_text()) != record:
                    raise RuntimeError("The managed service record changed; refusing to adopt a replacement")
        finally:
            # stop() performs its own ownership check. Preserve any unknown calls.
            if record is not None:
                runtime.stop(expected_record=record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("serve", "health"))
    command = parser.parse_args().command
    if command == "serve":
        serve()
    else:
        health()
        print("ExploreOS is ready (service and frontend; no model connectivity test).")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error))
