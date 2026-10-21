"""Offline tests: frame building, checksums and decoding of a real capture."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import decode          # noqa: E402
import protocol        # noqa: E402

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'npc-response.bin'


class ProtocolTests(unittest.TestCase):
    def test_npc_request_matches_recovered_bytes(self):
        self.assertEqual(
            protocol.build_npc_request().hex(),
            '0000001a011100d362012b0d4e504300000000000000000000e5')

    def test_header_checksum(self):
        self.assertEqual(protocol.checksum8(bytes.fromhex('0000001a011100')), 0xD3)

    def test_imei_nibble_swap(self):
        self.assertEqual(protocol.decode_imei(bytes.fromhex('3375980885662526')),
                         '357898058665262')
        self.assertEqual(protocol.decode_imei(bytes.fromhex('3375980885662507')),
                         '357898058665270')

    def test_luhn(self):
        self.assertTrue(protocol.luhn_ok('357898058665262'))
        self.assertFalse(protocol.luhn_ok('357898058665263'))


class DecodeTests(unittest.TestCase):
    def test_captured_payload(self):
        info = decode.decode_blob(FIXTURE.read_bytes())
        self.assertEqual(info.product_code, '059R3250')
        self.assertEqual(info.imei1, '357898058665262')
        self.assertEqual(info.imei2, '357898058665270')
        self.assertEqual(info.bt_id, '1C:65:E4:08:44:54')
        self.assertEqual(info.wlan_id, '5C:01:E5:08:44:54')
        self.assertEqual(info.npc_copies, 2)
        self.assertTrue(info.has_wssi)
        self.assertEqual(info.payload_bytes, 30353)

    def test_corrupt_checksum_is_rejected(self):
        frame = bytearray(FIXTURE.read_bytes())
        frame[-1] ^= 0xFF
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_npc_reply(bytes(frame))

    def test_truncated_frame_is_rejected(self):
        with self.assertRaises(protocol.ProtocolError):
            protocol.parse_npc_reply(FIXTURE.read_bytes()[:-10])


if __name__ == '__main__':
    unittest.main()
