#!/usr/bin/env python3
"""
Mock C167 in bootstrap mode, for testing ME7BootTool without hardware.

Creates a PTY pair; point the tool at the slave device and this answers as a
GS20 would: zero-byte autobaud, loader upload, minimon upload, then the
monitor command set.

The simulated flash carries a realistic GS20 layout so a read can be checked
against known content:

    0x080000  boot block   - starts FA 0A 00 1E (C167 JMPS vector table)
    0x090000  calibration  - version string at 0xFFC8
    0x0A0000  program
"""
import os, pty, sys, time, threading

# --- protocol constants, taken from ME7BootTool.py -------------------------
I_LOADER_STARTED      = 0x01
I_APPLICATION_STARTED = 0x03
A_ACK1                = 0xAA
A_ACK2                = 0xEA
C_WRITE_BLOCK         = 0x84
C_READ_BLOCK          = 0x85
C_GETCHECKSUM         = 0x33
C_TEST_COMM           = 0x93
C_WRITE_WORD          = 0x82
C_READ_WORD           = 0xCD
VARIANT_C167          = 0xC5      # what we answer to the zero byte

LOADER_LEN  = None                # learned from the real files
MINIMON_LEN = None


def build_flash():
    """A 512 KB module image with recognisable regions."""
    mem = bytearray(b'\xF8' * 0x80000)          # module 0x080000-0x0FFFFF

    # boot block: C167 vector table, 128 x JMPS 0x0A,<off>
    for i in range(128):
        off = 0x1E00 + i * 4
        mem[i * 4:i * 4 + 4] = bytes([0xFA, 0x0A, off & 0xFF, off >> 8])
    for i in range(0x200, 0x8000):
        mem[i] = (i * 7) & 0xFF                  # filler that is not uniform

    # calibration at file offset 0x10000
    cal = bytearray(b'\xFF' * 0x10000)
    cal[0x00:0x10] = bytes([0xFF, 0xFF, 0x00, 0x02, 0x96, 0x02, 0x61, 0x31,
                            0x41, 0x41, 0xFF, 0xFF, 0x00, 0x14, 0x8B, 0xFF])
    cal[0xFFC8:0xFFD8] = b'G2210_0090C0ER10'
    mem[0x10000:0x20000] = cal

    # program at file offset 0x20000
    for i in range(0x20000, 0x60000):
        mem[i] = (i * 31) & 0xFF
    mem[0x5FFC0:0x5FFD0] = b'G2210_0090C0'

    return mem


class MockC167:
    def __init__(self, fd, flash):
        self.fd = fd
        self.flash = flash
        self.state = 'autobaud'
        self.last_block = b''
        self.log = []

    # ---- low level -------------------------------------------------------
    def rd(self, n):
        out = b''
        while len(out) < n:
            try:
                c = os.read(self.fd, n - len(out))
            except OSError:
                return out
            if not c:
                return out
            out += c
        return out

    def wr(self, data):
        os.write(self.fd, bytes(data))

    def echo(self, data):
        """The K line loops our input back before any answer."""
        self.wr(data)

    def note(self, msg):
        self.log.append(msg)
        print('   [mock] ' + msg, flush=True)

    # ---- phases ----------------------------------------------------------
    def run(self):
        # 1. autobaud: a single 0x00 arrives, we answer with the variant byte
        b = self.rd(1)
        if not b:
            return
        if b[0] != 0x00:
            self.note('expected 0x00 autobaud byte, got 0x%02X' % b[0])
            return
        self.note('autobaud 0x00 -> answering variant 0x%02X' % VARIANT_C167)
        self.wr([VARIANT_C167])

        # 2. loader upload: 32 bytes, echoed, then I_LOADER_STARTED
        loader = self.rd(LOADER_LEN)
        self.note('loader received (%d bytes) -> ack 0x01' % len(loader))
        self.echo(loader)
        self.wr([I_LOADER_STARTED])

        # 3. minimon upload: echoed, then I_APPLICATION_STARTED
        core = self.rd(MINIMON_LEN)
        self.note('minimon received (%d bytes) -> ack 0x03' % len(core))
        self.echo(core)
        self.wr([I_APPLICATION_STARTED])

        # 4. monitor command loop
        self.note('monitor running')
        while True:
            c = self.rd(1)
            if not c:
                self.note('port closed')
                return
            self.command(c[0])

    # ---- monitor commands -------------------------------------------------
    def command(self, cmd):
        if cmd == C_TEST_COMM:
            self.echo([cmd])
            self.wr([A_ACK1, A_ACK2])
            self.note('TEST_COMM -> AA EA')

        elif cmd == C_WRITE_WORD:
            self.echo([cmd])
            self.wr([A_ACK1])
            payload = self.rd(5)          # addr(3, little endian) + word(2)
            self.echo(payload)
            self.wr([A_ACK2])
            addr = payload[0] | payload[1] << 8 | payload[2] << 16
            word = payload[3] | payload[4] << 8
            self.note('WRITE_WORD 0x%06X = 0x%04X' % (addr, word))

        elif cmd == C_READ_BLOCK:
            self.echo([cmd])
            self.wr([A_ACK1])
            hdr = self.rd(5)              # addr(3) + size(2)
            self.echo(hdr)
            addr = hdr[0] | hdr[1] << 8 | hdr[2] << 16
            size = hdr[3] | hdr[4] << 8
            off = addr - 0x080000
            if 0 <= off and off + size <= len(self.flash):
                data = bytes(self.flash[off:off + size])
            else:
                data = b'\xFF' * size
                self.note('READ_BLOCK 0x%06X OUT OF RANGE' % addr)
            self.wr(data + bytes([A_ACK2]))
            self.last_block = data
            self.note('READ_BLOCK 0x%06X len 0x%X' % (addr, size))

        elif cmd == C_GETCHECKSUM:
            self.echo([cmd])
            cs = 0
            for d in self.last_block:
                cs ^= d
            self.wr([0x00, cs, A_ACK2])
            self.note('GETCHECKSUM -> 0x%02X' % cs)

        else:
            self.echo([cmd])
            self.wr([A_ACK1, A_ACK2])
            self.note('unhandled command 0x%02X (acked anyway)' % cmd)


def main():
    global LOADER_LEN, MINIMON_LEN
    tool_dir = os.path.expanduser('~/Development/code/projects/C167BootTool')
    LOADER_LEN = os.path.getsize(os.path.join(tool_dir, 'Minimon/LOADK.bin'))
    MINIMON_LEN = os.path.getsize(os.path.join(tool_dir, 'Minimon/MINIMONK.bin'))

    master, slave = pty.openpty()
    name = os.ttyname(slave)
    print('mock C167 listening on %s' % name)
    print('   loader  = %d bytes' % LOADER_LEN)
    print('   minimon = %d bytes' % MINIMON_LEN)
    with open(os.path.expanduser('~/.mock_c167_port'), 'w') as f:
        f.write(name)

    mock = MockC167(master, build_flash())
    try:
        mock.run()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
