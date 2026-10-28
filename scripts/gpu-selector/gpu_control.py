#!/usr/bin/env python3
"""Private, owner-scoped dual GPU selection. No root, GPU reset or other job control."""
import argparse
import csv
import fcntl
import io
import json
import os
from pathlib import Path
import re
import shlex
import signal
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from process_aliases import aliases_for
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from session_shutdown import stop_steam


def run(args, **kwargs):
    return subprocess.run(args, capture_output=True, text=True, timeout=kwargs.pop('timeout', 12), **kwargs)


def read_json(path, default=None):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return default


def alive(pid):
    try:
        p = Path('/proc') / str(pid)
        return p.stat().st_uid == os.getuid() and (p/'stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
    except OSError:
        return False


def own_procs():
    for p in Path('/proc').iterdir():
        if p.name.isdigit() and alive(int(p.name)):
            yield p


def steam_pids(root):
    target = (root/'runtime/steam-client/ubuntu12_32/steam').resolve()
    result = []
    for p in own_procs():
        try:
            if (p/'exe').resolve() == target:
                result.append(int(p.name))
        except OSError:
            pass
    return result


def games(root):
    """Check graphics windows and owned game images; do not trust the game's argv."""
    found = set()
    gamepath = str(root/'games')+'/'
    for p in own_procs():
        try:
            exe = str((p/'exe').resolve())
            env = dict(x.split(b'=', 1) for x in (p/'environ').read_bytes().split(b'\0') if b'=' in x)
            cmd = (p/'cmdline').read_bytes()
            if exe.startswith(gamepath) or gamepath in (p/'maps').read_text(errors='replace'):
                found.add(int(p.name))
            elif env.get(b'DISPLAY') == b':93' and (exe.lower().endswith('.exe') or b'tlou-' in cmd.lower()):
                if not exe.lower().endswith(('explorer.exe', 'services.exe', 'winedevice.exe', 'rpcss.exe', 'conhost.exe', 'steam.exe')):
                    found.add(int(p.name))
        except OSError:
            pass
    env = dict(os.environ, DISPLAY=':93', XAUTHORITY=str(root/'config/Xauthority'))
    listing = run(['xprop', '-root', '_NET_CLIENT_LIST'], env=env, timeout=5)
    for wid in re.findall(r'0x[0-9a-f]+', listing.stdout):
        text = run(['xprop', '-id', wid, 'WM_CLASS', '_NET_WM_PID'], env=env, timeout=3).stdout
        if re.search(r'steam_app_\d+', text):
            match = re.search(r'_NET_WM_PID[^=]*=\s*(\d+)', text)
            if match and alive(int(match[1])):
                found.add(int(match[1]))
    return sorted(found)


def inventory():
    fields = 'index,uuid,name,pci.bus_id,memory.used,memory.total,utilization.gpu,temperature.gpu,power.draw,utilization.encoder'
    reply = run(['nvidia-smi', '--query-gpu='+fields, '--format=csv,noheader,nounits'], check=True)
    gpus = []
    for row in csv.reader(io.StringIO(reply.stdout), skipinitialspace=True):
        index, uuid, name, pci, used, total, util, temp, power, encoder = (x.strip() for x in row)
        def number(v):
            try: return float(v)
            except ValueError: return None
        gpus.append(dict(index=int(index), uuid=uuid, name=name, pci=pci,
                         used=number(used), total=number(total), utilization=number(util),
                         temperature=number(temp), power=number(power), encoder=number(encoder), processes=[]))
    xml = ET.fromstring(run(['nvidia-smi', '-q', '-x'], check=True).stdout)
    by_uuid = {g['uuid']: g for g in gpus}
    all_processes = {}
    for gpu in xml.findall('gpu'):
        target = by_uuid.get(gpu.findtext('uuid'))
        if target is None: continue
        for item in gpu.findall('./processes/process_info'):
            pid = int(item.findtext('pid'))
            name = item.findtext('process_name') or 'unknown'
            proc = dict(pid=pid, name=name, type=item.findtext('type'), memory=item.findtext('used_memory'))
            target['processes'].append(proc)
            all_processes[pid] = name
    # Stable for each PID for the lifetime of the process, across all four cards.
    python_names = aliases_for(Path(__file__).resolve().parents[2],all_processes)
    for gpu in gpus:
        for proc in gpu['processes']:
            proc['alias'] = python_names[proc['pid']]
    return gpus


def selected(root):
    value = read_json(root/'config/gpu-selection.json')
    if value: return value
    raise RuntimeError('GPU selection missing; server agent must initialize it with init before enabling the picker')


def status(root):
    active_games = games(root)
    choice = selected(root)
    return dict(gpus=inventory(), selection=choice, game_pids=active_games,
                steam_running=bool(steam_pids(root)), timestamp=time.time())


def selection(root, render, stream):
    by_index = {g['index']: g for g in inventory()}
    if render not in by_index or stream not in by_index:
        raise RuntimeError('INVALID_GPU: GPU no longer exists; refresh first')
    r, s = by_index[render], by_index[stream]
    pci = r['pci'].lower()
    domain, bus, df = pci.split(':')
    dev, func = df.split('.')
    if int(domain, 16): raise RuntimeError('Unsupported nonzero PCI domain')
    stream_pci = s['pci'].lower().split(':', 1)[1]
    drm = Path('/dev/dri/by-path')/('pci-0000:'+stream_pci+'-render')
    if not drm.exists(): raise RuntimeError('Selected encoder DRM device not found')
    return dict(render_index=render, stream_index=stream, render_uuid=r['uuid'], stream_uuid=s['uuid'],
                render_pci=r['pci'], stream_pci=s['pci'], xorg_bus=f'PCI:{int(bus,16)}:{int(dev,16)}:{int(func,16)}',
                stream_drm=str(drm.resolve()))


def plan(root, render, stream):
    new = selection(root, render, stream)
    old = selected(root)
    changed = old['render_index'] != render or old['stream_index'] != stream
    active_games = games(root)
    return dict(selection=new, current=old, changed=changed, game_pids=active_games,
                can_apply=not (changed and active_games), restart_session=changed,
                message='GAME_RUNNING' if changed and active_games else 'ready')


def atomic_json(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, indent=2))
    temp.chmod(0o600)
    temp.replace(path)


