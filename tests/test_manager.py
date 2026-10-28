"""Offline behavior checks: no network, GPU workload, or user session is modified."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import open_remote_steam as launcher
import server_profiles
import steam_manager
import close_remote_steam
import gpu_picker


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        exe=self.root/'Moonlight.exe';exe.touch();(self.root/'portable.dat').touch()
        self.config={'ssh_alias':'lab-a','ssh_hostname':'gpu-a.example','ssh_user':'user','ssh_port':22,
                     'remote_root':'/home/user/gpu-over-ip/streaming','moonlight_host':'gpu-a.example',
                     'moonlight_app':'Steam','moonlight_exe':str(exe),'moonlight_workdir':str(self.root),
                     '_client_state_dir':str(self.root)}
        self.ready={'steam_ready':True,'sunshine_ready':True,'display_ready':True}

    def profiles(self):
        b=dict(self.config,ssh_alias='lab-b',ssh_hostname='gpu-b.example',ssh_port=2222,moonlight_host='gpu-b.example')
        value={'default_server':'lab-b','servers':[{'id':'lab-a','name':'A','connection':self.config},
                 {'id':'lab-b','name':'B','connection':b}, {'id':'disabled','enabled':False}]}
        path=self.root/'servers.json';path.write_text(json.dumps(value),encoding='utf-8');return path

    def test_servers_preserve_independent_connection_and_port(self):
        path=self.profiles();items,default=server_profiles.load_servers(path)
        self.assertEqual(default,'lab-b');self.assertEqual(len(items),2)
        chosen=server_profiles.resolve_server(path,'lab-b',interactive=False)['config']
        self.assertEqual(chosen['moonlight_host'],'gpu-b.example')
        self.assertEqual(launcher.ssh_options(chosen),['-o','HostName=gpu-b.example','-o','User=user','-p','2222'])
        self.assertEqual(items[0]['config']['ssh_port'],22)

    def test_duplicate_server_id_is_rejected(self):
        path=self.profiles();value=json.loads(path.read_text());value['servers'][1]['id']='lab-a';path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):server_profiles.load_servers(path)

    def test_bad_port_and_shell_characters_rejected(self):
        for changes in [{'ssh_port':True},{'ssh_port':70000},{'ssh_hostname':'gpu.example;command'}]:
            with self.assertRaises(ValueError):launcher.validate_config(dict(self.config,**changes))

    def test_existing_steam_connects_without_gpu_apply(self):
        with patch.object(steam_manager,'prepare_remote',return_value=self.ready) as prepare,patch.object(steam_manager,'request') as apply,patch.object(steam_manager,'connect_client',return_value='connected'):
            self.assertEqual(steam_manager.connect_server(self.config,0,1),'connected')
            prepare.assert_called_once();self.assertTrue(prepare.call_args.kwargs['check_only']);apply.assert_not_called()

    def test_stopped_steam_passes_both_gpu_roles(self):
        with patch.object(steam_manager,'prepare_remote',return_value=dict(self.ready,steam_ready=False)),patch.object(steam_manager,'request',return_value={'changed':True}) as apply,patch.object(steam_manager,'reconnect_client',return_value='connected'):
            steam_manager.connect_server(self.config,0,1)
            apply.assert_called_once_with(self.config,'apply',0,1)

    def test_missing_stream_repairs_existing_mapping(self):
        with patch.object(steam_manager,'prepare_remote',side_effect=[dict(self.ready,sunshine_ready=False),self.ready]) as prepare,patch.object(steam_manager,'request') as apply,patch.object(steam_manager,'connect_client',return_value='connected'):
            steam_manager.connect_server(self.config)
            self.assertFalse(prepare.call_args.kwargs['check_only']);apply.assert_not_called()

    def test_close_stopped_server_is_read_only(self):
        value={'steam_running':False,'sunshine_running':False,'display_running':False,'game_running':False}
        with patch.object(close_remote_steam,'remote',return_value=value) as remote:
            steam_manager.close_server(self.config)
            remote.assert_called_once_with(self.config,check_only=True)

    def test_close_active_game_refuses_before_shutdown(self):
        value={'steam_running':True,'sunshine_running':True,'display_running':True,'game_running':True}
        with patch.object(close_remote_steam,'remote',return_value=value) as remote:
            with self.assertRaises(RuntimeError):steam_manager.close_server(self.config)
            self.assertEqual(remote.call_count,1)

    def test_close_uses_selected_server_for_check_and_stop(self):
        value={'steam_running':True,'sunshine_running':True,'display_running':True,'game_running':False}
        b=server_profiles.resolve_server(self.profiles(),'lab-b',interactive=False)['config']
        with patch.object(close_remote_steam,'remote',side_effect=[value,{'stopped':True}]) as remote:
            steam_manager.close_server(b)
            self.assertEqual(remote.call_args_list[0].args[0]['ssh_alias'],'lab-b')
            self.assertEqual(remote.call_args_list[1].args[0]['ssh_alias'],'lab-b')

    def test_other_moonlight_host_is_not_reused(self):
        process={'Id':77,'CommandLine':'Moonlight.exe stream gpu-b.example Steam'}
        with patch.object(launcher,'moonlight_processes',return_value=[process]),patch.object(launcher.subprocess,'Popen') as spawn:
            with self.assertRaises(RuntimeError):launcher.connect_client(self.config,lambda _:None)
            spawn.assert_not_called()

    def test_same_moonlight_command_can_be_reused(self):
        process={'Id':77,'CommandLine':'Moonlight.exe stream gpu-a.example Steam'}
        with patch.object(launcher,'moonlight_processes',return_value=[process]),patch.object(launcher.subprocess,'Popen') as spawn:
            launcher.connect_client(self.config,lambda _:None);spawn.assert_not_called()
        active=json.loads((self.root/'active-moonlight.json').read_text());self.assertEqual(active['pid'],77)

    def test_gpu_request_uses_selected_ssh_endpoint(self):
        b=server_profiles.resolve_server(self.profiles(),'lab-b',interactive=False)['config']
        reply=subprocess.CompletedProcess([],0,stdout='{}\n',stderr='')
        with patch.object(gpu_picker.subprocess,'run',return_value=reply) as run:
            gpu_picker.request(b)
            args=run.call_args.args[0]
            self.assertIn('HostName=gpu-b.example',args);self.assertIn('2222',args);self.assertIn('lab-b',args)

    def test_other_backend_never_runs_sunshine_control(self):
        c=dict(self.config,backend='wolf')
        with patch.object(steam_manager,'prepare_remote') as probe,patch.object(steam_manager,'request') as apply,patch.object(close_remote_steam,'remote') as stop:
            self.assertTrue(steam_manager.inspect_server(c)['unsupported'])
            with self.assertRaises(RuntimeError):steam_manager.connect_server(c,0,1)
            with self.assertRaises(RuntimeError):steam_manager.close_server(c)
            probe.assert_not_called();apply.assert_not_called();stop.assert_not_called()


if __name__=='__main__':unittest.main()
