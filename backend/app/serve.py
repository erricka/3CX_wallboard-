"""Run the wallboard on IPv4 and, where the machine has it, IPv6 too.

GitHub Codespaces' port forwarding may connect over either, and a server that
only listens on one of them shows up as "HTTP ERROR 502".

    python -m app.serve [port]
"""

import logging
import os
import socket
import sys

import uvicorn


def listeners(port: int) -> list[socket.socket]:
    socks = []
    for family, address in ((socket.AF_INET, "0.0.0.0"), (socket.AF_INET6, "::")):
        try:
            sock = socket.socket(family, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if family == socket.AF_INET6:
                sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)
            sock.bind((address, port))
        except OSError as exc:
            if family == socket.AF_INET:
                raise
            logging.getLogger(__name__).info("No IPv6 listener (%s); IPv4 only", exc)
            continue
        socks.append(sock)
    return socks


def main() -> None:
    port = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PORT", 8000))
    server = uvicorn.Server(uvicorn.Config("app.main:create_app", factory=True))
    socks = listeners(port)
    print(f"Wallboard listening on port {port} ({', '.join(s.getsockname()[0] for s in socks)})", flush=True)
    server.run(sockets=socks)


if __name__ == "__main__":
    main()
