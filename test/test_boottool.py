#!/usr/bin/env python3
"""
Drive ME7BootTool's read path against the mock C167 over a PTY pair.

This imports the tool as a module so the real RunFunc / GetBlockAtAddress
code runs - only the serial endpoint is simulated.
"""
import os, sys, pty, threading, importlib.util, io

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.expanduser('~/Development/code/projects/C167BootTool/ME7BootTool.py')
sys.path.insert(0, HERE)
from mock_c167 import MockC167, build_flash, VARIANT_C167

import serial


def load_tool():
    spec = importlib.util.spec_from_file_location('me7', TOOL)
    mod = importlib.util.module_from_spec(spec)
    # the tool runs its CLI at import time; feed it -h so it prints usage and
    # returns instead of trying to open a port
    argv = sys.argv
    sys.argv = ['ME7BootTool.py']
    buf = io.StringIO()
    out = sys.stdout
    sys.stdout = buf
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    finally:
        sys.stdout = out
        sys.argv = argv
    return mod


def main():
    tool = load_tool()
    tool_dir = os.path.dirname(TOOL)
    loader_len = os.path.getsize(os.path.join(tool_dir, 'Minimon/LOADK.bin'))
    minimon_len = os.path.getsize(os.path.join(tool_dir, 'Minimon/MINIMONK.bin'))

    import mock_c167
    mock_c167.LOADER_LEN = loader_len
    mock_c167.MINIMON_LEN = minimon_len

    master, slave = pty.openpty()
    port_name = os.ttyname(slave)
    flash = build_flash()

    mock = MockC167(master, flash)
    t = threading.Thread(target=mock.run, daemon=True)
    t.start()

    ser = serial.Serial(port_name, 9600, timeout=3)  # PTY ignores baud

    print('=' * 62)
    print(' driving the real tool code against the mock')
    print('=' * 62)

    # --- BSL entry, exactly as RunFunc does it
    print('\n[1] autobaud')
    ser.write(b'\x00')
    ser.flush()
    b = ser.read(1)
    print('    variant byte: %s  %s' % (
        b.hex() if b else 'none',
        'OK' if b and b[0] == VARIANT_C167 else 'FAIL'))

    print('\n[2] loader upload')
    loader = open(os.path.join(tool_dir, 'Minimon/LOADK.bin'), 'rb').read()
    ok = tool.SendDatawEcho(ser, loader)
    ack = ser.read(1)
    print('    ack: %s  %s' % (
        ack.hex() if ack else 'none',
        'OK' if ack and ack[0] == tool.I_LOADER_STARTED else 'FAIL'))

    print('\n[3] minimon upload')
    core = open(os.path.join(tool_dir, 'Minimon/MINIMONK.bin'), 'rb').read()
    tool.SendDatawEcho(ser, core)
    ack = ser.read(1)
    print('    ack: %s  %s' % (
        ack.hex() if ack else 'none',
        'OK' if ack and ack[0] == tool.I_APPLICATION_STARTED else 'FAIL'))

    print('\n[4] TestComm')
    tool.TestComm(ser)

    print('\n[5] GetBlockAtAddress - the GS20 boot block at 0x080000')
    ok, data = tool.GetBlockAtAddress(ser, 0x080000, 0x40)
    if ok:
        got = bytes(data)
        print('    first 16: %s' % got[:16].hex(' '))
        expect = bytes(flash[0:len(got)])
        print('    expected: %s' % expect.hex(' '))
        vectors_ok = all(got[i] == 0xFA for i in (0, 4, 8, 0x0C))
        print('    0xFA vector check: %s' % ('PASS' if vectors_ok else 'FAIL'))
        print('    content match:     %s' % ('PASS' if got == expect else 'FAIL'))
    else:
        print('    read FAILED')

    print('\n[6] GetBlockAtAddress - calibration version string at 0x09FFC8')
    ok, data = tool.GetBlockAtAddress(ser, 0x09FFC8, 0x10)
    if ok:
        got = bytes(data)
        print('    raw:    %s' % got.hex(' '))
        print('    ascii:  %r' % got.decode('latin1'))
        print('    match:  %s' % ('PASS' if got == b'G2210_0090C0ER10' else 'FAIL'))
    else:
        print('    read FAILED')

    print('\n[7] GetBlockAtAddress - program region at 0x0A0000')
    ok, data = tool.GetBlockAtAddress(ser, 0x0A0000, 0x20)
    if ok:
        got = bytes(data)
        expect = bytes(flash[0x20000:0x20020])
        print('    first 16: %s' % got[:16].hex(' '))
        print('    match:    %s' % ('PASS' if got == expect else 'FAIL'))
    else:
        print('    read FAILED')

    ser.close()
    print('\n' + '=' * 62)


if __name__ == '__main__':
    main()
