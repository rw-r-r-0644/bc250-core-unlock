#!/usr/bin/env python3
"""bc250-dfps — read/set the BC-250 DF (fabric + memory) P-state.

Same mailbox as bc250-collective/bc250_smu_oc: AMD SMN index/data window at PCI config
0xB8/0xBC on 0000:00:00.0. Self-contained so you can just drop it on the box.

  sudo systemctl stop cyan-skillfish-governor-smu    # it owns the same config fd
  sudo ./bc250-dfps.py status
  sudo ./bc250-dfps.py set 1
  sudo ./bc250-dfps.py domains

Queue 3 only — queue 0 belongs to amdgpu. Volatile: resets to 3 on reboot.
"""
import os
import struct
import sys
import time

BDF = "0000:00:00.0"
IDX, DAT = 0xB8, 0xBC
Q3_CMD, Q3_RSP, Q3_ARG = 0x03B10A20, 0x03B10A80, 0x03B10A88

MSG_SET_DFPS, MSG_GET_DFPS, MSG_GET_DOMAIN = 0x1E, 0x46, 0x11
MSG_FCLK, MSG_UCLK, MSG_DERIVED = 0x38, 0x39, 0x3A

DOMAINS = {0x0E: "FCLK  (fabric)", 0x0F: "UCLK  ch0", 0x10: "derived ch0",
           0x11: "UCLK  ch1", 0x12: "derived ch1", 0x19: "GFX?"}
DONE = {0x01, 0xFF, 0xFE, 0xFD, 0xFC}
OK, FAIL = 0x01, 0xFF


class Smu:
    def __init__(self):
        self.fd = os.open("/sys/bus/pci/devices/%s/config" % BDF, os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def _rd(self, reg):
        os.pwrite(self.fd, struct.pack("<I", reg), IDX)
        return struct.unpack("<I", os.pread(self.fd, 4, DAT))[0]

    def _wr(self, reg, val):
        os.pwrite(self.fd, struct.pack("<I", reg), IDX)
        os.pwrite(self.fd, struct.pack("<I", val), DAT)

    def send(self, msg, arg=0, budget=5.0):
        """Real timed wait. Status 0x00 means TIMED OUT, not success -- if you keep
        sending after one you desync the mailbox and wedge the SMU (cold boot to fix)."""
        end = time.monotonic() + budget
        while self._rd(Q3_RSP) not in DONE and time.monotonic() < end:
            time.sleep(0.002)
        if self._rd(Q3_RSP) not in DONE:
            raise RuntimeError("mailbox busy before send; is the governor stopped?")
        self._wr(Q3_RSP, 0)
        self._wr(Q3_ARG, arg)
        self._wr(Q3_ARG + 4, 0)
        self._wr(Q3_CMD, msg)
        end = time.monotonic() + budget
        while time.monotonic() < end:
            st = self._rd(Q3_RSP)
            if st in DONE:
                return st, self._rd(Q3_ARG)
            time.sleep(0.002)
        raise RuntimeError("TIMEOUT on msg 0x%02X arg=0x%X -- ABORT, do not send more"
                           % (msg, arg))


def table(smu):
    """Walk the DF P-state table until the firmware rejects the index."""
    rows = []
    for i in range(8):
        st, fclk = smu.send(MSG_FCLK, i)
        if st != OK:
            break
        uclk = smu.send(MSG_UCLK, i)[1]
        derived = smu.send(MSG_DERIVED, i)[1]
        rows.append((i, fclk, uclk, derived, uclk * 2))
    return rows


def cmd_status(smu):
    cur = smu.send(MSG_GET_DFPS)[1]
    fclk = smu.send(MSG_GET_DOMAIN, 0x0E)[1]
    uclk = smu.send(MSG_GET_DOMAIN, 0x0F)[1]
    print("DfPstate %d   FCLK %d MHz   UCLK %d MHz   MEMCLK %d MHz (%.1f Gbps)"
          % (cur, fclk, uclk, uclk * 2, uclk * 2 * 8 / 1000.0))


def cmd_table(smu):
    cur = smu.send(MSG_GET_DFPS)[1]
    print("idx   FCLK  UCLK  derived  MEMCLK   Gbps")
    for i, f, u, d, m in table(smu):
        print("%s%d    %5d %5d %8d %7d %6.1f"
              % ("*" if i == cur else " ", i, f, u, d, m, m * 8 / 1000.0))
    print("\n* = current. Lower is slower and cooler; 1 is the practical floor.")


def cmd_domains(smu):
    print("dom   MHz    name")
    for d in range(0x00, 0x1B):
        st, v = smu.send(MSG_GET_DOMAIN, d)
        if st == OK and v:
            print("0x%02X  %5d  %s" % (d, v, DOMAINS.get(d, "")))


def cmd_set(smu, want):
    rows = table(smu)
    if want not in [r[0] for r in rows]:
        sys.exit("no such DfPstate %d (valid: %s)" % (want, [r[0] for r in rows]))
    before = smu.send(MSG_GET_DFPS)[1]
    st, _ = smu.send(MSG_SET_DFPS, want)
    if st != OK:
        sys.exit("SetDfPstate rejected, status 0x%02X" % st)
    # The switch is asynchronous: reading 0x46 immediately returns the OLD state.
    time.sleep(1.0)
    now = smu.send(MSG_GET_DFPS)[1]
    print("DfPstate %d -> %d" % (before, now))
    cmd_status(smu)
    if now != want:
        print("warning: read-back is %d, not %d" % (now, want))


def main():
    if os.geteuid() != 0:
        sys.exit("needs root (raw PCI config access)")
    args = sys.argv[1:] or ["status"]
    smu = Smu()
    try:
        if args[0] == "status":
            cmd_status(smu)
        elif args[0] == "table":
            cmd_table(smu)
        elif args[0] == "domains":
            cmd_domains(smu)
        elif args[0] == "set" and len(args) == 2:
            cmd_set(smu, int(args[1]))
        else:
            sys.exit(__doc__)
    finally:
        smu.close()


if __name__ == "__main__":
    main()
