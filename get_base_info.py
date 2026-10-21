#!/usr/bin/env python3
"""Guided, read-only base-info reader for the Nokia Asha 501 (RM-902).

The tool walks the operator through entering flash mode, runs the documented
loader/read sequence over USB, decodes the NPC object and saves every raw
reply.  It never sends a flash, erase, reset or unlock command.
"""
import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from chain import (load_algorithm, read_hwconf, read_identity, read_npc,
                   run_setup, send_secondary)
from decode import decode_blob
from loaders import load_bodies
from protocol import ProtocolError
from session import DeviceLost, RomSession
from ui import UI

HERE = Path(__file__).resolve().parent
DEFAULT_TIMEOUT = 90


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description='Read and decode base information from an RM-902 in flash mode.')
    parser.add_argument('--no-color', action='store_true', help='plain output')
    parser.add_argument('--no-prompt', action='store_true',
                        help='skip the guided Enter prompts (start waiting immediately)')
    parser.add_argument('--timeout', type=int, default=DEFAULT_TIMEOUT,
                        help=f'seconds to wait for the flash-mode device (default {DEFAULT_TIMEOUT})')
    parser.add_argument('--output', type=Path,
                        help='capture directory (default: captures/<UTC timestamp>)')
    parser.add_argument('--loaders', type=Path, default=HERE / 'loaders',
                        help='directory holding secondary.bin and algorithm.bin')
    parser.add_argument('--decode', type=Path, metavar='NPC_BIN',
                        help='decode a saved npc-response.bin without touching the phone')
    return parser.parse_args(argv)


def guide(ui, skip_prompts, timeout):
    """Explain the physical steps; the phone cannot be detected until step 2."""
    ui.header('Step 1 — power off and connect')
    ui.note('1. Insert a charged battery.')
    ui.note('2. Unplug the USB cable.')
    ui.note('3. Hold power for about 10 seconds until the phone is off.')
    ui.note('4. Plug the USB cable back in; the phone must stay off.')
    if not skip_prompts:
        input('     Press Enter when done. ')
    ui.header('Step 2 — enter flash mode')
    ui.note('Press Enter, then IMMEDIATELY short-press power once.')
    ui.note(f'The tool waits up to {timeout} s for 0421:0106 revision 0026.')
    if not skip_prompts:
        input('     Press Enter to arm the window. ')


def run_capture(session, secondary, algorithm, ui):
    """Run identity -> loaders -> ACK -> setup -> NPC and return all replies."""
    ui.step('1/6  Reading identity')
    identity = read_identity(session)
    ui.ok(f'{len(identity)} bytes')

    ui.step('2/6  Sending secondary loader')
    send_secondary(session, secondary)
    hwconf = read_hwconf(session)
    ui.ok(f'HW_CONF {len(hwconf)} bytes')

    ui.step('3/6  Sending algorithm loader')
    mode, ack = load_algorithm(session, algorithm)
    ui.ok(f'mode {mode.hex()}, ACK {ack.hex()}')

    ui.step('4/6  Running setup frames')
    setup = run_setup(session)
    ui.ok('replies: ' + ', '.join(str(len(reply)) for reply in setup) + ' bytes')

    ui.step('5/6  Reading NPC object')
    npc = read_npc(session)
    ui.ok(f'{len(npc)} bytes')

    ui.step('6/6  Decoding')
    info = decode_blob(npc)
    ui.ok('payload parsed')
    return dict(identity=identity, hwconf=hwconf, mode=mode, ack=ack,
                setup=setup, npc=npc, info=info)


