# Offline tests

`mock_c167.py` pretends to be a C167 sitting in bootstrap mode on the other
end of a PTY: it answers the autobaud byte, takes the loader and monitor
uploads, and then serves the monitor command set (`TEST_COMM`, `READ_BLOCK`,
`GETCHECKSUM`, `WRITE_WORD`) out of a simulated 512 KB GS20 image.

`test_boottool.py` imports ME7BootTool and drives its real functions against
that mock, so the framing, echo handling, block checksums and address
arithmetic are all exercised without hardware.

```
python3 test/test_boottool.py
```

Checks the whole sequence and then reads the three GS20 regions
(boot 0x080000, calibration 0x090000, program 0x0A0000), comparing the bytes
against the simulated flash.

Note: a PTY rejects the non-standard 28800 baud on macOS, so the test opens
the port at 9600. Baud is meaningless over a PTY either way.
