import socket


def send_magic_packet(mac: str, host: str, port: int) -> None:
    """Sends one standard Wake-on-LAN magic packet. Getting it to actually reach a
    sleeping NIC (same broadcast domain, a LAN relay, router WoL-forwarding, etc.) is
    the caller's network setup - this just sends the packet where it's told to."""
    mac_bytes = bytes.fromhex(mac.replace(":", "").replace("-", ""))
    if len(mac_bytes) != 6:
        raise ValueError(f"not a MAC address: {mac!r}")

    packet = b"\xff" * 6 + mac_bytes * 16

    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.sendto(packet, (host, port))
