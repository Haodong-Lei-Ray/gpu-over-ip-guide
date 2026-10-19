"""Linux readiness checks; optional idempotent recovery for a private session.

Default is read-only. --ensure invokes only the already-deployed start-session.sh.
--watch stays in the foreground for an optional user systemd service.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import time
from pathlib import Path


def owned_pids(executable: Path):
    expected = executable.resolve()
    result = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():
            continue
        try:
            if proc.stat().st_uid == os.getuid() and (proc / 'exe').resolve() == expected:
                result.append(int(proc.name))
        except (OSError, RuntimeError):
            pass
    return result


def port_ready(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=2):
            return True
    except OSError:
        return False


def succeeds(command, env):
    try:
        return subprocess.run(command, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL, timeout=5).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def inspect(root, route, display, sunshine_port, juice_port):
    if route == 'juice':
        pids = owned_pids(root / 'agent')
        enough_files = False
        for pid in pids:
            try:
                limits = Path(f'/proc/{pid}/limits').read_text()
                match = re.search(r'^Max open files\s+(\S+)', limits, re.M)
                enough_files |= bool(match and (match[1] == 'unlimited' or int(match[1]) >= 65536))
            except (OSError, ValueError):
                pass
        checks = {'owned_agent': bool(pids), 'loopback_port': port_ready(juice_port),
                  'agent_nofile': enough_files}
    else:
        env = os.environ.copy()
        env.update(DISPLAY=display, XAUTHORITY=str(root / 'config/Xauthority'),
                   PULSE_SERVER='unix:' + str(root / 'runtime/pulse/native'),
                   PULSE_COOKIE=str(root / 'config/pulse-cookie'))
        steam = root / 'runtime/steam-client/ubuntu12_32/steam'
        # Steam's process executable may resolve to its real binary; resolve both.
        checks = {'display': succeeds(['xdpyinfo', '-display', display], env),
                  'audio': succeeds(['pactl', 'info'], env),
                  'sunshine_port': port_ready(sunshine_port),
                  'owned_steam': bool(owned_pids(steam)),
                  'session_entry': (root / 'scripts/start-session.sh').is_file()}
    return {'route': route, 'ready': all(checks.values()), 'checks': checks,
            'game_auto_launch': False}


def once(args):
    result = inspect(args.root, args.route, args.display, args.sunshine_port, args.juice_port)
    result['action'] = 'none'
    if result['ready'] or not (args.ensure or args.watch):
        return result
    entry = args.root / 'scripts/start-session.sh'
    if not entry.is_file():
        result['action'] = 'session-entry-missing'
        return result
    logdir = args.root / 'logs'
    logdir.mkdir(exist_ok=True)
    try:
        with (logdir / 'server-health-recovery.log').open('ab') as log:
            recovery = subprocess.run(['/bin/bash', str(entry)], stdout=log,
                                      stderr=subprocess.STDOUT, timeout=180)
        result['action'] = 'startup-requested' if recovery.returncode == 0 else 'startup-failed'
        if recovery.returncode == 0:
            for _ in range(15):
                latest = inspect(args.root, args.route, args.display, args.sunshine_port, args.juice_port)
                if latest['ready']:
                    latest['action'] = 'startup-requested'
                    return latest
                time.sleep(2)
    except (OSError, subprocess.TimeoutExpired):
        result['action'] = 'startup-error'
    latest = inspect(args.root, args.route, args.display, args.sunshine_port, args.juice_port)
    latest['action'] = result['action']
    return latest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True,
                        help='Streaming deployment directory, or the Juice directory containing agent')
    parser.add_argument('--route', choices=['streaming', 'juice'], default='streaming')
    parser.add_argument('--display', default=':93')
    parser.add_argument('--sunshine-port', type=int, default=47989)
    parser.add_argument('--juice-port', type=int, default=43210)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--ensure', action='store_true')
    mode.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=int, default=60)
    args = parser.parse_args()
    args.root = args.root.expanduser().resolve()
    if not args.root.is_dir():
        parser.error('Configured root directory does not exist')
    if args.interval < 15:
        parser.error('Use a check interval of at least 15 seconds')
    if args.route == 'juice' and (args.ensure or args.watch):
        parser.error('For Juice recovery use the dedicated foreground agent systemd unit')
    lock = None
    if args.ensure or args.watch:
        import fcntl
        private = args.root / 'private'
        private.mkdir(mode=0o700, exist_ok=True)
        lock = (private / 'server-health.lock').open('a')
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'ready': False, 'action': 'another-checker-running'}), flush=True)
            return 2
    try:
        while True:
            result = once(args)
            print(json.dumps(result), flush=True)
            if not args.watch:
                return 0 if result['ready'] else 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0
    finally:
        if lock:
            lock.close()


if __name__ == '__main__':
    raise SystemExit(main())
