"""Reuse an existing remote Steam session before asking the user to choose GPUs."""
import logging
import queue
import threading

from open_remote_steam import connect_client, prepare_remote


def route_start(config, status):
    current = prepare_remote(config, status, check_only=True)
    if not current['steam_ready']:
        return {'choose_gpu': True, 'status': current}
    # Repair missing streaming components with the existing server selection.
    # This calls only the idempotent session entry; it never invokes GPU apply/stop.
    if not current['sunshine_ready'] or not current.get('display_ready', True):
        status('远端 Steam 已启动，正在按现有显卡配置补齐串流服务…')
        current = prepare_remote(config, status, check_only=False)
    status('远端 Steam 已就绪，直接连接现有会话…')
    return {'choose_gpu': False, 'status': current, 'message': connect_client(config, status)}


def show_quick_start(config):
    import tkinter as tk
    from tkinter import ttk
    app = tk.Tk()
    app.title('启动远程 Steam · '+config.get('_server_name',config['ssh_alias']))
    app.geometry('540x210')
    app.resizable(False,False)
    app.configure(bg='#f4f6f0')
    tk.Label(app,text='连接远程 Steam',bg='#f4f6f0',fg='#1b6047',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w',padx=25,pady=(22,12))
    label=tk.Label(app,text='正在检查远端是否已有 Steam 会话…',bg='#f4f6f0',fg='#243c30',wraplength=485,justify='left',font=('Microsoft YaHei UI',10))
    label.pack(anchor='w',padx=25)
    progress=ttk.Progressbar(app,mode='indeterminate',length=485)
    progress.pack(padx=25,pady=18);progress.start(15)
    tk.Label(app,text='已启动就直接连接 · 未启动再选卡 · 保留 VPN',bg='#f4f6f0',fg='#69776d',font=('Microsoft YaHei UI',9)).pack(anchor='w',padx=25)
    events=queue.Queue();outcome={'choose_gpu':False}
    def worker():
        try:
            result=route_start(config,lambda message:events.put(('status',message)))
            events.put(('done',result))
        except Exception as error:
            logging.exception('Quick remote Steam connection failed')
            events.put(('error',str(error)))
    def poll():
        try:
            while True:
                kind,value=events.get_nowait()
                if kind=='status':label.config(text=value)
                elif kind=='done':
                    outcome.update(value);progress.stop()
                    if value['choose_gpu']:app.destroy()
                    else:
                        label.config(text=value['message'])
                        app.after(1500,app.destroy)
                    return
                else:
                    progress.stop();label.config(text=value,fg='#9a3829');return
        except queue.Empty:app.after(120,poll)
    threading.Thread(target=worker,daemon=True).start();app.after(100,poll);app.mainloop()
    return outcome['choose_gpu']
