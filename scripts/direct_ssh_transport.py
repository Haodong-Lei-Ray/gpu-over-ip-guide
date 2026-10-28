"""Optional Windows SSH socket binding; no route or VPN changes."""
import msvcrt
import os
import socket
import struct
import sys
import threading


def main():
    if len(sys.argv) not in (6,7):
        raise ValueError("Usage: host port interface_index source_ipv4 allowed_host [allowed_port]")
    host, port, interface_index, source, allowed = sys.argv[1:6]
    allowed_port=int(sys.argv[6]) if len(sys.argv)==7 else 22
    if not 1<=allowed_port<=65535 or host != allowed or int(port) != allowed_port:
        raise ValueError("Connection is outside the configured SSH destination")
    socket.inet_aton(source)
    index = int(interface_index)
    if index <= 0:
        raise ValueError("Physical interface index required")
    for descriptor in (0, 1):
        msvcrt.setmode(descriptor, os.O_BINARY)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as connection:
        connection.setsockopt(socket.IPPROTO_IP, 31, struct.pack("!I", index))
        connection.bind((source, 0))
        connection.settimeout(10)
        connection.connect((host, int(port)))
        connection.settimeout(None)
        def upload():
            try:
                while True:
                    data = os.read(0, 65536)
                    if not data:
                        connection.shutdown(socket.SHUT_WR)
                        break
                    connection.sendall(data)
            except OSError:
                pass
        threading.Thread(target=upload, daemon=True).start()
        while True:
            data = connection.recv(65536)
            if not data:
                break
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError) as error:
        print("Direct SSH transport: " + str(error), file=sys.stderr)
        sys.exit(1)
