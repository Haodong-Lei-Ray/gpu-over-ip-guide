"""Windows one-click remote Steam bootstrap. Configuration stays in private/.

Never starts a game, changes VPN settings, or replaces SSH authentication.
Python 3.10+ and tkinter are required for the progress window.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path

HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
REMOTE = r'''
import json, os, socket, subprocess, time
from pathlib import Path
root=Path(config['remote_root'])
entry=root/'scripts/start-session.sh'
if not root.is_absolute() or not entry.is_file():
    raise SystemExit('Server session entry missing; server agent must prepare scripts/start-session.sh')
if not config['check_only']:
    logdir=root/'logs'
    logdir.mkdir(exist_ok=True)
    with (logdir/'one-click-steam.log').open('ab') as log:
        log.write(('\nRemote Steam bootstrap '+time.strftime('%Y-%m-%d %H:%M:%S')+'\n').encode())
        result=subprocess.run(['/bin/bash',str(entry)],stdout=log,stderr=subprocess.STDOUT,timeout=140)
    if result.returncode:
        raise SystemExit('Session bootstrap failed; inspect private remote logs/one-click-steam.log')
def steam_ready():
    target=str(root/'runtime/steam-client/ubuntu12_32/steam').encode()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            if process.stat().st_uid==os.getuid() and (process/'cmdline').read_bytes().split(b'\0')[0]==target:
                return True
        except OSError: pass
    return False
def sunshine_ready():
    try:
        with socket.create_connection(('127.0.0.1',config['sunshine_port']),timeout=2): return True
    except OSError: return False
if not config['check_only']:
    for attempt in range(30):
        if steam_ready() and sunshine_ready(): break
        time.sleep(1)
status={'session_entry':True,'steam_ready':steam_ready(),'sunshine_ready':sunshine_ready(),'game_auto_launch':False}
print(json.dumps(status))
if not config['check_only'] and not (status['steam_ready'] and status['sunshine_ready']):
    raise SystemExit('Remote Steam/Sunshine not ready; inspect private remote startup log')
'''


def load_config(path: Path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    for name in ("ssh_alias", "remote_root", "moonlight_exe", "moonlight_host", "moonlight_app"):
        if not isinstance(config.get(name), str) or not config[name] or any(c in config[name] for c in "\r\n\0"):
            raise ValueError(f"Invalid or missing configuration field: {name}")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", config["ssh_alias"]):
        raise ValueError("Use a simple SSH Host alias")
    if not config["remote_root"].startswith("/"):
        raise ValueError("remote_root must be an absolute Linux path")
    executable = Path(config["moonlight_exe"])
    if not executable.is_file():
        raise ValueError("Configured Moonlight executable not found")
    workdir = Path(config.get("moonlight_workdir", str(executable.parent)))
    if not workdir.is_dir():
        raise ValueError("Moonlight working directory not found")
    if config.get("portable", True) and not (workdir / "portable.dat").is_file():
        raise ValueError("portable.dat missing from Moonlight working directory")
    config["moonlight_workdir"] = str(workdir)
    if config.get("display_mode", "windowed") not in {"windowed", "fullscreen", "borderless"}:
        raise ValueError("display_mode must be windowed, fullscreen, or borderless")
    return config


def powershell_json(command):
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=18, creationflags=HIDDEN)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError("Cannot read local process/network state")
    return json.loads(result.stdout.lstrip("\ufeff"))


def direct_transport(config):
    """Opt-in per-socket interface binding. Never edits routes or VPN state."""
    host = config.get("direct_ssh_host")
    if not host or any(c in host for c in '" \r\n\0'):
        raise ValueError("Set direct_ssh_host before enabling fallback")
    command = "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $a=@(Get-NetAdapter -Physical | Where-Object Status -eq Up); if($a.Count -ne 1){exit 3}; $v=@(Get-NetIPAddress -InterfaceIndex $a[0].ifIndex -AddressFamily IPv4 | Where-Object {$_.AddressState -eq 'Preferred' -and $_.IPAddress -notlike '169.254.*'}); if($v.Count -ne 1){exit 4}; @{index=$a[0].ifIndex;address=$v[0].IPAddress}|ConvertTo-Json -Compress"
    info = powershell_json(command)
    helper = Path(__file__).with_name("direct_ssh_transport.py")
    python = Path(sys.executable).with_name("python.exe")
    if not helper.is_file() or not python.is_file():
        raise ValueError("Direct SSH transport helper missing")
    return f'"{python}" "{helper}" %h %p {int(info["index"])} {info["address"]} {host}'


def prepare_remote(config, status, check_only=False):
    remote_config = {"remote_root": config["remote_root"], "check_only": check_only, "sunshine_port": int(config.get("sunshine_port", 47989))}
    code = "import json\nconfig=json.loads(" + repr(json.dumps(remote_config)) + ")\n" + REMOTE
    base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
    status("正在连接服务器，检查远端 Steam…")
    transport_name = "default"
    result = subprocess.run(base + [config["ssh_alias"], "python3", "-"], input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=200, creationflags=HIDDEN)
    if result.returncode == 255 and config.get("direct_ssh_fallback", False):
        status("普通 SSH 未连通，改用现有物理网卡直连；VPN 保持运行…")
        transport = direct_transport(config)
        transport_name = "physical"
        result = subprocess.run(base + ["-o", "ProxyCommand=" + transport, config["ssh_alias"], "python3", "-"], input=code, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=200, creationflags=HIDDEN)
    if result.returncode:
        logging.error("SSH bootstrap failed (status %s): %s", result.returncode, result.stderr[-2000:])
        raise RuntimeError("远端连接或会话启动失败。请查看本机私有日志；VPN 未被修改。\n若是首次 SSH 或登录过期，请先手动完成认证。")
    try:
        outcome = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as error:
        raise RuntimeError("Remote readiness response invalid") from error
    outcome["ssh_transport"] = transport_name
    return outcome


def moonlight_running(executable):
    try:
        processes = powershell_json("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $p=@(Get-Process -Name Moonlight -ErrorAction SilentlyContinue | Select-Object Id,Path); ConvertTo-Json -InputObject $p -Compress")
        if isinstance(processes, dict):
            processes = [processes]
        return any(p.get("Path") and os.path.normcase(os.path.abspath(p["Path"])) == os.path.normcase(os.path.abspath(executable)) for p in processes or [])
    except (RuntimeError, ValueError, subprocess.SubprocessError):
        # Avoid creating a second stream when process state cannot be verified.
        raise RuntimeError("无法核对现有 Moonlight，请关闭旧客户端后再试。")


def connect_client(config, status):
    if moonlight_running(config["moonlight_exe"]):
        return "远端 Steam 已就绪；Moonlight 已打开，请切回该窗口。"
    status("Steam 已就绪，正在打开 Moonlight…")
    command = [config["moonlight_exe"], "stream", "--1080", "--fps", "60", "--bitrate", str(int(config.get("bitrate", 8000))), "--video-codec", "H.264", "--video-decoder", "hardware", "--no-hdr", "--display-mode", config.get("display_mode", "windowed"), "--no-performance-overlay", "--no-absolute-mouse", config["moonlight_host"], config["moonlight_app"]]
    subprocess.Popen(command, cwd=config["moonlight_workdir"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN)
    return "已打开远端 Steam。请在游戏库选择你要玩的游戏。"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "private/launcher.json")
    parser.add_argument("--check-only", action="store_true", help="Read-only local/remote prerequisites check")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare remote Steam only; no client GUI or game launch")
    args = parser.parse_args()
    args.config.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.config.parent / "launcher.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    if args.check_only or args.prepare_only:
        config = load_config(args.config)
        outcome = prepare_remote(config, lambda text: None, check_only=args.check_only)
        print(json.dumps(outcome))
        return
    import tkinter as tk
    from tkinter import ttk
    import msvcrt
    lock = (args.config.parent / "launcher.lock").open("a+b")
    lock.seek(0)
    if lock.read(1) == b"":
        lock.write(b"0"); lock.flush()
    lock.seek(0)
    try:
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        lock.close()
        return
    app = tk.Tk()
    app.title("启动远程 Steam")
    app.geometry("540x235")
    app.resizable(False, False)
    app.configure(bg="#f4f6f0")
    tk.Label(app, text="启动远程 Steam", bg="#f4f6f0", fg="#1b6047", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w", padx=25, pady=(22, 12))
    label = tk.Label(app, text="正在检查连接…", bg="#f4f6f0", fg="#243c30", wraplength=485, justify="left", font=("Microsoft YaHei UI", 10))
    label.pack(anchor="w", padx=25)
    progress = ttk.Progressbar(app, mode="indeterminate", length=485)
    progress.pack(padx=25, pady=18)
    progress.start(15)
    tk.Label(app, text="保留 VPN · 复用已有会话 · 不自动启动游戏", bg="#f4f6f0", fg="#69776d", font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=25)
    messages = queue.Queue()
    def worker():
        try:
            config = load_config(args.config)
            prepare_remote(config, lambda text: messages.put(("status", text)))
            message = connect_client(config, lambda text: messages.put(("status", text)))
            messages.put(("done", message))
        except Exception as error:
            logging.exception("Launcher failed")
            messages.put(("error", str(error)))
    def poll():
        try:
            while True:
                kind, text = messages.get_nowait()
                label.config(text=text)
                if kind in {"done", "error"}:
                    progress.stop()
                    if kind == "done":
                        app.after(1800, app.destroy)
                    else:
                        label.config(fg="#9a3829")
                    return
        except queue.Empty:
            app.after(120, poll)
    threading.Thread(target=worker, daemon=True).start()
    app.after(100, poll)
    app.mainloop()
    lock.close()


if __name__ == "__main__":
    main()
