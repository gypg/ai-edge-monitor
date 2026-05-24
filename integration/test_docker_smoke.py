from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "ai-edge-monitor:smoke"


def main() -> int:
    if shutil.which("docker") is None:
        print(json.dumps({"result": "SKIP", "reason": "docker command not available"}))
        return 0

    build = subprocess.run(
        ["docker", "build", "-t", IMAGE, str(ROOT)],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if build.returncode != 0:
        print(build.stdout)
        print(json.dumps({"result": "FAIL", "step": "build"}))
        return 1

    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "reports"
        out_dir.mkdir()
        docker_run = ["docker", "run", "--rm"]
        if hasattr(os, "getuid") and hasattr(os, "getgid"):
            docker_run.extend(["--user", f"{os.getuid()}:{os.getgid()}"])
        docker_run.extend(
            [
                "-v",
                f"{out_dir}:/out",
                IMAGE,
                "ai-edge-monitor",
                "run",
                "--duration",
                "5",
                "--interval",
                "1000",
                "--out",
                "/out/demo",
                "--force-dummy",
            ]
        )
        run = subprocess.run(
            docker_run,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        if run.returncode != 0:
            print(run.stdout)
            print(json.dumps({"result": "FAIL", "step": "run"}))
            return 1
        expected = [
            out_dir / "demo" / "metrics.jsonl",
            out_dir / "demo" / "metrics.csv",
            out_dir / "demo" / "summary.json",
            out_dir / "demo" / "report.png",
        ]
        missing = [str(path) for path in expected if not path.is_file() or path.stat().st_size == 0]
        if missing:
            print(run.stdout)
            print(json.dumps({"result": "FAIL", "step": "outputs", "missing": missing}))
            return 1

    print(json.dumps({"result": "PASS", "image": IMAGE}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
