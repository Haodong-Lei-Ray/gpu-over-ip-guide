"""Own one authenticated SSH/UDP relay per configured streaming server."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import time
import uuid

VERSION=2


def read_json(path):
    try:return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}


def write_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)


def reachable(port):
    try:
        with socket.create_connection(('127.0.0.1',port),timeout=.5):return True
    except OSError:return False


def paths(config):
    folder=Path(config['_client_state_dir']);ident=config['_server_id']
    return folder/('transport-'+ident+'.json'),folder/('transport-'+ident+'-request.json'),folder/('transport-'+ident+'-udp.json')


def udp_ready(path,generation):
    state=read_json(path)
    return state.get('generation')==generation and state.get('ready') is True


def ensure_transport(config,new_session=False):
    settings=config.get('stream_tunnel')
    if not settings:return
    from open_remote_steam import HIDDEN,powershell_json
    record,request,ready=paths(config);ident=config['_server_id'];script=Path(__file__).resolve()
    saved=read_json(record);live=False
    if saved.get('pid'):
        item=powershell_json("[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); $p=Get-CimInstance Win32_Process -Filter 'ProcessId = "+str(int(saved['pid']))+"'; if($null -eq $p){Write-Output 'null'}else{$p | Select-Object CommandLine | ConvertTo-Json -Compress}")
        live=bool(item and str(script).lower() in (item.get('CommandLine') or '').lower() and ident in item['CommandLine'])
    if live and saved.get('version')!=VERSION:
        raise RuntimeError('旧版 SSH 串流通道仍在运行，需要先更新该通道再连接。')
    generation=read_json(request).get('generation')
    if new_session or not generation:
        generation=uuid.uuid4().hex;write_json(request,{'generation':generation})
    if not live:
        folder=Path(config['_client_state_dir'])
        child=subprocess.Popen([sys.executable,str(script),'--server',ident,'--profile',str(folder/'servers.json')],
            cwd=folder,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=HIDDEN)
        write_json(record,{'pid':child.pid,'version':VERSION})
    # A TCP listener alone is insufficient: wait for THIS generation to authenticate
    # and bind all local UDP sockets, with a fresh channel map for the next stream.
    for _ in range(150):
        if udp_ready(ready,generation) and reachable(int(settings['base_port'])):return
        time.sleep(.2)
    raise RuntimeError('SSH 串流通道的 UDP 握手尚未就绪，请查看 private/transport-'+ident+'.log。')


def retire(children):
    for child in children:
        if child.poll() is None:child.terminate()
    for child in children:
        try:child.wait(timeout=5)
        except subprocess.TimeoutExpired:child.kill();child.wait()


def supervise(config,ident):
    from open_remote_steam import HIDDEN,ssh_options
    settings=config['stream_tunnel'];base=int(settings['base_port']);bridge=int(settings['bridge_port'])
    command=['ssh','-N','-o','BatchMode=yes','-o','ConnectTimeout=8','-o','ExitOnForwardFailure=yes','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2']+ssh_options(config)
    for port in [base-5,base,base+1,base+21,bridge]:command+=['-L',f'127.0.0.1:{port}:127.0.0.1:{port}']
    command+=[config['ssh_alias']]
    _,request,ready=paths(config)
    folder=Path(config['_client_state_dir'])
    with (folder/('transport-'+ident+'.log')).open('ab') as log:
        while True:
            generation=read_json(request).get('generation','persistent')
            ready.unlink(missing_ok=True)
            udp=[sys.executable,str(Path(__file__).with_name('ssh_udp_bridge.py')),'client',
                '--token-file',settings['token_file'],'--tcp-port',str(bridge),'--base-port',str(base),
                '--ready-file',str(ready),'--generation',generation]
            children=[];replaced=False
            try:
                children.append(subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=HIDDEN))
                children.append(subprocess.Popen(udp,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=HIDDEN))
                while all(child.poll() is None for child in children):
                    if read_json(request).get('generation','persistent')!=generation:replaced=True;break
                    time.sleep(.2)
            finally:
                retire(children);ready.unlink(missing_ok=True)
            if not replaced:time.sleep(3)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--profile',type=Path,required=True);parser.add_argument('--server',required=True)
    args=parser.parse_args()
    from server_profiles import resolve_server
    supervise(resolve_server(args.profile,args.server,False)['config'],args.server)