def saved_pid(root, kind):
    filename = {'display':'display-state.json', 'sunshine':'sunshine-process.json'}[kind]
    state = read_json(root/'config'/filename, {})
    pid = state.get('pid')
    if not pid or not alive(pid): return None
    cmd = (Path('/proc')/str(pid)/'cmdline').read_bytes()
    marker = b'Xorg' if kind == 'display' else b'sunshine'
    if str(root).encode() not in cmd or marker not in cmd:
        raise RuntimeError('Saved '+kind+' process identity mismatch')
    return pid


def stop_session(root):
    if games(root): raise RuntimeError('GAME_RUNNING: Save and exit the game first')
    if run(['systemctl','--user','is-active','--quiet','gpuip-session-watch.service'], timeout=4).returncode == 0:
        raise RuntimeError('WATCHER_ACTIVE: Stop the dedicated recovery watcher first')
    stop_steam(root,lambda: bool(games(root)))
    if games(root): raise RuntimeError('GAME_RUNNING: A game started; stream left intact')
    for kind in ['sunshine', 'display']:
        pid = saved_pid(root, kind)
        if pid:
            # Saved PID is always individually verified. Existing helper stops its owned group.
            done = run(['python3',str(root/'scripts/stop-owned.py'),kind], timeout=12)
            if done.returncode: raise RuntimeError('Cannot stop owned '+kind+': '+done.stderr[-400:])
            for _ in range(50):
                if not alive(pid): break
                time.sleep(.1)
            if alive(pid): raise RuntimeError(kind+' is still exiting')


