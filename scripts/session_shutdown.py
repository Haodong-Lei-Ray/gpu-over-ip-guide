"""Linux Steam shutdown: IPC first, then SIGTERM to verified private master PIDs.

Never signals a process group, uses SIGKILL, or proceeds while the game guard is true.
"""
import os
from pathlib import Path
import signal
import subprocess
import time


def _steam_identity(root, pid):
    """A reused PID, another UID, and a zombie are never a signalling target."""
    p=Path('/proc')/str(pid)
    expected={(root/'runtime/steam-client'/arch/'steam').resolve() for arch in ('ubuntu12_32','ubuntu12_64')}
    try:
        stat=(p/'stat').read_text().rsplit(')',1)[1].split()
        exe=(p/'exe').resolve()
        if p.stat().st_uid!=os.getuid() or stat[0]=='Z' or exe not in expected:return None
        return (int(stat[19]),str(exe))
    except (OSError,RuntimeError):return None


def _steam_masters(root):
    result={}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit():continue
        identity=_steam_identity(root,int(p.name))
        if identity is not None:result[int(p.name)]=identity
    return result


def _guard(game_running):
    if game_running():raise RuntimeError('GAME_RUNNING: Save and exit the game before stopping Steam')


def _wait_steam(root, seconds):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        if not _steam_masters(root):return True
        time.sleep(.25)
    return not _steam_masters(root)


def stop_steam(root, game_running, ipc_wait=12, term_wait=15):
    root=Path(root).resolve()
    _guard(game_running)
    if not _steam_masters(root):return {'method':'already-stopped','term_pids':[]}
    logdir=root/'logs';logdir.mkdir(exist_ok=True)
    with (logdir/'one-click-stop.log').open('ab') as log:
        log.write(b'\nRequesting private Steam -shutdown\n');log.flush()
        try:
            subprocess.run(['/bin/bash',str(root/'scripts/run-steam.sh'),'-shutdown'],stdout=log,stderr=subprocess.STDOUT,timeout=12)
        except subprocess.TimeoutExpired:log.write(b'Steam IPC launcher timeout; checking master processes\n')
        if _wait_steam(root,ipc_wait):return {'method':'steam-ipc','term_pids':[]}
        _guard(game_running)
        targets=_steam_masters(root);sent=[]
        for pid,identity in targets.items():
            _guard(game_running)
            # Re-read identity immediately before signalling, including Linux starttime.
            if _steam_identity(root,pid)!=identity:continue
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:continue
            sent.append(pid);log.write(('SIGTERM private Steam master PID '+str(pid)+'\n').encode());log.flush()
        if not _wait_steam(root,term_wait):
            raise RuntimeError('STEAM_STILL_RUNNING: Steam ignored IPC and verified SIGTERM; stream left running')
    return {'method':'steam-sigterm','term_pids':sent}
