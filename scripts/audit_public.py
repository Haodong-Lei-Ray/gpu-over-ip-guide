"""Audit publishable files without printing matching secret values."""
from __future__ import annotations

import ipaddress
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCKED_PARTS = {"private", "logs", "runtime", "downloads", "userdata", "compatdata", "juice-client", "juice-server", "moonlight"}
BLOCKED_SUFFIXES = {".exe", ".dll", ".zip", ".gz", ".xz", ".pem", ".key", ".pfx", ".ppk", ".dmp", ".log", ".csv", ".pyc"}
RULES = {
    "private-key": re.compile(r"-----BEGIN (?:[A-Z]+ )*PRIVATE KEY-----"),
    "github-token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    "cloud-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "gpu-uuid": re.compile(r"\bGPU-[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}\b"),
    "personal-windows-home": re.compile(r"[A-Za-z]:[\\/]Users[\\/](?!<|USER|user|example)[A-Za-z0-9_.-]+[\\/]"),
    "personal-linux-home": re.compile(r"/home2?/((?!user/|example/)[A-Za-z0-9_.-]+)/"),
    "embedded-auth-url": re.compile(r"https?://[^\s/@]+:[^\s/@]+@"),
}
IPV4 = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")
EXAMPLE_NETWORKS = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


def files_to_audit():
    if (ROOT / ".git").is_dir():
        result = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT, capture_output=True, check=True)
        return sorted({ROOT / p for p in result.stdout.decode("utf-8").split("\0") if p})
    return sorted(p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.relative_to(ROOT).parts)


def main():
    failures = []
    files = files_to_audit()
    for path in files:
        relative = path.relative_to(ROOT)
        if not path.is_file():
            continue
        if any(part.lower() in BLOCKED_PARTS for part in relative.parts[:-1]) or path.suffix.lower() in BLOCKED_SUFFIXES:
            failures.append((str(relative), "runtime-or-binary-file"))
            continue
        if path.name.startswith(".env") and path.name != ".env.example":
            failures.append((str(relative), "environment-file"))
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeError:
            failures.append((str(relative), "non-text-file"))
            continue
        for name, pattern in RULES.items():
            if pattern.search(text):
                failures.append((str(relative), name))
        for token in IPV4.findall(text):
            try:
                address = ipaddress.ip_address(token)
            except ValueError:
                continue
            if str(address) in {"127.0.0.1", "0.0.0.0"} or any(address in network for network in EXAMPLE_NETWORKS):
                continue
            failures.append((str(relative), "non-example-ipv4"))
    markdown = {p.relative_to(ROOT).as_posix() for p in files if p.suffix == ".md"}
    if markdown != {"README.md", "client.md", "server.md"}:
        failures.append(("repository", "expected-three-markdown-files"))
    if failures:
        for filename, rule in sorted(set(failures)):
            print(f"FAIL {filename}: {rule}")
        return 1
    print(f"PASS: {len(files)} public text files; 3 Markdown guides; no detected private values")
    return 0


if __name__ == "__main__":
    sys.exit(main())
