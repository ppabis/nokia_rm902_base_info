"""Small pyusb wrapper for the RM-902 flash-mode bulk endpoints."""
import time

import usb.core
import usb.util

from protocol import BCD_DEVICE, EP_IN, EP_OUT, PID, VID, ProtocolError


class DeviceLost(Exception):
    """The phone left flash mode or stopped answering."""


class RomSession:
    """One open bulk session; only endpoints 0x02 (OUT) and 0x83 (IN)."""

    def __init__(self, device):
        self.dev = device
        self._detached = False
        self._rx = bytearray()   # bytes read ahead, e.g. a full packet for an 8-byte header

    @staticmethod
    def _packet_size(remaining: int) -> int:
        """usbfs rejects buffers smaller than a 512-byte packet (EOVERFLOW)."""
        return max(512, ((remaining + 511) // 512) * 512)

    @classmethod
    def find(cls, timeout_s, on_wait=None):
        """Poll for 0421:0106 revision 0026 and return a session, or None."""
        start = time.monotonic()
        while time.monotonic() - start < timeout_s:
            try:
                devices = usb.core.find(find_all=True, idVendor=VID, idProduct=PID)
            except usb.core.NoBackendError as exc:
                raise DeviceLost('libusb backend missing: install libusb-1.0') from exc
            for dev in devices or []:
                if dev.bcdDevice == BCD_DEVICE:
                    return cls(dev)
            if on_wait:
                on_wait(time.monotonic() - start)
            time.sleep(0.1)
        return None

    def open(self):
        """Claim interface 0, detaching a host driver only if one is attached."""
        try:
            self.dev.get_active_configuration()
        except usb.core.USBError:
            self.dev.set_configuration()
        try:
            if self.dev.is_kernel_driver_active(0):
                self.dev.detach_kernel_driver(0)
                self._detached = True
        except (NotImplementedError, usb.core.USBError):
            pass
        try:
            usb.util.claim_interface(self.dev, 0)
        except usb.core.USBError as exc:
            raise DeviceLost(f'could not claim interface 0: {exc}') from exc

    def close(self):
        try:
            usb.util.release_interface(self.dev, 0)
        except usb.core.USBError:
            pass
        if self._detached:
            try:
                self.dev.attach_kernel_driver(0)
            except usb.core.USBError:
                pass

    def write(self, data: bytes, timeout_ms: int = 2000):
        """Send one bulk transfer; a short count means the phone went away."""
        try:
            sent = self.dev.write(EP_OUT, data, timeout=timeout_ms)
        except usb.core.USBError as exc:
            raise DeviceLost(f'bulk OUT failed: {exc}') from exc
        if sent != len(data):
            raise DeviceLost(f'bulk OUT accepted {sent}/{len(data)} bytes')

    def read_exact(self, size: int, timeout_ms: int) -> bytes:
        """Read up to size bytes; returns short data on timeout, raises on loss.

        Reads are issued in 512-byte multiples and the surplus is buffered, so
        a short header read does not overflow when the phone sends a whole
        frame (104-byte HW_CONF, 4-byte NPC length, ...).
        """
        result = bytearray()
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(result) < size:
            if self._rx:
                take = min(size - len(result), len(self._rx))
                result.extend(self._rx[:take])
                del self._rx[:take]
                continue
            remaining = int((deadline - time.monotonic()) * 1000)
            if remaining <= 0:
                break
            request = self._packet_size(size - len(result))
            try:
                chunk = self.dev.read(EP_IN, request, timeout=remaining)
            except usb.core.USBTimeoutError:
                break
            except usb.core.USBError as exc:
                raise DeviceLost(f'bulk IN failed: {exc}') from exc
            if not chunk:
                break
            result.extend(bytes(chunk))
            if len(result) > size:
                self._rx[:0] = result[size:]   # keep the rest of the packet
                del result[size:]
        return bytes(result)

    def read_idle(self, first_ms: int, idle_ms: int, max_bytes: int = 8192) -> bytes:
        """Read until the endpoint is quiet for idle_ms, bounded by max_bytes."""
        buffer = bytearray()
        while len(buffer) < max_bytes:
            timeout = idle_ms if buffer else first_ms
            try:
                chunk = self.dev.read(EP_IN, 4096, timeout=timeout)  # packet multiple
            except usb.core.USBTimeoutError:
                break
            except usb.core.USBError as exc:
                raise DeviceLost(f'bulk IN failed: {exc}') from exc
            if not chunk:
                break
            buffer.extend(bytes(chunk))
        return bytes(buffer)

    def read_frame_be32(self, timeout_ms: int, max_bytes: int = 262144) -> bytes:
        """Read a frame whose first four bytes are its total length (NPC)."""
        head = self.read_exact(4, timeout_ms)
        if len(head) < 4:
            return head
        total = int.from_bytes(head, 'big')
        if not 8 <= total <= max_bytes:
            raise ProtocolError(f'implausible BE32 frame length {total}')
        return head + self.read_exact(total - 4, timeout_ms)

    def read_frame_le32(self, timeout_ms: int, max_bytes: int = 65536) -> bytes:
        """Read a frame with an 8-byte magic then LE32 payload length (HW_CONF)."""
        head = self.read_exact(8, timeout_ms)
        if len(head) < 8:
            return head
        declared = int.from_bytes(head[4:8], 'little')
        if declared > max_bytes:
            raise ProtocolError(f'implausible LE32 frame length {declared}')
        return head + self.read_exact(declared, timeout_ms)
