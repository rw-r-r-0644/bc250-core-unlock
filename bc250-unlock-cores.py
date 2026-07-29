#!/usr/bin/env python3
"""Enable the BC-250's two disabled CPU cores. 6c/12t -> 8c/16t.

Writes the core presence mask (SMN 0x0115A870) from 0x77 to 0xFF using queue 3 message
0x98, an ungated SMU-privileged SMN write. Takes effect on the next reboot: AGESA then
enumerates 8 cores and the PSP releases all of them.

  sudo systemctl stop cyan-skillfish-governor-smu
  sudo ./bc250-unlock-cores.py
  sudo reboot

The mask is NOT host-writable, which is why this needs the SMU. Volatile - a cold power
cycle very likely reverts it (untested), so this may need repeating per cold boot.

WARNING: these cores may have been disabled for a reason. Stress-test before trusting them.
"""
import os
import struct
import sys
import time

MASK_REG = 0x0115A870
MSG_WRITE_FF = 0x98
Q3_CMD, Q3_RSP, Q3_ARG = 0x03B10A20, 0x03B10A80, 0x03B10A88
DONE = {0x01, 0xFF, 0xFE, 0xFD, 0xFC}

if os.geteuid() != 0:
    sys.exit("needs root")

fd = os.open("/sys/bus/pci/devices/0000:00:00.0/config", os.O_RDWR)


def smn_rd(reg):
    os.pwrite(fd, struct.pack("<I", reg), 0xB8)
    return struct.unpack("<I", os.pread(fd, 4, 0xBC))[0]


def smu_rd(reg):
    os.pwrite(fd, struct.pack("<I", reg), 0xB8)
    return struct.unpack("<I", os.pread(fd, 4, 0xBC))[0]


def smu_wr(reg, val):
    os.pwrite(fd, struct.pack("<I", reg), 0xB8)
    os.pwrite(fd, struct.pack("<I", val), 0xBC)


def send(msg, arg, budget=5.0):
    end = time.monotonic() + budget
    while smu_rd(Q3_RSP) not in DONE and time.monotonic() < end:
        time.sleep(0.002)
    smu_wr(Q3_RSP, 0)
    smu_wr(Q3_ARG, arg)
    smu_wr(Q3_ARG + 4, 0)
    smu_wr(Q3_CMD, msg)
    end = time.monotonic() + budget
    while time.monotonic() < end:
        st = smu_rd(Q3_RSP)
        if st in DONE:
            return st
        time.sleep(0.002)
    raise RuntimeError("mailbox timeout - abort, do not retry")


try:
    before = smn_rd(MASK_REG)
    print("core presence mask: 0x%08X" % before)
    if before & 0xFF == 0xFF:
        print("already 0xFF - reboot to pick up all 8 cores")
        raise SystemExit(0)
    if before & 0xFF != 0x77:
        sys.exit("unexpected mask 0x%02X, expected 0x77 - aborting" % (before & 0xFF))

    st = send(MSG_WRITE_FF, MASK_REG)
    if st != 0x01:
        sys.exit("Q3 0x98 returned 0x%02X - is the governor stopped?" % st)
    time.sleep(0.2)

    after = smn_rd(MASK_REG)
    print("after write        : 0x%08X" % after)
    if after & 0xFF != 0xFF:
        sys.exit("mask did not take")
    print("\nOK. Reboot to bring up all 8 cores (16 threads).")
finally:
    os.close(fd)
