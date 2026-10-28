#!/usr/bin/env python3
"""Labelled nvidia-smi display wrapper; raw/query/management modes are untouched."""
import os
from pathlib import Path
import re
import subprocess
import sys
from process_aliases import aliases_for

REAL='/usr/bin/nvidia-smi'
args=sys.argv[1:]
if args:
    if args==['--real']:args=[]
    os.execv(REAL,[REAL,*args])
result=subprocess.run([REAL],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
sys.stderr.write(result.stderr)
if result.returncode:
    sys.stdout.write(result.stdout);raise SystemExit(result.returncode)
pattern=re.compile(r'^(\|\s+\d+\s+\S+\s+\S+\s+)(\d+)(\s+\S+\s+)(.*?)(\s+\d+\s*MiB\s*\|)\s*$')
lines=result.stdout.splitlines()
matches=[pattern.match(line) for line in lines]
aliases=aliases_for(Path(__file__).resolve().parents[2],[int(m[2]) for m in matches if m])
print('[显示别名 python*；GPU/显存/PID 数据未修改。原始名称：nvidia-smi --real]')
for line,match in zip(lines,matches):
    if match:
        label=aliases[int(match[2])]
        line=match[1]+match[2]+match[3]+label.ljust(len(match[4]))+match[5]
    print(line)
