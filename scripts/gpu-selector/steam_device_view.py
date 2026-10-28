#!/usr/bin/env python3
"""Give this Steam process tree access to its selected NVIDIA GPU only.

Bubblewrap creates a private mount namespace. Host devices, drivers, networking,
Xorg and the independently selected Sunshine encoder are left unchanged.
"""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import sys


def pci_address(value):
    match=re.fullmatch(r'([0-9a-fA-F]{4,8}):([0-9a-fA-F]{2}):([0-9a-fA-F]{2})\.([0-7])',value)
    if not match:raise ValueError('Invalid render PCI address')
    domain,bus,device,function=(int(v,16) for v in match.groups())
    if domain>65535 or device>31:raise ValueError('Invalid render PCI address')
    return f'{domain:04x}:{bus:02x}:{device:02x}.{function:x}'


def device_plan(choice,dev=Path('/dev'),drm=Path('/sys/class/drm'),driver=Path('/proc/driver/nvidia/gpus')):
    pci=pci_address(choice['render_pci'])
    info=(driver/pci/'information').read_text()
    uuid=re.search(r'^GPU UUID:\s*(\S+)\s*$',info,re.M)
    minor=re.search(r'^Device Minor:\s*(\d+)\s*$',info,re.M)
    if not uuid or uuid.group(1)!=choice['render_uuid'] or not minor:
        raise RuntimeError('Render GPU UUID/PCI/minor do not match; refusing arbitrary GPU fallback')
    selected=dev/('nvidia'+minor.group(1))
    if not selected.is_char_device():raise RuntimeError('Selected NVIDIA device is unavailable')
    masked=[]
    for node in sorted(dev.glob('nvidia*'),key=lambda node:node.name):
        if re.fullmatch(r'nvidia\d+',node.name) and node!=selected:masked.append(node)
    for node in sorted(drm.glob('*'),key=lambda node:node.name):
        if not re.fullmatch(r'(?:card\d+|renderD\d+)',node.name):continue
        if (node/'device').resolve().name.lower()!=pci:
            target=dev/'dri'/node.name
            if target.exists():masked.append(target)
    return {'pci':pci,'device':str(selected),'masked':[str(p) for p in masked]}


def bubblewrap(root):
    installed=shutil.which('bwrap')
    bundled=root/'runtime/steam-client/steamrt64/pv-runtime/steam-runtime-steamrt/pressure-vessel/libexec/steam-runtime-tools-0/srt-bwrap'
    if installed:return installed
    if bundled.is_file() and os.access(bundled,os.X_OK):return str(bundled)
    raise RuntimeError('Bubblewrap is required for the private Steam GPU device view')


def command(root,choice,plan,argv):
    args=[bubblewrap(root),'--bind','/','/','--dev-bind','/dev','/dev']
    for node in plan['masked']:args+=['--ro-bind','/dev/null',node]
    # Vulkan has exactly one accessible adapter in this process view.
    args+=['--setenv','CUDA_VISIBLE_DEVICES',choice['render_uuid'],
           '--setenv','VKD3D_VULKAN_DEVICE','0','--setenv','GPUIP_DEVICE_VIEW','1']
    for key in ('__NV_PRIME_RENDER_OFFLOAD','__NV_PRIME_RENDER_OFFLOAD_PROVIDER','__VK_LAYER_NV_optimus',
                'DRI_PRIME','MESA_VK_DEVICE_SELECT','MESA_VK_DEVICE_SELECT_FORCE_DEFAULT_DEVICE'):
        args+=['--unsetenv',key]
    return args+['--']+argv


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--describe',action='store_true')
    parser.add_argument('argv',nargs=argparse.REMAINDER)
    options=parser.parse_args()
    root=options.root.resolve()
    if root.stat().st_uid!=os.getuid():raise RuntimeError('Deployment belongs to another user')
    choice=json.loads((root/'config/gpu-selection.json').read_text())
    plan=device_plan(choice)
    if options.describe:print(json.dumps(plan));return
    argv=options.argv[1:] if options.argv[:1]==['--'] else options.argv
    if not argv:parser.error('Provide the Steam command after --')
    args=command(root,choice,plan,argv)
    print('Steam GPU device view: render GPU '+str(choice['render_index'])+' at '+plan['pci'],file=sys.stderr,flush=True)
    os.execv(args[0],args)


if __name__=='__main__':
    try:main()
    except (OSError,ValueError,KeyError,RuntimeError) as error:raise SystemExit(str(error))
