"""Close this private remote Steam/Sunshine session, never the server itself."""
import argparse
import json
import logging
import subprocess
import threading
from pathlib import Path

from open_remote_steam import HIDDEN, direct_transport, load_config, ssh_options

REMOTE = r'''
import json,os,re,subprocess,time
from pathlib import Path
root=Path(config['remote_root']).resolve()
if not root.is_absolute() or not (root/'scripts/run-steam.sh').is_file():
    raise SystemExit('Dedicated deployment not found')
env=os.environ.copy()
env.update(DISPLAY=':93',XAUTHORITY=str(root/'config/Xauthority'))
def own_processes():
    for p in Path('/proc').iterdir():
        if p.name.isdigit():
            try:
                if p.stat().st_uid==os.getuid():yield p
            except OSError:pass
def steam_pids():
    target=(root/'runtime/steam-client/ubuntu12_32/steam').resolve()
    out=[]
    for p in own_processes():
        try:
            if (p/'exe').resolve()==target:out.append(int(p.name))
        except OSError:pass
    return out
def game_running():
    gamepath=str(root/'games')+'/'
    for p in own_processes():
        try:
            if str((p/'exe').resolve()).startswith(gamepath):return True
            if gamepath in (p/'maps').read_text(errors='replace'):return True
            cmd=(p/'cmdline').read_bytes()
            if str(root).encode() in cmd and (b'/proton\x00' in cmd or b'run-last-of-us-proton.sh' in cmd):return True
        except OSError:pass
    try:
        listing=subprocess.run(['xprop','-root','_NET_CLIENT_LIST'],env=env,capture_output=True,text=True,timeout=5)
        for wid in re.findall(r'0x[0-9a-f]+',listing.stdout):
            props=subprocess.run(['xprop','-id',wid,'WM_CLASS','_NET_WM_PID'],env=env,capture_output=True,text=True,timeout=3).stdout
            if re.search(r'steam_app_\d+',props):
                match=re.search(r'_NET_WM_PID[^=]*=\s*(\d+)',props)
                if match and Path('/proc/'+match[1]).stat().st_uid==os.getuid():return True
    except (OSError,subprocess.TimeoutExpired):pass
    return False
def watcher_active():
    try:
        return subprocess.run(['systemctl','--user','is-active','--quiet','gpuip-session-watch.service'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=4).returncode==0
    except (OSError,subprocess.TimeoutExpired):return False
def saved_alive(kind):
    state=root/'config'/({'sunshine':'sunshine-process.json','display':'display-state.json'}[kind])
    try:
        pid=int(json.loads(state.read_text())['pid']);p=Path('/proc')/str(pid)
        if not p.exists():return False
        if p.stat().st_uid!=os.getuid():raise RuntimeError('Saved process owner mismatch')
        if (p/'stat').read_text().rsplit(')',1)[1].split()[0]=='Z':return False
        cmd=(p/'cmdline').read_bytes()
        expected=b'sunshine' if kind=='sunshine' else b'Xorg'
        if str(root).encode() not in cmd or expected not in cmd:raise RuntimeError('Saved process identity mismatch')
        return True
    except FileNotFoundError:return False
def inspect():
    return {'steam_running':bool(steam_pids()),'game_running':game_running(),
            'sunshine_running':saved_alive('sunshine'),'display_running':saved_alive('display'),
            'watcher_active':watcher_active()}
state=inspect()
if config['check_only']:
    print(json.dumps(state));raise SystemExit(0)
if state['game_running']:
    raise SystemExit('GAME_RUNNING: Please save and exit the remote game first. Nothing was stopped.')
if state['watcher_active']:
    raise SystemExit('WATCHER_ACTIVE: Automatic session recovery is enabled. Stop that supervisor before closing this session.')
# Request ordinary Steam exit, never kill its process group or force-close a game.
if state['steam_running']:
    logdir=root/'logs';logdir.mkdir(exist_ok=True)
    with (logdir/'one-click-stop.log').open('ab') as log:
        try:
            subprocess.run(['/bin/bash',str(root/'scripts/run-steam.sh'),'-shutdown'],stdout=log,stderr=subprocess.STDOUT,timeout=12)
        except subprocess.TimeoutExpired:pass
    for _ in range(40):
        if not steam_pids():break
        time.sleep(1)
    if steam_pids():raise SystemExit('STEAM_STILL_RUNNING: Steam did not exit normally; streaming was left running.')
if game_running():raise SystemExit('GAME_RUNNING: A game appeared during shutdown; streaming was left running.')
for kind in ('sunshine','display'):
    if saved_alive(kind):
        result=subprocess.run(['python3',str(root/'scripts/stop-owned.py'),kind],capture_output=True,text=True,timeout=12)
        if result.returncode:raise SystemExit('Owned '+kind+' stop failed; inspect the private deployment.')
        if saved_alive(kind):raise SystemExit('Owned '+kind+' is still exiting; retry later.')
# This socket and cookie belong only to the dedicated streaming audio server.
audio_env=os.environ.copy();audio_env.update(PULSE_SERVER='unix:'+str(root/'runtime/pulse/native'),PULSE_COOKIE=str(root/'config/pulse-cookie'))
try:
    subprocess.run(['pactl','exit'],env=audio_env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=5)
except (OSError,subprocess.TimeoutExpired):pass
final=inspect();final['stopped']=not any(final[k] for k in ('steam_running','sunshine_running','display_running'))
print(json.dumps(final))
if not final['stopped']:raise SystemExit(1)
'''


