"""Inspect our own Tk widgets; no remote sessions or system input are touched."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import steam_manager
import copyable_ui
import tkinter as tk
from tkinter import ttk


class CopyableTests(unittest.TestCase):
    def setUp(self):
        try:self.app=tk.Tk()
        except tk.TclError as error:self.skipTest(str(error))
        self.app.withdraw();self.addCleanup(self.app.destroy)

    def test_all_regions_are_exported_and_selectable(self):
        status=tk.StringVar(value='状态：运行中\n第二行')
        text=copyable_ui.readonly_text(self.app,textvariable=status)
        label=ttk.Label(self.app,text='GPU 监控')
        button=ttk.Button(self.app,text='复制全部信息')
        tree=ttk.Treeview(self.app,columns=['gpu','process'],show='headings')
        tree.heading('gpu',text='显卡');tree.heading('process',text='进程')
        tree.insert('','end',iid='1',values=['GPU 1','python2']);tree.selection_set('1')
        for widget in (label,text,tree,button):widget.pack()
        copyable_ui.enable_copy(self.app)
        self.app.update_idletasks()
        self.assertEqual(str(text['state']),'disabled')
        self.assertTrue(text.bind('<Control-c>'))
        self.assertTrue(tree.bind('<Control-c>'))
        for widget in (label,text,tree,button):self.assertTrue(widget.bind('<Button-3>'))
        self.assertEqual(copyable_ui.table_text(tree,tree.selection()),'显卡\t进程\nGPU 1\tpython2')
        export=copyable_ui.window_text(self.app)
        for value in ('GPU 监控','状态：运行中','第二行','GPU 1\tpython2','复制全部信息'):self.assertIn(value,export)
        status.set('启动超时\n完整错误');self.app.update_idletasks()
        self.assertIn('完整错误',copyable_ui.window_text(self.app))


class ManagerUiTests(unittest.TestCase):
    def test_gpu_one_defaults_copy_and_layout(self):
        original=tk.Tk
        try:probe=original();probe.update_idletasks();probe.destroy()
        except tk.TclError as error:self.skipTest(str(error))
        config={'ssh_alias':'lab-a','moonlight_host':'gpu-a.example',
                'default_render_gpu':1,'default_stream_gpu':1}
        profiles=[{'id':'lab-a','name':'实验服务器','config':config}]
        ready={'steam_ready':True,'sunshine_ready':True,'display_ready':True}
        gpus=[dict(index=i,name='Test GPU',pci='01:00.0',used=5,total=24000,
                   utilization=0,encoder=0,temperature=30,power=20,processes=[])
              for i in range(4)]
        snapshot={'ready':ready,'gpu_error':None,'gpu':{
            'gpus':gpus,'selection':{'render_index':3,'stream_index':3},'game_pids':[]}}
        failures=[];exports=[]
        def build():
            app=original()
            def verify():
                try:
                    widgets=[]
                    def walk(widget):
                        widgets.append(widget)
                        for child in widget.winfo_children():walk(child)
                    walk(app);app.update_idletasks()
                    tree=next(w for w in widgets if w.winfo_class()=='Treeview')
                    combos=[w for w in widgets if w.winfo_class()=='TCombobox']
                    self.assertEqual(tree.selection(),('1',))
                    self.assertTrue(all(w.get().startswith('GPU 1 · ') for w in combos[1:]))
                    buttons={str(w['text']):w for w in widgets if w.winfo_class()=='TButton'}
                    buttons['复制全部信息'].invoke()
                    self.assertIn('Steam：运行中',exports[-1])
                    self.assertIn('GPU 3',exports[-1])
                    for button in buttons.values():
                        self.assertGreater(button.winfo_height(),1)
                        self.assertLessEqual(button.winfo_rooty()+button.winfo_height(),app.winfo_rooty()+app.winfo_height())
                    # A refresh must not replace a deliberate selection with the default.
                    combos[1].current(2);buttons['刷新状态'].invoke()
                    app.after(400,verify_refresh)
                except Exception as error:failures.append(error);app.destroy()
            def verify_refresh():
                try:
                    widgets=[]
                    def walk(widget):
                        if widget.winfo_class()=='TCombobox':widgets.append(widget)
                        for child in widget.winfo_children():walk(child)
                    walk(app);self.assertTrue(widgets[1].get().startswith('GPU 2 · '))
                except Exception as error:failures.append(error)
                finally:app.destroy()
            app.after(700,verify);return app
        with patch.object(tk,'Tk',build),patch.object(steam_manager,'inspect_server',return_value=snapshot),patch.object(copyable_ui,'put_clipboard',side_effect=lambda app,value:exports.append(value)):
            steam_manager.show_manager(profiles,'lab-a',Path('servers.json'))
        if failures:raise failures[0]
        self.assertTrue(exports)
