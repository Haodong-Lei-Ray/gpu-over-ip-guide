#!/usr/bin/env python3
"""Bounded startup order for an already deployed private streaming session.

The deployment supplies idempotent start-display/audio/steam/sunshine.py helpers.
This orchestrator installs no software and does not start a game.
"""
from pathlib import Path
import subprocess
import sys
import time


def start(root):
    phases=[('display',35),('audio',25),('steam',25),('sunshine',25)]
    if (root/'scripts/start-transport.py').is_file():phases.insert(0,('transport',12))
    for phase,limit in phases:
        print(time.strftime('%Y-%m-%d %H:%M:%S')+' START_STAGE '+phase,flush=True)
        try:
            result=subprocess.run([sys.executable,str(root/'scripts'/('start-'+phase+'.py'))],timeout=limit)
        except subprocess.TimeoutExpired:
            raise RuntimeError('STAGE_TIMEOUT: '+phase+' did not finish in '+str(limit)+' seconds') from None
        if result.returncode:raise RuntimeError('STAGE_FAILED: '+phase+' exited '+str(result.returncode))
        print(time.strftime('%Y-%m-%d %H:%M:%S')+' READY_STAGE '+phase,flush=True)


if __name__=='__main__':
    try:start(Path(__file__).resolve().parents[1])
    except RuntimeError as error:raise SystemExit(str(error))
