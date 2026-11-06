"""Forward Moonlight UDP over an authenticated TCP connection inside SSH.

Only the four dedicated Sunshine UDP ports are accepted. No third-party packages required.
The server listens on loopback; SSH provides transport encryption.
"""
import argparse
import asyncio
import hmac
import ipaddress
import logging
import json
import os
from pathlib import Path
import socket
import struct

PORTS = (48998, 48999, 49000, 49010)
HEADER = struct.Struct('!IHH')
MAX_PACKET = 65507
LOG = logging.getLogger('udp-bridge')


def udp_ports(args):
    base=getattr(args,'base_port',48989)
    return tuple(base+offset for offset in (9,10,11,21))


def readiness(args,ready):
    path=getattr(args,'ready_file',None)
    if not path:return
    temporary=path.with_suffix('.tmp')
    value={'generation':args.generation,'ready':ready,'pid':os.getpid()}
    temporary.write_text(json.dumps(value),encoding='utf-8');temporary.replace(path)


def enqueue(queue, channel, port, data):
    if not data or len(data) > MAX_PACKET:
        return
    try:
        queue.put_nowait(HEADER.pack(len(data), channel, port) + data)
    except asyncio.QueueFull:
        # Drop stale video packets instead of building unbounded latency.
        pass


async def send_frames(writer, queue):
    while True:
        writer.write(await queue.get())
        await writer.drain()


async def read_frame(reader):
    length, channel, port = HEADER.unpack(await reader.readexactly(HEADER.size))
    if not 0 < length <= MAX_PACKET or channel == 0:
        raise ValueError('Invalid UDP frame')
    return channel, port, await reader.readexactly(length)


def configure_tcp(writer):
    sock = writer.get_extra_info('socket')
    if sock:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)


class ReplyProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue, channel):
        self.queue, self.channel = queue, channel

    def datagram_received(self, data, addr):
        enqueue(self.queue, self.channel, 0, data)


class LocalProtocol(asyncio.DatagramProtocol):
    def __init__(self, port, queue, endpoints, channels):
        self.port, self.queue = port, queue
        self.endpoints, self.channels = endpoints, channels

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        key = (self.port, addr)
        channel = self.endpoints.get(key)
        if channel is None:
            if len(self.channels) >= 256:
                return
            channel = len(self.channels) + 1
            self.endpoints[key] = channel
            self.channels[channel] = (self.transport, addr)
        enqueue(self.queue, channel, self.port, data)


async def server_connection(reader, writer, token, upstream_host):
    peers = {}
    sender = None
    queue = asyncio.Queue(maxsize=1024)
    configure_tcp(writer)
    try:
        supplied = await asyncio.wait_for(reader.readexactly(len(token)), timeout=10)
        if not hmac.compare_digest(supplied, token):
            return
        writer.write(b'OK')
        await writer.drain()
        sender = asyncio.create_task(send_frames(writer, queue))
        loop = asyncio.get_running_loop()
        LOG.info('Authenticated UDP tunnel connected')
        while True:
            channel, port, data = await read_frame(reader)
            if port not in PORTS:
                raise ValueError('Destination port is not permitted')
            if channel not in peers:
                if len(peers) >= 256:
                    raise ValueError('Too many UDP peers')
                transport, _ = await loop.create_datagram_endpoint(
                    lambda: ReplyProtocol(queue, channel),
                    remote_addr=(upstream_host, port), family=socket.AF_INET)
                peers[channel] = (port, transport)
            expected_port, transport = peers[channel]
            if expected_port != port:
                raise ValueError('UDP channel destination changed')
            transport.sendto(data)
    except (asyncio.IncompleteReadError, ConnectionError, asyncio.TimeoutError):
        LOG.info('UDP tunnel disconnected')
    except (OSError, ValueError) as exc:
        LOG.warning('UDP tunnel stopped: %s', exc)
    finally:
        if sender:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        for _, transport in peers.values():
            transport.close()
        writer.close()
        try:await writer.wait_closed()
        except (ConnectionError,OSError):pass


async def run_server(args, token):
    server = await asyncio.start_server(
        lambda r, w: server_connection(r, w, token, args.upstream_host),
        '127.0.0.1', args.tcp_port)
    LOG.info('Server ready on 127.0.0.1:%s', args.tcp_port)
    async with server:
        await server.serve_forever()


async def client_session(args, token):
    readiness(args,False)
    channels, endpoints, transports = {}, {}, []
    writer=None;tasks=[]
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', args.tcp_port)
        configure_tcp(writer)
        writer.write(token)
        await writer.drain()
        if await asyncio.wait_for(reader.readexactly(2), 10) != b'OK':
            raise ValueError('UDP tunnel authentication failed')
        queue = asyncio.Queue(maxsize=1024)
        loop = asyncio.get_running_loop()
        for port in udp_ports(args):
            transport, _ = await loop.create_datagram_endpoint(
                lambda p=port: LocalProtocol(p, queue, endpoints, channels),
                local_addr=('127.0.0.1', port), family=socket.AF_INET)
            transports.append(transport)
        readiness(args,True)
        LOG.info('Client ready on UDP ports %s', ','.join(map(str, udp_ports(args))))
        async def receive():
            while True:
                channel, port, data = await read_frame(reader)
                if port != 0:raise ValueError('Invalid reply frame')
                if channel in channels:
                    transport, addr = channels[channel];transport.sendto(data, addr)
        tasks=[asyncio.create_task(send_frames(writer,queue)),asyncio.create_task(receive())]
        done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        for task in done:await task
    finally:
        readiness(args,False)
        for transport in transports:
            transport.close()
        for task in tasks:task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if writer:
            writer.close()
            try:await writer.wait_closed()
            except (ConnectionError,OSError):pass


async def run_client(args, token):
    while True:
        try:
            await client_session(args, token)
        except (OSError, ConnectionError, asyncio.IncompleteReadError,
                asyncio.TimeoutError) as exc:
            LOG.warning('Waiting for SSH tunnel: %s', type(exc).__name__)
            await asyncio.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('server', 'client'))
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--tcp-port', type=int, default=19089)
    parser.add_argument('--upstream-host', default='127.0.0.1')
    parser.add_argument('--base-port',type=int,default=48989)
    parser.add_argument('--ready-file',type=Path)
    parser.add_argument('--generation',default='standalone')
    args = parser.parse_args()
    if not 6<=args.base_port<=65514:parser.error('Invalid Sunshine base port')
    global PORTS
    PORTS=udp_ports(args)
    if not ipaddress.ip_address(args.upstream_host).is_loopback:
        parser.error('Upstream must be a loopback address')
    token = args.token_file.read_bytes()
    if len(token) != 32:
        parser.error('Token file must contain 32 random bytes')
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(run_server(args, token) if args.mode == 'server'
                    else run_client(args, token))
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
