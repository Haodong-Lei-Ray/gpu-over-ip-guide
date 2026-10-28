"""Windows GPU dashboard and independent render/encode selectors."""
import json
import logging
from pathlib import Path
import queue
import subprocess
import threading
import time

from open_remote_steam import HIDDEN, connect_client, direct_transport, moonlight_running, ssh_options


def request(config, action='status', render=None, stream=None):
    args = ['python3', config['remote_root']+'/scripts/gpu-selector/gpu_control.py',
            '--root', config['remote_root'], action]
    if action != 'status': args += ['--render', str(render), '--stream', str(stream)]
    # All variable arguments travel as JSON on stdin, never through a remote shell.
    code = 'import subprocess,json,sys\na=json.loads('+repr(json.dumps(args))+')\np=subprocess.run(a,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=210)\nprint(p.stdout,end="")\nprint(p.stderr,end="",file=sys.stderr)\nsys.exit(p.returncode)\n'
    base = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8', '-o', 'ConnectionAttempts=1',
            '-o', 'ServerAliveInterval=10', '-o', 'ServerAliveCountMax=2']
    base += ssh_options(config)
    if config.get('_gpu_proxy'): base += ['-o', 'ProxyCommand='+config['_gpu_proxy']]
    def execute(command):
        return subprocess.run(command+[config['ssh_alias'],'python3','-'],input=code,
                              capture_output=True,text=True,encoding='utf-8',errors='replace',
                              timeout=230 if action == 'apply' else 40,creationflags=HIDDEN)
    result = execute(base)
    if result.returncode == 255 and config.get('direct_ssh_fallback') and not config.get('_gpu_proxy'):
        config['_gpu_proxy'] = direct_transport(config)
        result = execute(base+['-o','ProxyCommand='+config['_gpu_proxy']])
    if result.returncode:
        logging.error('GPU selector %s failed: %s',action,result.stderr[-2500:])
        error = result.stderr
        if 'GAME_RUNNING' in error: raise RuntimeError('远端游戏仍在运行。请先保存并退出游戏，再切换显卡。当前游戏和串流已保留。')
        if 'WATCHER_ACTIVE' in error: raise RuntimeError('远端自动恢复守护正在运行，需要先停止该专用守护才能切卡。')
        if 'STEAM_STILL_RUNNING' in error: raise RuntimeError('Steam 未正常退出。请在远端 Steam 菜单内退出后再试。')
        details='\n'.join(error.strip().splitlines()[-14:])[-3000:]
        summary='远端选卡或启动失败。'
        if result.returncode==255:summary='SSH 连接失败或被远端断开，尚不能判断显卡权限。'
        elif 'STAGE_TIMEOUT:' in error or 'TimeoutExpired' in error:summary='远端启动阶段超时；请复制下面的具体原因。'
        elif 'previous session restored' in error:summary='所选配置启动失败，已尝试恢复原配置。'
        raise RuntimeError(summary+'\n远端详情：\n'+details+'\n完整记录：private/launcher.log；VPN 未被修改。')
    try: return json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError) as error: raise RuntimeError('服务器返回的显卡状态无法解析，请重试。') from error


def reconnect_client(config, changed):
    if changed and moonlight_running(config['moonlight_exe']):
        # Only after the remote idle session was restarted, close its now-disconnected client normally.
        executable = config['moonlight_exe'].replace("'", "''")
        code = "$p=@(Get-Process -Name Moonlight -ErrorAction SilentlyContinue | Where-Object {$_.Path -eq '"+executable+"'}); foreach($i in $p){[void]$i.CloseMainWindow()}"
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',code],
                       capture_output=True,timeout=10,creationflags=HIDDEN)
        for _ in range(30):
            if not moonlight_running(config['moonlight_exe']): break
            time.sleep(.2)
    return connect_client(config, lambda message: None)


