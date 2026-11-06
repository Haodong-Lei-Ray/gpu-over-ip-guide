import asyncio
from argparse import Namespace
import json
from pathlib import Path
import random
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import stream_transport as transport
import ssh_udp_bridge as bridge
import open_remote_steam as launcher


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)
        self.config={'_client_state_dir':str(self.folder),'_server_id':'lab-a',
                     'stream_tunnel':{'base_port':48989,'bridge_port':49150}}
        self.record,self.request,self.ready=transport.paths(self.config)
        transport.write_json(self.record,{'pid':77,'version':transport.VERSION})
        transport.write_json(self.request,{'generation':'old'})
        transport.write_json(self.ready,{'generation':'old','ready':True})
        self.process={'CommandLine':str(Path(transport.__file__).resolve())+' --server lab-a'}

    def test_fresh_stream_rejects_previous_authenticated_udp_state(self):
        waits=[]
        def progress(delay):
            generation=transport.read_json(self.request)['generation'];self.assertNotEqual(generation,'old')
            waits.append(delay)
            transport.write_json(self.ready,{'generation':generation,'ready':len(waits)>1})
        with patch.object(launcher,'powershell_json',return_value=self.process),patch.object(transport.time,'sleep',side_effect=progress),patch.object(transport,'reachable',return_value=True),patch.object(transport.subprocess,'Popen') as spawn:
            transport.ensure_transport(self.config,new_session=True)
            self.assertEqual(len(waits),2);spawn.assert_not_called()

    def test_healthy_existing_transport_is_reused_without_reset(self):
        with patch.object(launcher,'powershell_json',return_value=self.process),patch.object(transport,'reachable',return_value=True),patch.object(transport.time,'sleep') as wait:
            transport.ensure_transport(self.config)
            wait.assert_not_called();self.assertEqual(transport.read_json(self.request)['generation'],'old')

    def test_legacy_supervisor_is_not_silently_reused_or_duplicated(self):
        transport.write_json(self.record,{'pid':77})
        with patch.object(launcher,'powershell_json',return_value=self.process),patch.object(transport.subprocess,'Popen') as spawn:
            with self.assertRaisesRegex(RuntimeError,'旧版'):transport.ensure_transport(self.config,new_session=True)
            spawn.assert_not_called()

    def test_dead_saved_pid_starts_a_new_supervisor(self):
        class Child:pid=88
        def progress(delay):
            generation=transport.read_json(self.request)['generation']
            transport.write_json(self.ready,{'generation':generation,'ready':True})
        with patch.object(launcher,'powershell_json',return_value=None),patch.object(transport.subprocess,'Popen',return_value=Child()) as spawn,patch.object(transport,'reachable',return_value=True),patch.object(transport.time,'sleep',side_effect=progress):
            transport.ensure_transport(self.config,new_session=True)
            spawn.assert_called_once();self.assertEqual(transport.read_json(self.record)['pid'],88)


class UdpRelayTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ready.json';self.loop=asyncio.get_running_loop()
        self.base=None
        for _ in range(60):
            base=random.randint(52000,58000);probes=[]
            try:
                for offset in (9,10,11,21):
                    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);probes.append(sock);sock.bind(('127.0.0.1',base+offset))
                self.base=base;break
            except OSError:pass
            finally:
                for sock in probes:sock.close()
        self.assertIsNotNone(self.base)
        self.token=b'x'*32;self.previous=bridge.PORTS;bridge.PORTS=(self.base+9,)
        self.addCleanup(setattr,bridge,'PORTS',self.previous)
        self.server=await asyncio.start_server(lambda r,w:bridge.server_connection(r,w,self.token,'127.0.0.2'),'127.0.0.1',0)
        self.args=Namespace(tcp_port=self.server.sockets[0].getsockname()[1],base_port=self.base,ready_file=self.path,generation='new-stream')

    async def asyncTearDown(self):
        self.server.close();await self.server.wait_closed()

    async def test_authenticated_udp_round_trip_and_disconnect_readiness(self):
        class Echo(asyncio.DatagramProtocol):
            def connection_made(self,t):self.transport=t
            def datagram_received(self,data,address):self.transport.sendto(data,address)
        echo,_=await self.loop.create_datagram_endpoint(Echo,local_addr=('127.0.0.2',self.base+9))
        task=asyncio.create_task(bridge.client_session(self.args,self.token))
        sender=None
        try:
            for _ in range(150):
                if transport.udp_ready(self.path,'new-stream'):break
                await asyncio.sleep(.02)
            self.assertTrue(transport.udp_ready(self.path,'new-stream'))
            response=self.loop.create_future()
            class Receive(asyncio.DatagramProtocol):
                def datagram_received(self,data,address):
                    if not response.done():response.set_result(data)
            sender,_=await self.loop.create_datagram_endpoint(Receive,local_addr=('127.0.0.1',0))
            sender.sendto(b'ping-test',('127.0.0.1',self.base+9))
            self.assertEqual(await asyncio.wait_for(response,3),b'ping-test')
        finally:
            task.cancel();await asyncio.gather(task,return_exceptions=True);echo.close()
            if sender:sender.close()
        self.assertFalse(transport.udp_ready(self.path,'new-stream'))

    async def test_invalid_token_never_reports_udp_ready(self):
        with self.assertRaises(asyncio.IncompleteReadError):
            await bridge.client_session(self.args,b'z'*32)
        self.assertFalse(transport.udp_ready(self.path,'new-stream'))
