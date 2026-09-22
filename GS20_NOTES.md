# BMW GS20 (Siemens / GM 5L40-E) notes

Working notes for using this tool against the BMW GS20 transmission control
unit. Everything below was measured or taken from a datasheet; anything still
unverified is marked as such.

## Module

| | |
|---|---|
| ECU | Siemens GS20, BMW EGS for the GM 5L40-E (A5S 360R / A5S 390R) |
| CPU | Infineon `SAK-C167CR-LM` (144-pin MQFP) |
| Variant | **ROMless** - the `-LM` suffix has no on-chip program memory |
| Fitted to | E46 / E53 / E83 with the 5-speed auto |

Because the CPU is ROMless the firmware lives in external flash. The MS4X wiki
records an `AM29F400BB` (4 Mbit, 44-pin SO) for this module; on the board I
opened, no 44-pin flash is visible on the component side, so it is presumably
on the underside. **Confirm before relying on the external-flash write path.**

## Memory map (from the module's own firmware)

| Region | Address | Size |
|---|---|---|
| Boot block | `0x080000` | 64 KB |
| Calibration | `0x090000` | 64 KB |
| Program | `0x0A0000` | 256 KB |

DS2 diagnostics can read the calibration only; the program and boot regions are
refused (`0xB0`). That is the reason for using boot mode.

## Entering boot mode

`P0L.4` low at the end of reset selects the bootstrap loader (C167CR user
manual, ch. 14). On the 144-pin package that is **pin 104**.

| Signal | CPU pin | Notes |
|---|---|---|
| `P0L.4` / `AD4` | **104** | pull to ground during reset |
| `P3.10` / `TxD0` | **77** | CPU output -> adapter RXD |
| `P3.11` / `RxD0` | **78** | CPU input  <- adapter TXD |
| `VSS` (ground) | **18, 45, 71, 110** | verified 71 and 110 are common |
| `VDD` | 17, 46, 56, 126, 136 | |
| `RSTIN` | 140 | |

Pin 1 is the bottom-left corner with the part number reading normally; pins run
counter-clockwise, 36 per side. So pins 73-108 are the top edge running
right-to-left: pin 104 is the 5th pin in from the top-left corner, and pins
77/78 are the 5th and 6th in from the top-right corner.

If the external flash chip is found, `P0L.4` is also one of its address lines
(`A4`, pin 7 on a 44-pin SO `29F400`), which is a much easier place to tap.

**Release the boot pin before reading.** It is an address line; leaving it
grounded pulls `A4` low and the dump comes back corrupt. A good read has `0xFA`
(the C167 `JMPS` opcode) at offsets `0x00`, `0x04`, `0x08` and `0x0C`.

## Wiring

```
adapter TXD  ->  CPU pin 78   (RxD0)
adapter RXD  <-  CPU pin 77   (TxD0)
adapter GND  ->  CPU pin 110  (or any VSS / board ground)

jumper       :   pin 104 -> pin 110      (remove once the monitor is running)
12 V supply  ->  connector terminal 30 + terminal 15, and ground
```

A 5 V FTDI breakout (FT232RL) is the simplest adapter - **set the jumper to
5 V**, the C167 is a 5 V part. The adapter is powered from USB; the ECU needs
its own 12 V. Do not feed the adapter's VCC into the module.

## Reading

```
python3 ME7BootTool.py 28800 -readInt 0x10000 gs20_boot.bin 0x080000
python3 ME7BootTool.py 28800 -readInt 0x10000 gs20_cal.bin  0x090000
python3 ME7BootTool.py 28800 -readInt 0x40000 gs20_prog.bin 0x0A0000
```

The `[startaddr]` argument is an addition in this fork; upstream hard-codes
`IntRomAddress` to `0x010000`.

## Writing - not supported yet

`-writeextflash` only knows the AMD `29Fx00B` command set with the ME7 /
Simos3 / EDC15 memory layouts. Whether it applies here depends on whether the
GS20 really does use an external `29F400`:

* **external `29F400` confirmed** - the existing driver should be close; the
  write base address still needs to match the GS20 map.
* **no external flash** - a new driver is needed for the on-chip flash
  controller, and the infrastructure in this tool (BSL entry, monitor upload,
  `SetWordAtAddress`, `GetBlockAtAddress`) is reusable.

Read first and identify the flash before attempting any write.

## Changes in this fork

* serial port discovery also matches macOS / Linux device names, and skips
  `/dev/tty.usb*` in favour of the `/dev/cu.*` twin
* `-readInt` takes an optional start address