def remote(config, check_only=False):
    parameters={'remote_root':config['remote_root'],'check_only':check_only}
    code='import json\nconfig=json.loads('+repr(json.dumps(parameters))+')\n'+REMOTE
    base=['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2']
    base+=ssh_options(config)
    result=subprocess.run(base+[config['ssh_alias'],'python3','-'],input=code,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=115,creationflags=HIDDEN)
    if result.returncode==255 and config.get('direct_ssh_fallback'):
        proxy=direct_transport(config)
        result=subprocess.run(base+['-o','ProxyCommand='+proxy,config['ssh_alias'],'python3','-'],input=code,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=115,creationflags=HIDDEN)
    if result.returncode:
        error=result.stderr[-2000:]
        logging.error('Remote stop failed: %s',error)
        if 'GAME_RUNNING' in error:raise RuntimeError('检测到远端游戏仍在运行。请先保存并正常退出游戏，再运行此脚本。')
        if 'WATCHER_ACTIVE' in error:raise RuntimeError('检测到自动恢复守护正在运行。请先停止该守护，避免关闭后自动重启。')
        if 'STEAM_STILL_RUNNING' in error:raise RuntimeError('Steam 未能正常退出。串流已保留，请在远端 Steam 内手动退出后再试。')
        raise RuntimeError('远端关闭未完成，请查看本机 private/close-remote-steam.log；没有执行服务器关机或强制结束游戏。')
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--check-only',action='store_true')
    parser.add_argument('--servers',type=Path)
    parser.add_argument('--server')
    args=parser.parse_args()
    logging.basicConfig(filename=args.config.parent/'close-remote-steam.log',level=logging.INFO,encoding='utf-8')
    profiles=args.servers or args.config.parent/'servers.json'
    if profiles.is_file():
        from server_profiles import resolve_server
        selected=resolve_server(profiles,args.server,interactive=False)
        if selected is None:return
        config=selected['config']
    else:
        if args.servers or args.server:parser.error('Server configuration not found')
        config=load_config(args.config)
    if args.check_only:
        print(json.dumps(remote(config,True)));return
    from steam_manager import show_manager
    if profiles.is_file():
        from server_profiles import load_servers
        available,default_id=load_servers(profiles)
        if args.server:default_id=args.server
        source=profiles
    else:
        config['_server_id']='single';config['_server_name']=config['ssh_alias']
        available=[{'id':'single','name':config['ssh_alias'],'config':config}]
        default_id='single';source=args.config
    show_manager(available,default_id,source,startup_action='stop')



if __name__=='__main__':main()
