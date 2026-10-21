# base_info — Nokia Asha 501 (RM-902) read-only information reader

Guided end-to-end tool: it tells you when to power off, connect the cable and
short-press power, then performs the documented loader/read sequence and
decodes the phone's NPC object to the terminal.

It does not flash, erase, reset or unlock anything. The two vendor loaders run
from RAM; only identity, HW_CONF setup replies and the NPC object are read.

## How and why?

The goal of the whole project is to dump entire firmware with all the data from
a locked 2014 Nokia Asha 501. To do this, I utilize Reverse Engineer Anything
skill against Nokia Care Suite and other unofficial phone flashing software.
This entire code was created by AI agents and the only human written note is
this paragraph. This script is just a first step in the journey to create a PoC
that will read IMEI2 and other values from the phone using standard methods
known before flashing. Some of the ground work was done by GPT-6.1-Sol and
GPT-6-Astra. However, the most helpful here turned out to be DeepSeek 4.1 Flash
1017.

## Install

    cd ~/Projects/Asha501/tools/base_info
    python3 -m pip install -r requirements.txt

USB access to `0421:0106` is required. On Linux either run as root or install a
udev rule for the device; a `Permission denied` error means the rule is missing.

## Run

    python3 get_base_info.py
    python3 get_base_info.py --no-color
    python3 get_base_info.py --timeout 120 --output ~/asha-capture

Options:

    --no-color      plain text output
    --no-prompt     skip the guided Enter prompts (starts waiting immediately)
    --timeout N     seconds to wait for the flash-mode device (default 90)
    --output DIR    capture directory (default captures/<UTC timestamp>)
    --loaders DIR   directory with secondary.bin and algorithm.bin
    --decode FILE   decode a saved npc-response.bin, no phone access

Example without a phone:

    python3 get_base_info.py --decode tests/fixtures/npc-response.bin

## Physical sequence

1. Insert a charged battery.
2. Unplug the USB cable.
3. Hold power for about 10 seconds until the phone is off.
4. Plug the USB cable back in — the phone must stay off.
5. Press Enter in the tool, then immediately short-press power once.

The tool then waits for `0421:0106` revision `0026`. If the phone enumerates as
`0421:0000` it booted to the OS instead; power it off and repeat.

## Output

Decoded to stdout:

- product code
- IMEI 1 and IMEI 2 (with Luhn check)
- Bluetooth and WLAN IDs
- unit value, identifier block, PAPUB key block, second key block
- NPC payload size, number of NPC0 copies, WSSI presence

Every raw reply is saved under the capture directory (`identity.bin`,
`hwconf.bin`, `setup-*.bin`, `npc-response.bin`) with SHA256 hashes and decoded
fields in `result.json`. Nothing is overwritten: each run gets its own
timestamped directory unless `--output` points at an existing one.

## Loader provenance

`loaders/secondary.bin` (22,976 bytes, SHA256 `0b894fec…23cce`) and
`loaders/algorithm.bin` (207,440 bytes, SHA256 `81fe1d88…ab45a`) are the exact
bodies prepared offline from the retained Care Suite `XG223_v11_usb2nd.fg` and
`XG223_v11_usbalg.fg`. The tool verifies both hashes before opening the phone.
See `loaders/README.md` for the licensing note.

## Troubleshooting

- **No device found** — repeat the power-off / cable / short-press sequence.
  The flash window lasts only a few seconds.
- **`0421:0000` appears** — the phone booted normally; power it off and retry.
- **Permission denied / could not claim interface** — add a udev rule or run
  with sufficient privileges.
- **Phone disappears mid-run** — the window closed. Nothing was written;
  power-cycle and run again.

## Tests

    python3 -m unittest discover -s tests -v
