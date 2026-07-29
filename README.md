# bc250 core unlock

enables the 2 disabled cpu cores. 6c/12t -> 8c/16t.

tested on bios 3.0, kernel 6.18.40.

## usage

```
sudo systemctl stop cyan-skillfish-governor-smu
sudo chmod +x ./bc250-unlock-cores.py
sudo ./bc250-unlock-cores.py
sudo reboot
```

survives warm reboots. a full power off clears it, so redo after every cold boot.

## how it works

smu queue 3 msg 0x98 is ungated and writes the fixed value 0x00ff to any smn address
passed as its argument. only validation is addr != 0.

core presence mask is at smn 0x0115a870, reads 0x77 (6 of 8 cores). writing 0xff there
makes agesa enumerate 8 cores on the next boot, build a 16 entry madt, and the psp release
all of them.

the host cannot write that register itself. writes through the pci smn window (0xb8/0xbc)
do not stick. the smu is a more privileged smn requester.

patching the madt alone does not work either. cores get advertised but the psp never
released them, so all 4 init/sipi time out.

## results

```
cpu(s): 16, cores per socket 8, threads per core 2
smp: brought up 1 node, 16 cpus, no timeouts
bogomips 76690 -> 102245 (16/12)
apicid 0..15 contiguous, 6/7/14/15 absent before
madt: 16 lapic entries, all enabled
idle wall power unchanged, 72.68w vs 72.43w
16 thread load: 44c -> 55c, no mces
```

reproduced 3/3, including twice from a cold boot.

## caveats

volatile, redo per cold boot.

no idea why these 2 cores are disabled (ps5 oberon die). 3 boots and a short load test
prove nothing. run mprime or stress-ng for a few hours and check dmesg for mces before
relying on them.

0x98 writes to any smn address with no bounds check. a wrong address hangs or corrupts the
board. bc250-unlock-cores.py only ever targets 0x0115a870 and checks the mask reads 0x77
first.

one run came up with no ethernet. that nic is flaky on this kernel anyway, later runs were
fine.

only tested on bios 3.0. the 0.58.7.1 smu build (bios 5) differs in one dispatch slot, so
0x98 is probably the same there, untested.

## known issue: gpu clock reporting

after the unlock, pp_dpm_sclk and hwmon freq1_input report nonsense. fluctuates, roughly
18 to 60 mhz instead of 500 at idle.

the gpu itself is fine:

```
smu's own clock getters are correct and stable: dom00 500, dom19 1500, fclk 1200, uclk 875
llama-bench gemma 12b q4_0 tg32: 39.73 t/s at 8 cores, 39.71 t/s at 6 cores
no mces, no smu errors, gpu voltage normal (924 mv)
```

so it is amdgpu's derived value that is wrong, not the hardware and not the smu. cosmetic.

pinned reads from old and new cores are both wrong (cpu0 19mhz, cpu14 23mhz) so it is not
per core. tsc is fine (3194 mhz, no sync warnings). cause not identified yet.

## bc250-dfps.py

df/memory p-state, same mailbox. about 22w idle between top and bottom state.

```
sudo ./bc250-dfps.py table
sudo ./bc250-dfps.py set 1
```

```
idx  fclk  uclk  memclk  gbps
0/1   250   225     450   3.6
 2    750   425     850   6.8
 3   1200   875    1750  14.0   default
```

uclk = memclk/2, memclk*8 = gbps. same thing cyan-skillfish-governor does through
set_perfprofileindex.

## license

MIT
