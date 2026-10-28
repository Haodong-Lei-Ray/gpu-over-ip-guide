"""Display aliases only, stable across dashboard and terminal for a PID lifetime."""
import fcntl
import json
from pathlib import Path


def aliases_for(root, pids):
    folder=Path(root)/'config'
    cache=folder/'process-aliases.json'
    with (folder/'process-aliases.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:data=json.loads(cache.read_text())
        except FileNotFoundError:data={'next':1,'processes':{}}
        result={};changed=False
        for pid in sorted(set(map(int,pids))):
            try:
                # PID reuse creates a new identity. Linux stat field 22 is starttime.
                start=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()[19]
            except OSError:start='gone'
            key=f'{pid}:{start}'
            if key not in data['processes']:
                data['processes'][key]='python'+str(data['next']);data['next']+=1;changed=True
            result[pid]=data['processes'][key]
        if changed:
            temp=cache.with_suffix('.tmp');temp.write_text(json.dumps(data,indent=2));temp.chmod(0o600);temp.replace(cache)
        return result
