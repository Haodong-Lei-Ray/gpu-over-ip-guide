"""One Windows management window for all configured remote Steam servers."""
import logging
from pathlib import Path
import queue
import threading
import time

from open_remote_steam import connect_client, prepare_remote
from gpu_picker import request, reconnect_client


def inspect_server(config):
    if config.get('backend','sunshine')!='sunshine':
        return {'ready':{'steam_ready':None,'sunshine_ready':None,'display_ready':None},'gpu':None,
                'unsupported':True,'gpu_error':'此服务器使用 '+config['backend']+'，SSH 信息已载入。启动、选卡和关闭需要对应管理适配器，不会套用 Sunshine 脚本。'}
    ready=prepare_remote(config,lambda _:None,check_only=True)
    try:
        gpu=request(config)
        return {'ready':ready,'gpu':gpu,'gpu_error':None}
    except Exception as error:
        return {'ready':ready,'gpu':None,'gpu_error':str(error)}


def connect_server(config,render=None,stream=None,apply_gpus=False):
    if config.get('backend','sunshine')!='sunshine':raise RuntimeError('此服务器的串流后端尚未接入管理器，不能执行 Sunshine 启动脚本。')
    current=prepare_remote(config,lambda _:None,check_only=True)
    if current['steam_ready'] and not apply_gpus:
        if not current['sunshine_ready'] or not current.get('display_ready',True):
            prepare_remote(config,lambda _:None,check_only=False)
        return connect_client(config,lambda _:None)
    if render is None or stream is None:
        raise RuntimeError('请先部署选卡后端并选择渲染与编码 GPU。')
    outcome=request(config,'apply',render,stream)
    return reconnect_client(config,outcome['changed'])


def close_server(config):
    if config.get('backend','sunshine')!='sunshine':raise RuntimeError('此服务器的串流后端尚未接入管理器，不能执行 Sunshine 关闭脚本。')
    from close_remote_steam import remote
    current=remote(config,check_only=True)
    if not any(current[k] for k in ('steam_running','sunshine_running','display_running')):
        return '所选服务器的 Steam 和串流已经关闭，无需重复操作。'
    if current['game_running']:
        raise RuntimeError('所选服务器的游戏仍在运行。请先保存并正常退出游戏，再关闭会话。')
    result=remote(config)
    if not result.get('stopped'):raise RuntimeError('关闭尚未完成，请刷新检查。')
    return '所选服务器的 Steam、专用桌面、串流和音频已关闭。'


