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
idle wall power nearly unchanged, 72.68w vs 72.43w
```

## caveats

**not all boards read 0x77.** the script only acts on exactly 0x77 and refuses anything
else, because a different mask probably means a different (or real) harvest. 0x77 is
0b01110111, core 3 of each ccx, symmetric, which looks like a product config choice. an
asymmetric mask looks more like actual defect binning, and the primitive always writes
0x00ff regardless, so blanket-enabling there is a worse bet. left alone on purpose.

volatile, redo per cold boot.

no idea why these 2 cores are disabled (ps5 oberon die). 3 boots and a short load test
prove nothing. run mprime or stress-ng for a few hours and check dmesg for mces before
relying on them.

0x98 writes to any smn address with no bounds check. a wrong address may hang or damage the
board. bc250-unlock-cores.py only ever targets 0x0115a870 and checks the mask reads 0x77
first.

## known issue: gpu clock reporting

after the unlock, pp_dpm_sclk and hwmon freq1_input report nonsense. fluctuates, roughly
18 to 60 mhz instead of 500 at idle.

smu's own clock getters seem correct and stable: dom00 500, dom19 1500, fclk 1200, uclk 875
so amdgpu's derived value may be broken for some reason.

pinned reads from old and new cores are both wrong (cpu0 19mhz, cpu14 23mhz) so it is not
per core. tsc is fine (3194 mhz, no sync warnings). cause not identified yet.

## license

MIT
