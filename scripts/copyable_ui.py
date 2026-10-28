"""Selectable status text and copy menus for every management-window control."""
import tkinter as tk
from tkinter import ttk


def table_text(tree,items=None,headers=True):
    columns=tree['columns']
    rows=[]
    if headers:rows.append([tree.heading(column,'text') for column in columns])
    for item in tree.get_children() if items is None else items:
        rows.append([str(v) for v in tree.item(item,'values')])
    return '\n'.join('\t'.join(row) for row in rows)


def widget_text(widget):
    kind=widget.winfo_class()
    if kind=='Text':return widget.get('1.0','end-1c')
    if kind=='Treeview':return table_text(widget)
    if kind in ('Entry','TEntry','TCombobox'):return widget.get()
    try:return str(widget.cget('text'))
    except (tk.TclError,KeyError):return ''


def window_text(app):
    parts=[app.title()]
    def walk(widget):
        text=widget_text(widget)
        if text:parts.append(text)
        # Combobox drop-down implementation is not application content.
        if widget.winfo_class()!='TCombobox':
            for child in widget.winfo_children():walk(child)
    for child in app.winfo_children():walk(child)
    return '\n\n'.join(parts)


def put_clipboard(app,text):
    app.clipboard_clear();app.clipboard_append(text)


def readonly_text(parent,text=None,textvariable=None,font=None,max_lines=4):
    variable=textvariable or tk.StringVar(master=parent,value=text or '')
    background=ttk.Style(parent).lookup('TFrame','background') or '#f4f6f0'
    widget=tk.Text(parent,height=1,wrap='word',font=font or ('Microsoft YaHei UI',10),
                   relief='flat',borderwidth=0,highlightthickness=0,background=background,
                   exportselection=False,takefocus=True,cursor='xterm')
    def resize(_event=None):
        try:
            lines=widget.count('1.0','end-1c','displaylines')
            wanted=max(1,min(max_lines,(lines[0] if lines else 0)+1))
            if int(widget['height'])!=wanted:widget.configure(height=wanted)
        except tk.TclError:pass
    def update(*_args):
        value=variable.get()
        if widget.get('1.0','end-1c')!=value:
            widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',value);widget.configure(state='disabled')
        widget.after_idle(resize)
    def select_all(_event=None):
        widget.tag_add('sel','1.0','end-1c');widget.mark_set('insert','1.0');return 'break'
    widget.bind('<Control-a>',select_all)
    widget.bind('<Configure>',resize)
    variable.trace_add('write',update)
    # Keep the Tcl variable alive when created by this helper.
    widget._copy_variable=variable
    update();return widget


def enable_copy(app):
    def copy_all():put_clipboard(app,window_text(app))
    def table_copy(event):
        tree=event.widget;items=tree.selection()
        put_clipboard(app,table_text(tree,items if items else None,headers=True));return 'break'
    def select_text(event):
        widget=event.widget
        if widget.winfo_class()=='Text':
            widget.tag_add('sel','1.0','end-1c');return 'break'
    def text_copy(event):
        widget=event.widget
        try:value=widget.get('sel.first','sel.last')
        except tk.TclError:return 'break'
        put_clipboard(app,value);return 'break'
    def popup(event):
        widget=event.widget;kind=widget.winfo_class();menu=tk.Menu(app,tearoff=False)
        if kind=='Treeview':
            item=widget.identify_row(event.y);column=widget.identify_column(event.x)
            if column.startswith('#') and column!='#0':
                index=int(column[1:])-1
                if item:
                    values=widget.item(item,'values')
                    value=str(values[index]) if index<len(values) else ''
                else:
                    columns=widget['columns'];value=widget.heading(columns[index],'text') if index<len(columns) else ''
                menu.add_command(label='复制此单元格',command=lambda:put_clipboard(app,value))
            if item:menu.add_command(label='复制此行',command=lambda:put_clipboard(app,table_text(widget,[item])))
            menu.add_command(label='复制整张表格',command=lambda:put_clipboard(app,table_text(widget)))
        else:
            value=widget_text(widget)
            if kind=='Text':
                try:selection=widget.get('sel.first','sel.last')
                except tk.TclError:selection=''
                if selection:menu.add_command(label='复制选中文字',command=lambda:put_clipboard(app,selection))
            if value:menu.add_command(label='复制此区域全部文字',command=lambda:put_clipboard(app,value))
        menu.add_separator();menu.add_command(label='复制全部窗口信息',command=copy_all)
        try:menu.tk_popup(event.x_root,event.y_root)
        finally:menu.grab_release()
        return 'break'
    def bind(widget):
        kind=widget.winfo_class()
        widget.bind('<Button-3>',popup)
        if kind=='Treeview':widget.bind('<Control-c>',table_copy)
        elif kind=='Text':
            widget.bind('<Control-a>',select_text);widget.bind('<Control-c>',text_copy)
        for child in widget.winfo_children():bind(child)
    bind(app)
    app.bind('<Control-Shift-C>',lambda event:(copy_all(),'break')[1])
    return copy_all
