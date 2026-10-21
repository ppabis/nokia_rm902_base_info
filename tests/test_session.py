"""Session-level tests with a fake USB device (no hardware)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import usb.core  # noqa: E402
from session import RomSession  # noqa: E402
from get_base_info import save_capture  # noqa: E402
from decode import decode_blob  # noqa: E402

FIXTURE = Path(__file__).resolve().parent / 'fixtures' / 'npc-response.bin'


class FakeDev:
    def __init__(self, chunks):
        self.chunks = list(chunks)
        self.requests = []

    def read(self, endpoint, size, timeout):
        self.requests.append(size)
        if not self.chunks:
            raise usb.core.USBTimeoutError('timeout')
        return self.chunks.pop(0)[:size]


class SessionTests(unittest.TestCase):
    def test_read_exact_assembles_chunks(self):
        session = RomSession(FakeDev([b'abc', b'def']))
        self.assertEqual(session.read_exact(6, 100), b'abcdef')

    def test_read_exact_returns_short_on_timeout(self):
        session = RomSession(FakeDev([b'ab']))
        self.assertEqual(session.read_exact(6, 20), b'ab')

    def test_short_header_read_keeps_surplus(self):
        frame = bytes(range(104))
        session = RomSession(FakeDev([frame]))
        self.assertEqual(session.read_exact(8, 100), frame[:8])
        self.assertEqual(session.read_exact(96, 100), frame[8:])

    def test_requests_are_packet_multiples(self):
        dev = FakeDev([b'a' * 512, b'b' * 512])
        RomSession(dev).read_exact(600, 100)
        self.assertTrue(all(size % 512 == 0 and size >= 512 for size in dev.requests))

    def test_read_frame_be32(self):
        session = RomSession(FakeDev([bytes.fromhex('00000008'), bytes.fromhex('01110000')]))
        self.assertEqual(session.read_frame_be32(100), bytes.fromhex('0000000801110000'))

    def test_read_idle_stops_after_quiet_endpoint(self):
        session = RomSession(FakeDev([b'\x80']))
        self.assertEqual(session.read_idle(10, 10), b'\x80')


class CaptureTests(unittest.TestCase):
    def test_save_capture_writes_blobs_and_manifest(self):
        npc = FIXTURE.read_bytes()
        art = dict(identity=b'\x05' * 81, hwconf=b'\x37' * 104, mode=bytes.fromhex('00000001'),
                   ack=bytes.fromhex('00000001'), setup=[b'\x80', b'\x80'],
                   npc=npc, info=decode_blob(npc))
        with tempfile.TemporaryDirectory() as tmp:
            out = save_capture(Path(tmp) / 'run', art)
            self.assertTrue((out / 'npc-response.bin').is_file())
            self.assertTrue((out / 'result.json').is_file())
            self.assertEqual((out / 'setup-1.bin').read_bytes(), b'\x80')
            self.assertIn('base_info', (out / 'result.json').read_text())


if __name__ == '__main__':
    unittest.main()