def show_picker(config, config_path, lock=None):
    import tkinter as tk
    from tkinter import ttk, messagebox
    app = tk.Tk()
    app.title('远程 Steam · '+config.get('_server_name','GPU 选择'))
    app.geometry('1060x710')
    app.minsize(960, 660)
    app.configure(bg='#f4f6f0')
    style = ttk.Style(app)
    style.theme_use('clam')
    style.configure('Treeview',rowheight=34,font=('Microsoft YaHei UI',10))
    style.configure('Treeview.Heading',font=('Microsoft YaHei UI',10,'bold'))
    frame = ttk.Frame(app,padding=22); frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='先看负载，再选择两张显卡',font=('Microsoft YaHei UI',19,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Steam／游戏渲染与 Sunshine 串流编码可独立选择，也可以使用同一张卡。',font=('Microsoft YaHei UI',10)).pack(anchor='w',pady=(7,15))
    columns = [('index','显卡',65),('memory','显存（已用 / 总量）',165),('load','GPU',65),
               ('encoder','编码',65),('temp','温度',65),('power','功耗',80),('procs','运行进程',280),('role','当前配置',130)]
    tree = ttk.Treeview(frame,columns=[x[0] for x in columns],show='headings',height=4,selectmode='browse')
    for key,title,width in columns:
        tree.heading(key,text=title);tree.column(key,width=width,minwidth=45,stretch=key=='procs')
    tree.pack(fill='x')
    stamp = tk.StringVar(value='正在连接服务器，读取四张显卡…')
    ttk.Label(frame,textvariable=stamp).pack(anchor='w',pady=(8,12))
    selectors=ttk.Frame(frame);selectors.pack(fill='x')
    render = tk.StringVar(); stream = tk.StringVar()
    ttk.Label(selectors,text='Steam／游戏渲染 GPU',font=('Microsoft YaHei UI',11,'bold')).grid(row=0,column=0,sticky='w',padx=(0,35))
    ttk.Label(selectors,text='Sunshine 串流编码 GPU',font=('Microsoft YaHei UI',11,'bold')).grid(row=0,column=1,sticky='w')
    render_box=ttk.Combobox(selectors,textvariable=render,state='disabled',width=38)
    stream_box=ttk.Combobox(selectors,textvariable=stream,state='disabled',width=38)
    render_box.grid(row=1,column=0,sticky='w',pady=8,padx=(0,35));stream_box.grid(row=1,column=1,sticky='w',pady=8)
    note=tk.StringVar(value='读取状态后可选择。每 10 秒刷新；负载是瞬时快照，不会锁定或抢占显卡。')
    ttk.Label(frame,textvariable=note,wraplength=980,foreground='#856025').pack(anchor='w',pady=(3,10))
    ttk.Label(frame,text='进程详情（点击上方显卡行）',font=('Microsoft YaHei UI',10,'bold')).pack(anchor='w')
    detail=tk.Text(frame,height=6,wrap='word',font=('Microsoft YaHei UI',9),bg='#ffffff',relief='flat')
    detail.pack(fill='both',expand=True,pady=(5,10));detail.configure(state='disabled')
    footer=ttk.Frame(frame);footer.pack(fill='x')
    status_var=tk.StringVar(value='保留 VPN · 不自动启动游戏 · 不结束其他计算作业')
    ttk.Label(footer,textvariable=status_var,wraplength=650).pack(side='left')
    refresh=ttk.Button(footer,text='刷新状态');refresh.pack(side='right',padx=(8,0))
    launch=ttk.Button(footer,text='按所选 GPU 启动 Steam',state='disabled');launch.pack(side='right')
    events=queue.Queue();state={'busy':False,'applying':False,'snapshot':None,'next_refresh':0,'choices':{},'python_alias':{}}

    def process_alias(proc):
        return proc['alias']

    def details(_event=None):
        selected=tree.selection()
        if not selected or not state['snapshot']:return
        gpu=next(g for g in state['snapshot']['gpus'] if str(g['index'])==selected[0])
        rows=[f"GPU {gpu['index']} · {gpu['name']} · PCI {gpu['pci']}"]
        for p in gpu['processes']:
            rows.append(f"{process_alias(p)}   PID {p['pid']}   {p.get('memory') or 'N/A'}   {p.get('type') or ''}\n  原始名称：{p['name']}")
        if not gpu['processes']:rows.append('没有发现 GPU 进程。')
        detail.configure(state='normal');detail.delete('1.0','end');detail.insert('1.0','\n'.join(rows));detail.configure(state='disabled')
    tree.bind('<<TreeviewSelect>>',details)

    def enable():
        ready=state['snapshot'] is not None and not state['applying']
        launch.configure(state='normal' if ready else 'disabled')
        render_box.configure(state='readonly' if ready else 'disabled')
        stream_box.configure(state='readonly' if ready else 'disabled')
        refresh.configure(state='disabled' if state['busy'] else 'normal')

    def fetch():
        if state['busy']:return
        state['busy']=True;enable()
        def worker():
            try: events.put(('snapshot',request(config)))
            except Exception as error: events.put(('error',str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def draw(data):
        initial=state['snapshot'] is None
        state['snapshot']=data
        choice=data['selection'];choices={}
        for gpu in data['gpus']:
            i=gpu['index']
            used=gpu['used'];total=gpu['total']
            label=f"GPU {i} · 显存 {used/1024:.1f}/{total/1024:.1f} GB · GPU {gpu['utilization']:g}%" if used is not None and total and gpu['utilization'] is not None else f'GPU {i}'
            choices[i]=label
            roles=[]
            if i==choice['render_index']:roles.append('渲染')
            if i==choice['stream_index']:roles.append('编码')
            def metric(v,suffix):return 'N/A' if v is None else f'{v:g}{suffix}'
            values=(f'GPU {i}',f'{used/1024:.1f} / {total/1024:.1f} GB' if used is not None and total else 'N/A',
                    metric(gpu['utilization'],'%'),metric(gpu['encoder'],'%'),metric(gpu['temperature'],'°C'),metric(gpu['power'],' W'),
                    ', '.join(process_alias(p) for p in gpu['processes']) or '空闲', ' + '.join(roles) or '—')
            if tree.exists(str(i)):tree.item(str(i),values=values)
            else:tree.insert('', 'end',iid=str(i),values=values)
        # Keep the user's selections while refreshing the dynamic load labels.
        def old_index(var, fallback):
            try:return int(var.get().split(' · ',1)[0].split()[-1])
            except (ValueError,IndexError):return fallback
        ri=choice['render_index'] if initial else old_index(render,choice['render_index'])
        si=choice['stream_index'] if initial else old_index(stream,choice['stream_index'])
        state['choices']=choices
        render_box.configure(values=list(choices.values()));stream_box.configure(values=list(choices.values()))
        render.set(choices.get(ri,''));stream.set(choices.get(si,''))
        stamp.set('已更新 '+time.strftime('%H:%M:%S')+'  ·  四卡实时快照；进程别名按 PID 区分')
        active=bool(data['game_pids'])
        note.set('远端游戏正在运行：保留相同配置可以连接；切换任一显卡前，请先保存并退出游戏。' if active else
                 '可以选择两张不同的卡；切卡会重启这套专用 Steam／桌面／串流。其他 GPU 作业保留。')
        if not tree.selection() and data['gpus']:tree.selection_set(str(choice['render_index']))
        details()

    def start():
        if state['busy'] or not state['snapshot']:return
        ri=int(render.get().split(' · ',1)[0].split()[-1]);si=int(stream.get().split(' · ',1)[0].split()[-1])
        old=state['snapshot']['selection'];changed=ri!=old['render_index'] or si!=old['stream_index']
        if changed and state['snapshot']['game_pids']:
            messagebox.showinfo('请先退出远端游戏','游戏仍在运行，不能在运行中迁移显卡。\n请先在游戏内保存并退出，然后点击刷新，再按所选显卡启动。',parent=app);return
        state['busy']=True;state['applying']=True;enable()
        status_var.set(f'正在应用：Steam／游戏 GPU {ri}，串流编码 GPU {si}。请等待…')
        def worker():
            try:
                result=request(config,'apply',ri,si)
                message=reconnect_client(config,result['changed'])
                events.put(('done',f'已应用：渲染 GPU {ri} · 编码 GPU {si}。'+message))
            except Exception as error:
                logging.exception('GPU selection failed');events.put(('error',str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def poll():
        try:
            while True:
                kind,value=events.get_nowait()
                state['busy']=False;state['applying']=False;state['next_refresh']=time.monotonic()+10
                if kind=='snapshot':draw(value)
                elif kind=='done':
                    status_var.set(value);state['snapshot']=None;fetch()
                else:status_var.set(value);stamp.set('刷新失败；已有数据可能已过期，请点击刷新。')
                enable()
        except queue.Empty: pass
        if not state['busy'] and time.monotonic()>=state['next_refresh']:fetch()
        app.after(150,poll)
    def close():
        if state['applying']:
            status_var.set('正在切换会话，请等待操作结束后再关闭窗口。');return
        app.destroy()
    refresh.configure(command=fetch);launch.configure(command=start)
    app.protocol('WM_DELETE_WINDOW',close)
    fetch();app.after(150,poll);app.mainloop()
