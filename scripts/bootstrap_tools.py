"""Install checksummed vendor tools locally; no global Java, Docker or service changes."""

import hashlib
import json
import platform
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / ".tools"


def host_key() -> str:
    machine = {"aarch64": "arm64", "AMD64": "x86_64"}.get(platform.machine(), platform.machine())
    return f"{platform.system().lower()}-{machine}"


def main() -> None:
    host = host_key()
    manifest = json.loads((ROOT / "tools.lock.json").read_text())
    if host not in {a["platform"] for a in manifest["artifacts"] if a["id"] == "jre"}:
        raise SystemExit(f"Unqualified platform: {host}; add reviewed artifact pins first")
    for item in manifest["artifacts"]:
        if item["platform"] not in ("all", host):
            continue
        target = TOOLS / item["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != item["sha256"]:
            temporary = target.with_suffix(target.suffix + ".part")
            try:
                subprocess.run(
                    [
                        "curl",
                        "--fail",
                        "--location",
                        "--silent",
                        "--show-error",
                        "--proto",
                        "=https",
                        "--proto-redir",
                        "=https",
                        "--retry",
                        "2",
                        "--max-time",
                        "300",
                        item["url"],
                        "-o",
                        str(temporary),
                    ],
                    check=True,
                    timeout=660,
                )
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != item["sha256"]:
                    raise RuntimeError(f"Checksum mismatch: {item['id']}")
                temporary.replace(target)
            finally:
                temporary.unlink(missing_ok=True)
        if item["id"] == "jre":
            destination = TOOLS / "jre" / item["sha256"]
            marker = destination / ".extracted"
            if not marker.exists():
                destination.mkdir(parents=True, exist_ok=True)
                with tarfile.open(target) as archive:
                    archive.extractall(destination, filter="data")
                marker.touch()
            matches = list(destination.rglob("bin/java"))
            if len(matches) != 1:
                raise RuntimeError("Expected exactly one Java executable")
            (TOOLS / "java-path.txt").write_text(str(matches[0]) + "\n")
        print(f"Verified {item['id']} {item['version']}")


if __name__ == "__main__":
    main()
