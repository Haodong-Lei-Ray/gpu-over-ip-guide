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
    target=(root/'runtime/steam-client/ubuntu12_32/steam').resolve()
    for process in Path('/proc').iterdir():
        if not process.name.isdigit(): continue
        try:
            if process.stat().st_uid==os.getuid() and (process/'exe').resolve()==target:
                return True
        except OSError: pass
    return False
def sunshine_ready():
    try:
        with socket.create_connection(('127.0.0.1',config['sunshine_port']),timeout=2): return True
    except OSError: return False
def display_ready():
    env=dict(os.environ,DISPLAY=':93',XAUTHORITY=str(root/'config/Xauthority'))
    try:
        return subprocess.run(['xdpyinfo'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False
if not config['check_only']:
    for attempt in range(30):
        if steam_ready() and sunshine_ready(): break
        time.sleep(1)
status={'session_entry':True,'steam_ready':steam_ready(),'sunshine_ready':sunshine_ready(),'display_ready':display_ready(),'game_auto_launch':False}
print(json.dumps(status))
if not config['check_only'] and not (status['steam_ready'] and status['sunshine_ready'] and status['display_ready']):
    raise SystemExit('Remote Steam/Sunshine not ready; inspect private remote startup log')
'''


def load_config(path: Path):
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    config=validate_config(config)
    config['_client_state_dir']=str(path.resolve().parent)
    return config


def validate_config(config):
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
    for key in ('ssh_hostname','ssh_user'):
        value=config.get(key)
        if value is not None and (not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_.:@-]+',value) or value.startswith('-')):
            raise ValueError('Invalid '+key)
    if 'ssh_port' in config:
        if isinstance(config['ssh_port'],bool) or not isinstance(config['ssh_port'],int) or not 1<=config['ssh_port']<=65535:
            raise ValueError('ssh_port must be an integer from 1 to 65535')
    if config.get("display_mode", "windowed") not in {"windowed", "fullscreen", "borderless"}:
        raise ValueError("display_mode must be windowed, fullscreen, or borderless")
    return config


def ssh_options(config):
    options=[]
    for key,option in [('ssh_hostname','HostName'),('ssh_user','User')]:
        if config.get(key):options+=['-o',option+'='+config[key]]
    if config.get('ssh_port'):options+=['-p',str(config['ssh_port'])]
    return options


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
    return f'"{python}" "{helper}" %h %p {int(info["index"])} {info["address"]} {host} {int(config.get("ssh_port",22))}'


def prepare_remote(config, status, check_only=False):
    remote_config = {"remote_root": config["remote_root"], "check_only": check_only, "sunshine_port": int(config.get("sunshine_port", 47989))}
    code = "import json\nconfig=json.loads(" + repr(json.dumps(remote_config)) + ")\n" + REMOTE
    base = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10", "-o", "ServerAliveCountMax=2"]
    base += ssh_options(config)
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


def moonlight_processes(executable):
    try:
        processes = powershell_json("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $p=@(Get-CimInstance Win32_Process -Filter \"Name='Moonlight.exe'\" | Select-Object @{Name='Id';Expression={$_.ProcessId}},@{Name='Path';Expression={$_.ExecutablePath}},CommandLine); ConvertTo-Json -InputObject $p -Compress")
        if isinstance(processes, dict):
            processes = [processes]
        return [p for p in processes or [] if p.get("Path") and os.path.normcase(os.path.abspath(p["Path"])) == os.path.normcase(os.path.abspath(executable))]
    except (RuntimeError, ValueError, subprocess.SubprocessError):
        # Avoid creating a second stream when process state cannot be verified.
        raise RuntimeError("无法核对现有 Moonlight，请关闭旧客户端后再试。")


def moonlight_running(executable):
    return bool(moonlight_processes(executable))


def connect_client(config, status):
    running=moonlight_processes(config['moonlight_exe'])
    state_dir=Path(config.get('_client_state_dir',str(Path(__file__).resolve().parents[1]/'private')))
    record=state_dir/'active-moonlight.json'
    if running:
        try:active=json.loads(record.read_text(encoding='utf-8'))
        except (OSError,ValueError):active={}
        expected=subprocess.list2cmdline([config['moonlight_host'],config['moonlight_app']])
        matching=[p for p in running if ' stream ' in (p.get('CommandLine') or '') and (p.get('CommandLine') or '').rstrip().endswith(' '+expected)]
        if matching:
            state_dir.mkdir(parents=True,exist_ok=True)
            record.write_text(json.dumps({'host':config['moonlight_host'],'app':config['moonlight_app'],'pid':matching[0]['Id']}),encoding='utf-8')
            return '远端 Steam 已就绪；所选服务器的 Moonlight 已打开，请切回该窗口。'
        if active.get('host')==config['moonlight_host'] and active.get('app')==config['moonlight_app'] and any(p['Id']==active.get('pid') for p in running):
            return '远端 Steam 已就绪；所选服务器的 Moonlight 已打开，请切回该窗口。'
        raise RuntimeError('Moonlight 已打开，但无法确认它连接的是所选服务器。请先断开并退出现有 Moonlight，再启动所选服务器，避免连接错主机。')
    status("Steam 已就绪，正在打开 Moonlight…")
    command = [config["moonlight_exe"], "stream", "--1080", "--fps", "60", "--bitrate", str(int(config.get("bitrate", 8000))), "--video-codec", "H.264", "--video-decoder", "hardware", "--no-hdr", "--no-quit-after", "--audio-on-host", "--audio-config", "stereo", "--display-mode", config.get("display_mode", "windowed"), "--no-performance-overlay", "--no-absolute-mouse", config["moonlight_host"], config["moonlight_app"]]
    process=subprocess.Popen(command, cwd=config["moonlight_workdir"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=HIDDEN)
    state_dir.mkdir(parents=True,exist_ok=True)
    record.write_text(json.dumps({'host':config['moonlight_host'],'app':config['moonlight_app'],'pid':process.pid}),encoding='utf-8')
    return "已打开远端 Steam。请在游戏库选择你要玩的游戏。"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=Path(__file__).resolve().parents[1] / "private/launcher.json")
    parser.add_argument("--check-only", action="store_true", help="Read-only local/remote prerequisites check")
    parser.add_argument("--prepare-only", action="store_true", help="Prepare remote Steam only; no client GUI or game launch")
    parser.add_argument("--gpu-status", action="store_true")
    parser.add_argument("--render-gpu", type=int)
    parser.add_argument("--stream-gpu", type=int)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--choose-gpu", action="store_true", help="Always open the GPU dashboard, even if Steam is already running")
    parser.add_argument("--servers",type=Path,help="Private multi-server JSON; otherwise auto-detect private/servers.json for GUI startup")
    parser.add_argument("--server",help="Server id from the multi-server JSON; skips the server chooser")
    args = parser.parse_args()
    args.config.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=args.config.parent / "launcher.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", encoding="utf-8")
    cli=bool(args.check_only or args.prepare_only or args.gpu_status or args.plan_only or args.render_gpu is not None or args.stream_gpu is not None)
    profiles=args.servers or (args.config.parent/'servers.json' if not cli or args.server else None)
    if profiles and (args.servers or profiles.is_file()):
        from server_profiles import resolve_server
        selected=resolve_server(profiles,args.server,interactive=False)
        if selected is None:return
        config=selected['config']
    else:
        if args.server:parser.error('--server requires a servers.json configuration')
        config=load_config(args.config)
    if args.gpu_status or args.plan_only or args.render_gpu is not None or args.stream_gpu is not None:
        from gpu_picker import request
        if args.gpu_status:
            print(json.dumps(request(config), ensure_ascii=False)); return
        if args.render_gpu is None or args.stream_gpu is None:
            parser.error("Specify both --render-gpu and --stream-gpu")
        if not (args.plan_only or args.prepare_only):
            parser.error("Use --plan-only or --prepare-only for command-line GPU selection")
        result = request(config, "plan" if args.plan_only else "apply", args.render_gpu, args.stream_gpu)
        print(json.dumps(result, ensure_ascii=False)); return
    if args.check_only or args.prepare_only:
        outcome = prepare_remote(config, lambda text: None, check_only=args.check_only)
        print(json.dumps(outcome))
        return
    from steam_manager import show_manager
    if profiles and profiles.is_file():
        from server_profiles import load_servers
        available,default_id=load_servers(profiles)
        if args.server:default_id=args.server
        source=profiles
    else:
        config['_server_id']='single'
        config['_server_name']=config['ssh_alias']
        available=[{'id':'single','name':config['ssh_alias'],'config':config}]
        default_id='single';source=args.config
    show_manager(available,default_id,source,startup_action='gpus' if args.choose_gpu else 'connect')



if __name__ == "__main__":
    main()