def start_session(root):
    with (root/'logs/gpu-switch.log').open('ab') as log:
        done = subprocess.run(['bash',str(root/'scripts/start-session.sh')],stdout=log,stderr=log,timeout=145)
    try:
        with socket.create_connection(('127.0.0.1',47989),timeout=2): sunshine=True
    except OSError: sunshine=False
    if done.returncode or not steam_pids(root) or not saved_pid(root,'display') or not saved_pid(root,'sunshine') or not sunshine:
        raise RuntimeError('Dedicated session failed to start; inspect logs/gpu-switch.log')


def apply(root, render, stream):
    with (root/'config/gpu-selector.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = plan(root, render, stream)
        if not result['can_apply']: raise RuntimeError('GAME_RUNNING: Save and exit the game before switching GPUs')
        config = root/'config/gpu-selection.json'
        previous = config.read_bytes() if config.exists() else None
        if result['changed']: stop_session(root)
        atomic_json(config, result['selection'])
        try:
            start_session(root)
        except Exception as error:
            if not result['changed']:
                if previous is None: config.unlink(missing_ok=True)
                else: config.write_bytes(previous)
                raise
            # A failed switch must not report the old choice while the new display is still alive.
            # Recover only via the same game/owner-checked normal shutdown, never force-kill.
            try:
                stop_session(root)
                if previous is None: config.unlink(missing_ok=True)
                else: config.write_bytes(previous)
                start_session(root)
            except Exception as recovery:
                raise RuntimeError('Switch failed and recovery needs attention; inspect logs/gpu-switch.log: '+str(recovery)) from error
            raise RuntimeError('Switch failed; previous session restored. Inspect logs/gpu-switch.log') from error
        result['applied'] = True
        return result


def shell_env(root):
    choice = selected(root)
    # Match the selected stable GPU UUID to the Vulkan loader's physical-device ordinal.
    env = dict(os.environ, DISPLAY=':93', XAUTHORITY=str(root/'config/Xauthority'),
               VK_ICD_FILENAMES='/usr/share/vulkan/icd.d/nvidia_icd.json', __NV_PRIME_RENDER_OFFLOAD='1')
    probe = run(['python3',str(root/'scripts/vulkan-devices.py')], env=env, check=True)
    devices = json.loads(probe.stdout)
    chosen = next(g for g in inventory() if g['index'] == choice['render_index'])
    uuid = chosen['uuid'].removeprefix('GPU-').replace('-', '').lower()
    matches = [d['index'] for d in devices if d['uuid_hex'].lower() == uuid]
    if len(matches) != 1: raise RuntimeError('Selected GPU UUID not visible to Vulkan')
    values = dict(CUDA_VISIBLE_DEVICES=chosen['uuid'], VKD3D_VULKAN_DEVICE=str(matches[0]),
                  GPUIP_RENDER_GPU=str(choice['render_index']), GPUIP_STREAM_GPU=str(choice['stream_index']))
    return '\n'.join('export '+k+'='+shlex.quote(v) for k,v in values.items())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('action', choices=['status','plan','apply','env','init'])
    parser.add_argument('--render', type=int)
    parser.add_argument('--stream', type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    if not (root/'scripts/start-session.sh').is_file() or root.stat().st_uid != os.getuid():
        raise RuntimeError('Invalid private deployment')
    if args.action == 'env': print(shell_env(root)); return
    if args.action == 'status': result = status(root)
    else:
        if args.render is None or args.stream is None: parser.error('Select both GPU roles')
        if args.action == 'init':
            if (root/'config/gpu-selection.json').exists(): raise RuntimeError('Initial selection already exists; use plan/apply')
            if steam_pids(root) or saved_pid(root,'display') or saved_pid(root,'sunshine'):
                raise RuntimeError('Initialize only before starting the dedicated session')
            result=selection(root,args.render,args.stream)
            atomic_json(root/'config/gpu-selection.json',result)
        else:
            result = (plan if args.action == 'plan' else apply)(root, args.render, args.stream)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
