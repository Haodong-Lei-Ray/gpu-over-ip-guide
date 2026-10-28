"""Private multi-server configuration and Windows server selection."""
import json
from pathlib import Path
import re


def load_servers(path):
    from open_remote_steam import validate_config
    path=Path(path).resolve()
    data=json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data,dict) or not isinstance(data.get('servers'),list):
        raise ValueError('servers.json must contain a servers array')
    profiles=[];seen=set()
    for item in data['servers']:
        if not isinstance(item,dict):raise ValueError('Invalid server entry')
        ident=item.get('id','')
        if not isinstance(ident,str) or not re.fullmatch(r'[A-Za-z0-9_.-]+',ident) or ident in seen:
            raise ValueError('Server ids must be unique simple names')
        seen.add(ident)
        if not item.get('enabled',True):continue
        name=item.get('name',ident)
        if not isinstance(name,str) or not name.strip() or any(c in name for c in '\r\n\0'):
            raise ValueError('Invalid server name')
        if 'config_file' in item:
            file=Path(item['config_file'])
            if not file.is_absolute():file=path.parent/file
            connection=json.loads(file.read_text(encoding='utf-8-sig'))
        else:
            connection=item.get('connection')
            if not isinstance(connection,dict):raise ValueError('Server needs connection or config_file')
        config=validate_config(dict(connection))
        config['_server_id']=ident;config['_server_name']=name
        config['_client_state_dir']=str(path.parent)
        profiles.append({'id':ident,'name':name,'config':config})
    if not profiles:raise ValueError('Enable at least one server in servers.json')
    default=data.get('default_server')
    if default not in {p['id'] for p in profiles}:default=profiles[0]['id']
    return profiles,default


def choose_server(profiles,default):
    import tkinter as tk
    from tkinter import ttk
    app=tk.Tk();app.title('远程 Steam · 选择服务器');app.geometry('720x370');app.minsize(680,340)
    frame=ttk.Frame(app,padding=24);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='这次连接哪台服务器？',font=('Microsoft YaHei UI',18,'bold')).pack(anchor='w',pady=(0,8))
    ttk.Label(frame,text='服务器信息保存在本机 private/servers.json；密码与私钥不写入此文件。').pack(anchor='w',pady=(0,15))
    tree=ttk.Treeview(frame,columns=['name','ssh','host'],show='headings',height=5,selectmode='browse')
    for key,title,width in [('name','服务器',230),('ssh','SSH',190),('host','Moonlight 主机',230)]:
        tree.heading(key,text=title);tree.column(key,width=width)
    tree.pack(fill='both',expand=True)
    for profile in profiles:
        c=profile['config']
        address=c.get('ssh_hostname',c['ssh_alias'])
        if c.get('ssh_user'):address=c['ssh_user']+'@'+address
        tree.insert('','end',iid=profile['id'],values=(profile['name'],address,c['moonlight_host']))
    tree.selection_set(default);tree.focus(default)
    chosen=[]
    def accept(_event=None):
        selected=tree.selection()
        if selected:chosen.append(next(p for p in profiles if p['id']==selected[0]));app.destroy()
    ttk.Button(frame,text='连接所选服务器',command=accept).pack(anchor='e',pady=(15,0))
    tree.bind('<Double-1>',accept);app.bind('<Return>',accept)
    app.mainloop()
    return chosen[0] if chosen else None


def resolve_server(path,server_id=None,interactive=True):
    profiles,default=load_servers(path)
    if server_id:
        matches=[p for p in profiles if p['id']==server_id]
        if not matches:raise ValueError('Unknown or disabled server: '+server_id)
        return matches[0]
    if not interactive:
        return next(p for p in profiles if p['id']==default)
    # Display even a single configured host, so the configuration entry is discoverable.
    return choose_server(profiles,default)
