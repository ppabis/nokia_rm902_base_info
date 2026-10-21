"""RM-902 wire constants and frame builders.

Only the documented read path is implemented here: identity query, the two
vendor RAM loaders, the protocol-0x100 acknowledgement, four setup frames and
the NPC named-object read.  There is no flash, erase, reset or unlock frame.
"""
from dataclasses import dataclass


class ProtocolError(Exception):
    """The device returned something the recovered contract does not allow."""


# USB identity of the phone in flash/ROM mode (normal OS mode is 0421:0000).
VID = 0x0421
PID = 0x0106
BCD_DEVICE = 0x0026
EP_OUT = 0x02          # bulk OUT, 512-byte packets
EP_IN = 0x83           # bulk IN, 512-byte packets

# 4-byte read-only identity query.  Reply is 81 bytes and starts 05 01 15.
IDENTITY_REQUEST = bytes.fromhex('00 00 09 20')

# Sent immediately before the 22,976-byte secondary loader body.
SECONDARY_PREAMBLE = bytes.fromhex('02 00 03 f0')

# Raw protocol-0x100 acknowledgement, sent after the algorithm reports mode 1.
ACK_OK = bytes.fromhex('00 00 00 01')

# BEST 2.29 post-boot setup frames.  They are vendor startup templates:
#   #0 18 B: length 0x12, type 0, routing 0x10, body 00000001 01000000 0001
#   #1 16 B: length 0x10, type 0, routing 0x10, body 00000004 01010100
#   #2 14 B: length 0x0e, type 1, routing 0x11, command 0x60
#   #3 71 B: length 0x47, type 1, routing 0x11, opcode 0x61, four 0x2b records
# Header checksums (0xff - sum of the first seven bytes) are already applied.
SETUP_FRAMES = (
    bytes.fromhex('00000012001000dd00000001010000000001'),
    bytes.fromhex('00000010001000df0000000401010100'),
    bytes.fromhex('0000000e011100df6001290100d4'),
    bytes.fromhex('00000047011100a661042b0d4e504300000000000000000000'
                  '2b0d43434300000000000000000000'
                  '2b0d48574300000000000000000000'
                  '2b0d52264400000000000000000000d3'),
)

# NPC reply container: 8-byte envelope, 0xc6, N x (0x2c, length, payload),
# trailing checksum.
FUR_TYPE_REQUEST = 0x01
RESPONSE_ID = 0xC6
OBJECT_TAG = 0x2C
MAX_RECORDS = 120


def le32(value: int) -> bytes:
    """Little-endian 32-bit length used before loader bodies."""
    return value.to_bytes(4, 'little')


def checksum8(data: bytes) -> int:
    """One's-complement 8-bit checksum: 0xff - (sum & 0xff)."""
    return 0xFF - (sum(data) & 0xFF)


def build_npc_request(name: bytes = b'NPC') -> bytes:
    """Build the 26-byte named-object read for NPC.

    Layout: BE32 length 0x1a, type 0x01, routing 0x11, reserved 0x00,
    header checksum, opcode 0x62, then count 0x01 / tag 0x2b / length 0x0d /
    12-byte name / selector 0x00 / inner checksum.
    """
    if not isinstance(name, bytes) or not 1 <= len(name) <= 12:
        raise ValueError('name must be 1..12 bytes')
    inner = bytes([0x01, 0x2B, 0x0D]) + name.ljust(12, b'\0') + b'\x00'
    inner_ck = checksum8(inner)
    head = bytes.fromhex('00 00 00 1a 01 11 00')  # 26-byte frame, routing 0x11
    return head + bytes([checksum8(head), 0x62]) + inner + bytes([inner_ck])


@dataclass
class NpcReply:
    routing: int
    records: list
    payload: bytes


def _check_envelope_length(frame: bytes):
    if len(frame) < 12:
        raise ProtocolError('NPC reply shorter than envelope plus body header')
    if int.from_bytes(frame[0:4], 'big') != len(frame):
        raise ProtocolError('declared NPC length does not match received bytes')


def _check_envelope_header(frame: bytes):
    if frame[4] != FUR_TYPE_REQUEST or frame[6] != 0x00:
        raise ProtocolError('unexpected NPC envelope type or reserved byte')
    if frame[7] != checksum8(frame[0:7]):
        raise ProtocolError('NPC header checksum mismatch')


def _check_body_header(body: bytes):
    if body[0] != RESPONSE_ID:
        raise ProtocolError(f'NPC opcode {body[0]:#04x}, expected 0xc6')
    if not 1 <= body[1] <= MAX_RECORDS:
        raise ProtocolError(f'record count {body[1]} outside 1..{MAX_RECORDS}')


def _read_records(body: bytes, count: int) -> list:
    records = []
    cursor = 2
    limit = len(body) - 1          # last byte is the inner checksum
    for index in range(count):
        if cursor + 2 > limit:
            raise ProtocolError(f'record {index} header overruns body')
        tag, length = body[cursor], body[cursor + 1]
        end = cursor + 2 + length
        if tag != OBJECT_TAG or length == 0 or end > limit:
            raise ProtocolError(f'record {index} invalid tag/length')
        records.append(body[cursor + 2:end])
        cursor = end
    if cursor != limit:
        raise ProtocolError('unexpected bytes between last record and checksum')
    return records


def _check_inner_checksum(body: bytes):
    if body[-1] != checksum8(body[1:-1]):
        raise ProtocolError('NPC inner checksum mismatch')


def parse_npc_reply(frame: bytes) -> NpcReply:
    """Parse and validate one complete NPC reply; reject any deviation."""
    _check_envelope_length(frame)
    _check_envelope_header(frame)
    body = frame[8:]
    _check_body_header(body)
    records = _read_records(body, body[1])
    _check_inner_checksum(body)
    return NpcReply(routing=frame[5], records=records, payload=b''.join(records))


def decode_imei(field: bytes) -> str:
    """Decode one 8-byte BCD field: swap each byte's nibbles, drop digit 0."""
    if len(field) != 8:
        raise ProtocolError('IMEI field must be 8 bytes')
    text = field.hex().upper()
    if set(text) <= {'0'} or set(text) <= {'F'}:
        raise ProtocolError('blank IMEI field')
    swapped = ''.join(text[i + 1] + text[i] for i in range(0, len(text), 2))
    imei = swapped[1:16]       # vendor helper keeps 15 digits after the first
    if len(imei) != 15 or not imei.isdigit():
        raise ProtocolError('decoded IMEI is not 15 digits')
    return imei


def luhn_ok(digits: str) -> bool:
    """Standard Luhn check, used only to flag a suspicious IMEI."""
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2 == 1:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0