def show_manager(profiles,default,config_path,startup_action='connect'):
    import tkinter as tk
    from tkinter import ttk,messagebox
    from copyable_ui import readonly_text,enable_copy,put_clipboard,window_text
    app=tk.Tk();app.title('远程 Steam 管理器');app.geometry('1100x760');app.minsize(1000,700)
    style=ttk.Style(app);style.theme_use('clam');style.configure('Treeview',rowheight=34,font=('Microsoft YaHei UI',10))
    frame=ttk.Frame(app,padding=22);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='远程 Steam 管理器',font=('Microsoft YaHei UI',20,'bold')).pack(anchor='w')
    ttk.Label(frame,text='选择服务器 · 查看 GPU · 连接 / 启动 · 切换显卡 · 关闭会话',font=('Microsoft YaHei UI',10)).pack(anchor='w',pady=(5,15))
    bar=ttk.Frame(frame);bar.pack(fill='x')
    ttk.Label(bar,text='服务器').pack(side='left',padx=(0,10))
    selected=tk.StringVar();server_box=ttk.Combobox(bar,textvariable=selected,state='readonly',width=43);server_box.pack(side='left')
    reload_button=ttk.Button(bar,text='重新加载配置');reload_button.pack(side='left',padx=10)
    refresh_button=ttk.Button(bar,text='刷新状态');refresh_button.pack(side='right')
    connection=tk.StringVar();readonly_text(frame,textvariable=connection,max_lines=2).pack(fill='x',pady=(10,5))
    health=tk.StringVar(value='正在读取所选服务器状态…');readonly_text(frame,textvariable=health,font=('Microsoft YaHei UI',11,'bold'),max_lines=2).pack(fill='x',pady=(0,12))
    columns=[('id','GPU',60),('memory','显存 已用 / 总量',155),('util','GPU',60),('enc','编码',60),('temp','温度',60),('power','功耗',75),('process','运行进程',330),('role','当前配置',130)]
    tree=ttk.Treeview(frame,columns=[v[0] for v in columns],show='headings',height=4,selectmode='browse')
    for key,title,width in columns:tree.heading(key,text=title);tree.column(key,width=width,minwidth=40,stretch=key=='process')
    tree.pack(fill='x')
    row=ttk.Frame(frame);row.pack(fill='x',pady=(15,5))
    ttk.Label(row,text='待应用：Steam／游戏渲染 GPU').grid(row=0,column=0,sticky='w')
    ttk.Label(row,text='待应用：Sunshine 编码 GPU').grid(row=0,column=1,sticky='w')
    render=tk.StringVar();stream=tk.StringVar()
    render_box=ttk.Combobox(row,textvariable=render,state='disabled',width=37);render_box.grid(row=1,column=0,padx=(0,35),pady=6)
    stream_box=ttk.Combobox(row,textvariable=stream,state='disabled',width=37);stream_box.grid(row=1,column=1,pady=6)
    note=tk.StringVar(value='显卡状态每 10 秒刷新；变更显卡前请先保存退出游戏。')
    readonly_text(frame,textvariable=note,max_lines=2).pack(fill='x',pady=(0,10))
    ttk.Label(frame,text='进程详情（名称用 python* 别名显示，原始名称在这里核对）').pack(anchor='w')
    details=tk.Text(frame,height=5,font=('Microsoft YaHei UI',9),wrap='word',relief='flat');details.pack(fill='both',expand=True,pady=(5,12));details.configure(state='disabled')
    actions=ttk.Frame(frame);actions.pack(fill='x')
    connect_button=ttk.Button(actions,text='连接 / 启动 Steam');connect_button.pack(side='left')
    apply_button=ttk.Button(actions,text='应用所选 GPU 并连接');apply_button.pack(side='left',padx=10)
    close_button=ttk.Button(actions,text='关闭所选服务器的会话');close_button.pack(side='right')
    message=tk.StringVar(value='选择服务器后操作。关闭前会重新检测状态，不关闭服务器或其他计算作业。')
    readonly_text(frame,textvariable=message,max_lines=3).pack(fill='x',pady=(12,4))
    readonly_text(frame,text='私有配置：'+str(config_path),max_lines=1).pack(fill='x')
    ttk.Label(frame,text='文字可选中后 Ctrl+C；表格 Ctrl+C 复制行；任意区域右键可复制全部。',font=('Microsoft YaHei UI',9)).pack(anchor='w',pady=(4,0))
    def copy_all():put_clipboard(app,window_text(app))
    ttk.Button(bar,text='复制全部信息',command=copy_all).pack(side='right',padx=(0,8))
    def copy_error():
        from copyable_ui import put_clipboard
        put_clipboard(app,message.get())
    ttk.Button(actions,text='复制状态 / 错误',command=copy_error).pack(side='left',padx=(0,8))
    events=queue.Queue();state={'profiles':profiles,'busy':False,'operation':False,'snapshot':None,'next':0,'generation':0}

    def current():return next(p for p in state['profiles'] if ('['+p['id']+'] '+p['name'])==selected.get())
    def populate(items,ident):
        state['profiles']=items;server_box.configure(values=['['+p['id']+'] '+p['name'] for p in items])
        target=next((p for p in items if p['id']==ident),items[0]);selected.set('['+target['id']+'] '+target['name'])
    populate(profiles,default)
    def controls():
        idle=not state['busy'];snapshot=state['snapshot'];gpu=snapshot and snapshot['gpu']
        server_box.configure(state='disabled' if state['operation'] else 'readonly')
        for button in [reload_button,refresh_button]:button.configure(state='normal' if idle else 'disabled')
        supported=snapshot and not snapshot.get('unsupported')
        connect_button.configure(state='normal' if idle and supported else 'disabled')
        close_button.configure(state='normal' if idle and supported else 'disabled')
        apply_button.configure(state='normal' if idle and gpu else 'disabled')
        for box in [render_box,stream_box]:box.configure(state='readonly' if idle and gpu else 'disabled')
    def details_changed(_event=None):
        snapshot=state['snapshot'];choice=tree.selection()
        lines=[]
        if snapshot and snapshot['gpu'] and choice:
            gpu=next(g for g in snapshot['gpu']['gpus'] if str(g['index'])==choice[0])
            lines=[f"GPU {gpu['index']} · {gpu['name']} · PCI {gpu['pci']}"]
            for p in gpu['processes']:lines.append(f"{p['alias']} · PID {p['pid']} · {p.get('memory') or 'N/A'}\n  原始名称：{p['name']}")
            if not gpu['processes']:lines.append('没有发现 GPU 进程。')
        details.configure(state='normal');details.delete('1.0','end');details.insert('1.0','\n'.join(lines));details.configure(state='disabled')
    tree.bind('<<TreeviewSelect>>',details_changed)
    def fetch():
        if state['busy']:return
        profile=current();c=profile['config'];generation=state['generation'];state['busy']=True;controls()
        app.title('远程 Steam 管理器 · '+profile['name'])
        connection.set('当前监控服务器：['+profile['id']+'] '+profile['name']+' · SSH '+c.get('ssh_hostname',c['ssh_alias'])+':'+str(c.get('ssh_port',22))+' · Moonlight '+c['moonlight_host'])
        def worker():
            try:events.put(('snapshot',generation,inspect_server(c)))
            except Exception as error:events.put(('error',generation,str(error)))
        threading.Thread(target=worker,daemon=True).start()
    def draw(value):
        state['snapshot']=value;r=value['ready'];gpu=value['gpu']
        health.set('Steam：'+('运行中' if r['steam_ready'] else '未启动')+'   Sunshine：'+('就绪' if r['sunshine_ready'] else '未就绪')+'   桌面：'+('就绪' if r.get('display_ready') else '未就绪')+'   更新 '+time.strftime('%H:%M:%S'))
        if not gpu:
            for item in tree.get_children():tree.delete(item)
            render.set('');stream.set('')
            if value.get('unsupported'):
                health.set('服务器配置已载入 · 串流后端待接入管理器');note.set(value['gpu_error']);return
            note.set('选卡后端不可用。已运行的 Steam 仍可连接；启动选卡需要 server agent 先完成部署。')
            message.set(value['gpu_error'] or '显卡状态不可用，请刷新重试。')
            logging.warning('GPU status unavailable: %s',value['gpu_error']);return
        old_render=render.get().split(' · ',1)[0];old_stream=stream.get().split(' · ',1)[0]
        selection=gpu['selection'];labels={}
        for g in gpu['gpus']:
            i=g['index'];used=g['used'];total=g['total'];roles=[]
            if i==selection['render_index']:roles.append('渲染')
            if i==selection['stream_index']:roles.append('编码')
            def metric(v,suffix):return 'N/A' if v is None else f'{v:g}{suffix}'
            memory=f'{used/1024:.1f} / {total/1024:.1f} GB' if used is not None and total else 'N/A'
            labels[f'GPU {i}']=f'GPU {i} · {memory} · '+metric(g['utilization'],'%')
            values=(f'GPU {i}',memory,metric(g['utilization'],'%'),metric(g['encoder'],'%'),metric(g['temperature'],'°C'),metric(g['power'],' W'),', '.join(p['alias'] for p in g['processes']) or '空闲',' + '.join(roles) or '—')
            if tree.exists(str(i)):tree.item(str(i),values=values)
            else:tree.insert('','end',iid=str(i),values=values)
        for box,var,old,role,key in [(render_box,render,old_render,'render_index','default_render_gpu'),(stream_box,stream,old_stream,'stream_index','default_stream_gpu')]:
            preferred=current()['config'].get(key,selection[role])
            fallback=labels.get('GPU '+str(preferred),labels.get('GPU '+str(selection[role]),''))
            box.configure(values=list(labels.values()));var.set(labels.get(old,fallback))
        note.set('检测到游戏运行：可连接，切卡或关闭前请先保存退出游戏。' if gpu['game_pids'] else '已有 Steam 点击连接即可复用。只有“应用所选 GPU”会主动切卡；关闭前会再次检测状态。')
        if not tree.selection() and gpu['gpus']:
            preferred=str(current()['config'].get('default_render_gpu',selection['render_index']))
            target=preferred if tree.exists(preferred) else str(gpu['gpus'][0]['index'])
            tree.selection_set(target);tree.focus(target);tree.see(target)
        details_changed()
    def switch(_event=None):
        # Read-only probes may finish after a server change; their generation is discarded.
        # Keep server selection responsive even when the previous host is unreachable.
        state['generation']+=1;state['snapshot']=None;state['busy']=False
        for item in tree.get_children():tree.delete(item)
        render.set('');stream.set('');details_changed();health.set('正在检查所选服务器…');message.set('目标已切换，操作仅作用于当前所选服务器。');fetch()
    def operate(action):
        if state['busy'] or not state['snapshot']:return
        profile=current();c=profile['config'];snapshot=state['snapshot'];generation=state['generation']
        if action=='close':
            if not messagebox.askokcancel('关闭所选服务器的会话','目标：'+profile['name']+'\n\n将先检测是否运行，再正常关闭专用 Steam 和串流。\n游戏仍在运行时会拒绝关闭；服务器和其他计算作业保留。',parent=app):return
        def index(var):
            try:return int(var.get().split(' · ',1)[0].split()[-1])
            except (ValueError,IndexError):return None
        ri,si=index(render),index(stream)
        state['busy']=True;state['operation']=True;controls();message.set('正在处理 '+profile['name']+'，请等待…')
        def worker():
            try:
                result=close_server(c) if action=='close' else connect_server(c,ri,si,apply_gpus=action=='apply')
                events.put(('done',generation,result))
            except Exception as error:
                logging.exception('Manager action %s failed for %s',action,profile['id']);events.put(('error',generation,str(error)))
        threading.Thread(target=worker,daemon=True).start()
    def reload_profiles():
        if state['busy']:return
        try:
            import json
            from server_profiles import load_servers
            if 'servers' in json.loads(Path(config_path).read_text(encoding='utf-8-sig')):
                items,default_id=load_servers(config_path)
            else:
                from open_remote_steam import load_config
                c=load_config(Path(config_path));c['_server_id']='single';c['_server_name']=c['ssh_alias']
                items=[{'id':'single','name':c['ssh_alias'],'config':c}];default_id='single'
            ident=current()['id'];populate(items,ident or default_id);switch()
        except Exception as error:messagebox.showerror('服务器配置无效',str(error),parent=app)
    def poll():
        try:
            while True:
                kind,generation,value=events.get_nowait()
                if generation!=state['generation']:continue
                state['busy']=False;state['operation']=False;state['next']=time.monotonic()+10
                if kind=='snapshot':draw(value)
                elif kind=='done':message.set(value);fetch()
                else:
                    message.set(value)
                    state['snapshot']=None
                    for item in tree.get_children():tree.delete(item)
                    details_changed()
                    health.set('刷新失败 · 当前运行状态未知，旧监控数据已清除；请重试。')
                controls()
        except queue.Empty:pass
        if not state['busy'] and time.monotonic()>=state['next']:fetch()
        app.after(150,poll)
    def close_window():
        if state['operation']:message.set('远端操作尚未完成，请等待结果后再关闭管理器。');return
        app.destroy()
    server_box.bind('<<ComboboxSelected>>',switch)
    refresh_button.configure(command=fetch);reload_button.configure(command=reload_profiles)
    connect_button.configure(command=lambda:operate('connect'));apply_button.configure(command=lambda:operate('apply'));close_button.configure(command=lambda:operate('close'))
    if startup_action=='stop':message.set('此入口用于关闭：先选择服务器，核对状态，再点击右侧关闭按钮。')
    enable_copy(app)
    app.protocol('WM_DELETE_WINDOW',close_window);fetch();app.after(150,poll);app.mainloop()
