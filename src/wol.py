import socket
import time


def send_magic_packet(mac: str, host: str, port: int, repeat: int = 5) -> None:
    """Sends a standard Wake-on-LAN magic packet, repeated a few times a fraction of a
    second apart. The magic packet is a single unacknowledged UDP broadcast - there's
    no retry or confirmation built into the protocol, so any one send can simply be
    dropped by the switch or NIC with zero error reported; repeating it is the
    standard way real WoL tools make this reliable in practice. Getting it to reach a
    sleeping NIC at all (same broadcast domain, a LAN relay, router WoL-forwarding,
    etc.) is still the caller's own network setup - this just sends it where it's
    told to, more than once."""
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        raise ValueError(f"not a MAC address: {mac!r}")

    packet = b"\xff" * 6 + mac_bytes * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for i in range(repeat):
            sock.sendto(packet, (host, port))
            if i < repeat - 1:
                time.sleep(0.2)
