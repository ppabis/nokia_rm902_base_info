"""Field extraction from the NPC payload (no I/O)."""
from dataclasses import asdict, dataclass

from protocol import decode_imei, luhn_ok, parse_npc_reply


@dataclass
class BaseInfo:
    product_code: str
    imei1: str
    imei2: str
    imei1_luhn: bool
    imei2_luhn: bool
    bt_id: str
    wlan_id: str
    identifier_hex: str
    papub_hex: str
    key2_hex: str
    unit_hex: str
    payload_bytes: int
    npc_copies: int
    has_wssi: bool

    def as_dict(self):
        return asdict(self)


def _named_value(payload: bytes, name: bytes, length: int):
    """Return the value after a NUL-padded name, or None."""
    index = payload.find(name)
    if index < 0 or index + len(name) + length > len(payload):
        return None
    pos = index + len(name)
    while pos < len(payload) and payload[pos] == 0:
        pos += 1
    return payload[pos:pos + length]


def _mac(payload: bytes, name: bytes):
    raw = _named_value(payload, name, 6)
    if raw is None:
        return 'not present'
    return ':'.join(f'{byte:02X}' for byte in raw)


def _imei(payload: bytes, marker: bytes):
    # Marker sits 8 bytes before the 8-byte BCD field in both GSM and GSM2.
    index = payload.find(marker)
    if index < 0:
        return 'not present'
    return decode_imei(payload[index + 8:index + 16])


def _slice(payload: bytes, base: int, offset: int, length: int) -> str:
    if base < 0:
        return 'not present'
    return payload[base + offset:base + offset + length].hex()


def extract(payload: bytes) -> BaseInfo:
    """Decode the fields this phone model exposes in its NPC object."""
    base = payload.find(b'NPC0')
    code_pos = payload.find(b'059R')
    code = payload[code_pos:code_pos + 8] if code_pos >= 0 else b''
    imei1 = _imei(payload, b'GSM\x00')
    imei2 = _imei(payload, b'GSM2')
    return BaseInfo(
        product_code=code.decode('ascii', 'replace') or 'not present',
        imei1=imei1,
        imei2=imei2,
        imei1_luhn=imei1.isdigit() and luhn_ok(imei1),
        imei2_luhn=imei2.isdigit() and luhn_ok(imei2),
        bt_id=_mac(payload, b'BT_ID'),
        wlan_id=_mac(payload, b'WLAN_ID'),
        identifier_hex=_slice(payload, base, 0x48, 19),
        papub_hex=_slice(payload, base, 0x5C, 20),
        key2_hex=_slice(payload, base, 0x70, 20),
        unit_hex=_slice(payload, base, 0x34, 8),
        payload_bytes=len(payload),
        npc_copies=payload.count(b'NPC0'),
        has_wssi=b'WSSI' in payload,
    )


def decode_blob(frame: bytes) -> BaseInfo:
    """Parse a complete NPC reply frame and return the decoded fields."""
    return extract(parse_npc_reply(frame).payload)
