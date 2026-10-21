"""The documented read-only transaction sequence."""
import time

from protocol import (ACK_OK, IDENTITY_REQUEST, SETUP_FRAMES, ProtocolError,
                      build_npc_request, le32)

# Identity reply: 05 01 15 ... total 81 bytes.
IDENTITY_BYTES = 81
IDENTITY_PREFIX = bytes.fromhex('05 01 15')

# HW_CONF magic 37 47 f4 58 followed by LE32 0x60 (96) payload bytes.
HWCONF_MAGIC = bytes.fromhex('37 47 f4 58')

ALGORITHM_CHUNK = 16384      # larger single writes dropped the phone
CHUNK_DELAY_S = 0.005


def read_identity(session, attempts=3) -> bytes:
    """Read-only identity query; retries only while the phone answers."""
    reply = b''
    for _ in range(attempts):
        session.write(IDENTITY_REQUEST)
        reply = session.read_exact(IDENTITY_BYTES, 400)
        if len(reply) == IDENTITY_BYTES and reply.startswith(IDENTITY_PREFIX):
            return reply
        time.sleep(0.05)
    raise ProtocolError(f'identity reply was {len(reply)} bytes, expected 81')


def send_secondary(session, body: bytes):
    """Preamble, LE32 length, then the 22,976-byte secondary loader."""
    session.write(bytes.fromhex('02 00 03 f0'))
    session.write(le32(len(body)))
    session.write(body, timeout_ms=5000)


def read_hwconf(session) -> bytes:
    """Consume the declared-length HW_CONF reply; no idle wait afterward."""
    frame = session.read_frame_le32(2500)
    if len(frame) < 8 or frame[:4] != HWCONF_MAGIC:
        raise ProtocolError(f'HW_CONF reply invalid: {len(frame)} bytes')
    return frame


def load_algorithm(session, body: bytes) -> tuple:
    """Send the algorithm body in chunks, read mode, ACK, read confirmation."""
    session.write(le32(len(body)))
    for offset in range(0, len(body), ALGORITHM_CHUNK):
        session.write(body[offset:offset + ALGORITHM_CHUNK], timeout_ms=5000)
        time.sleep(CHUNK_DELAY_S)
    mode = session.read_exact(4, 5000)
    value = int.from_bytes(mode, 'big') if len(mode) == 4 else None
    if value != 1:
        raise ProtocolError(f'algorithm mode reply {mode.hex() or "empty"}, expected 00000001')
    session.write(ACK_OK)
    second = session.read_exact(4, 2000)
    if second != ACK_OK:
        raise ProtocolError(f'post-ACK reply {second.hex() or "empty"}, expected 00000001')
    return mode, second


def run_setup(session) -> list:
    """Send the four BEST setup frames and keep each reply."""
    replies = []
    for index, frame in enumerate(SETUP_FRAMES):
        session.write(frame)
        reply = session.read_idle(800, 120)
        if not reply:
            raise ProtocolError(f'setup frame {index} got an empty reply')
        replies.append(reply)
    return replies


def read_npc(session) -> bytes:
    """Send the 26-byte NPC read and capture its BE32-length reply."""
    session.write(build_npc_request())
    frame = session.read_frame_be32(3000)
    if len(frame) < 12:
        raise ProtocolError(f'NPC reply too short: {len(frame)} bytes')
    return frame
