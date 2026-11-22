"""Run a Compose build while enforcing the host disk floor, then prune build caches."""

import os
import shutil
import signal
import subprocess
import sys
from time import monotonic, sleep


def main() -> int:
    floor = 5 * 1024**3
    if shutil.disk_usage(".").free < floor:
        raise SystemExit("Stopped before build: less than 5 GiB free")
    started = monotonic()
    proc = subprocess.Popen(["docker", "compose", *sys.argv[1:]], start_new_session=True)
    try:
        while proc.poll() is None:
            if shutil.disk_usage(".").free < floor:
                raise RuntimeError("Stopped during build: less than 5 GiB free")
            sleep(1)
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait()
        print(
            f"Compose exit={proc.returncode}, elapsed_seconds={monotonic() - started:.2f}",
            flush=True,
        )
        subprocess.run(["docker", "image", "prune", "-f"], check=True)
        subprocess.run(["docker", "builder", "prune", "-af"], check=True)
    if shutil.disk_usage(".").free < floor:
        raise SystemExit("Stopped after build: less than 5 GiB free")
    return proc.returncode


if __name__ == "__main__":
    raise SystemExit(main())