def save_capture(outdir, art):
    """Write every raw reply plus a JSON manifest; never overwrite silently."""
    outdir.mkdir(parents=True, exist_ok=True)
    blobs = {
        'identity.bin': art['identity'],
        'hwconf.bin': art['hwconf'],
        'algorithm-mode.bin': art['mode'],
        'algorithm-ack.bin': art['ack'],
        'npc-response.bin': art['npc'],
    }
    for index, reply in enumerate(art['setup']):
        blobs[f'setup-{index}.bin'] = reply
    manifest = {'created_utc': datetime.now(timezone.utc).isoformat(), 'files': {}}
    for name, data in blobs.items():
        (outdir / name).write_bytes(data)
        manifest['files'][name] = {'bytes': len(data),
                                   'sha256': hashlib.sha256(data).hexdigest()}
    manifest['base_info'] = art['info'].as_dict()
    (outdir / 'result.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return outdir


def _imei_text(value, luhn):
    if not value.isdigit():
        return value
    return f'{value}  (Luhn {"ok" if luhn else "failed"})'


def print_summary(ui, info, source, captured=True):
    ui.header('Base information')
    ui.field('Product code', info.product_code)
    ui.field('IMEI 1', _imei_text(info.imei1, info.imei1_luhn))
    ui.field('IMEI 2', _imei_text(info.imei2, info.imei2_luhn))
    ui.field('BT ID', info.bt_id)
    ui.field('WLAN ID', info.wlan_id)
    ui.field('NPC payload', f'{info.payload_bytes:,} bytes, {info.npc_copies} NPC0 copies')
    ui.field('WSSI record', 'present' if info.has_wssi else 'not found')

    ui.header('Raw identifier blocks')
    ui.field('Unit value', info.unit_hex)
    ui.field('Identifier', info.identifier_hex)
    ui.field('PAPUB key', info.papub_hex)
    ui.field('Key block 2', info.key2_hex)

    if captured:
        ui.header('Capture')
        ui.field('Directory', str(source))
        ui.note('identity.bin, hwconf.bin, setup-*.bin, npc-response.bin, result.json')
        ui.note('No flash, erase, reset or unlock command was sent.')
    else:
        ui.header('Source')
        ui.field('File', str(source))


def run_decode(path, ui):
    """Decode an existing capture without opening USB."""
    try:
        info = decode_blob(path.read_bytes())
    except (OSError, ProtocolError) as exc:
        ui.error(str(exc))
        return 2
    print_summary(ui, info, path, captured=False)
    return 0


def wait_for_session(timeout, ui):
    """Poll with a dot every half second; print guidance when nothing appears."""
    progress = {'next': 0.0}

    def on_wait(elapsed):
        if elapsed >= progress['next']:
            print('.', end='', flush=True)
            progress['next'] = elapsed + 0.5

    try:
        session = RomSession.find(timeout, on_wait)
    except DeviceLost as exc:
        ui.error(str(exc))
        return None
    print()
    if session is not None:
        return session
    ui.error(f'no 0421:0106 revision 0026 device within {timeout} s')
    ui.note('If it enumerated as 0421:0000, the phone booted to the OS: power off and retry.')
    ui.note('If nothing appeared, repeat the power-off / cable / short-press sequence.')
    return None


def main(argv=None):
    args = parse_args(argv)
    ui = UI(color=not args.no_color)
    ui.banner()
    if args.decode:
        return run_decode(args.decode, ui)
    try:
        secondary, algorithm = load_bodies(args.loaders)
    except (OSError, ValueError) as exc:
        ui.error(str(exc))
        return 1

    guide(ui, args.no_prompt, args.timeout)
    ui.step('Waiting for the phone')
    session = wait_for_session(args.timeout, ui)
    if session is None:
        return 2
    ui.ok('phone found in flash mode')

    try:
        session.open()
        art = run_capture(session, secondary, algorithm, ui)
    except (ProtocolError, DeviceLost) as exc:
        ui.error(str(exc))
        ui.note('The phone left flash mode or answered outside the recovered contract.')
        ui.note('Power-cycle it and run again; no data was written.')
        return 2
    finally:
        session.close()

    outdir = args.output or HERE / 'captures' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    save_capture(outdir, art)
    print_summary(ui, art['info'], outdir)
    return 0


if __name__ == '__main__':
    sys.exit(main())
