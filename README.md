# bc250 core unlock

enables the 2 disabled cpu cores. 6c/12t -> 8c/16t.
should work on all BIOS versions.

## usage

```
sudo su
systemctl stop cyan-skillfish-governor-smu
chmod +x ./bc250-unlock-cores.py
./bc250-unlock-cores.py
reboot
```

survives warm reboots. a full power off clears it, so redo after every cold boot.


## caveats

cores might have been disabled for a reason.
run mprime or stress-ng for a few hours and check dmesg for MCEs before relying on them.
we also cannot _fully_ rule out defects and incorrect results that may only come up in
specific circumstances (specific instructions, high temperature, ...).  
  
that being said, the fact that the core presence mask on many different boards is almost
always 0x77 (0b01110111, core 3 of each ccx, symmetric) suggests that quite likely cores
are usually disabled as a product configuration choice rather than due to actual defects
(we would expect defects to be somewhat more evenly distributed between cores).  
  
**not all boards read 0x77.** the script refuses anything else by default, as a different
mask strongly suggests an actual harvest that purposefully skipped defective cores.
call `./bc250-unlock-cores.py -f` to proceed anyway at your own risk.

the primitive we currently rely on can only enable _all_ cores, so if either of the 2 disabled cores
cores is defective, you are currently out of luck, sorry about this ;-;
  
volatile, redo per cold boot.

## making this permanent

once you are confident that the 2 new cores work correctly, you may want to automatically
enable the cores on cold boot.

you can achieve this using RescueMei's BIOS mod at https://github.com/RescueMei/BC250-DXE-SMU-Core-Unlock  
(by placing this in a BIOS DXE driver, it loads much more quickly than a full linux reboot or even a small EFI shim)

## ACPI fixes for 8 cores

you can find a version of the ACPI table fixes for 8 cores here: https://github.com/mendesrr/bc250-acpi-fix-updated-8c.git

## known issue: GPU clock reporting

after the unlock, pp_dpm_sclk and hwmon freq1_input report nonsense. fluctuates, roughly
18 to 60 MHz instead of 500 at idle.

SMU's own clock getters seem correct and stable: dom00 500, dom19 1500, fclk 1200, uclk 875
so amdgpu's derived value may be broken for some reason.

pinned reads from old and new cores are both wrong (CPU0 19MHz, CPU14 23MHz) so it is not
per core. TSC is fine (3194 MHz, no sync warnings). cause not identified yet.
very likely software, probably repairable with linux kernel changes.


## writeup

core presence mask is at SMN register 0x5a870 (0x115A870 in the SMU address space).  
we can infer this from several CPU interrupt-related functions which validate whether cores are enabled or not by reading that register.  
it normally reads 0x77 = 0b01110111, whereas writes from the CPU sides are silently dropped.  
we know that the silicon should physically have 8 cores, and the fact that the mask on many different boards is very frequently 0x77 suggests that often cores may have been disabled for a product configuration choice rather than actual defects (we would expect defects to be somewhat more evenly distributed between cores).  
  
while analysing various SMU message handlers (mostly to try and understand why sleep doesn't seem work xP) I accidentally stumbled upon queue 3's message 0x98 handler, which has the following pseudocode:  
```C

void msg_q3_98(pmfw_queue_t queue) {
	int arg = pmfw_queue_read_arg(queue);
	if (arg != 0) {
		smn_window_write(0, arg, 0xff, 2); /* hi=0, lo=arg, val=0xFF, width_sel=2 */
		smn_window_read(0, arg, 2); /* res discarded */
	} else
		panic_lock_HANGS();
	pmfw_queue_write_status(queue, 1);
}

void smn_window_write(u32 hi, u32 lo, u32 val, int width_sel) {
	u32 saved_ps = rsil(2);

	/* save address in a scratch struct in SRAM (nothing in SMU firm seems to read this ?) */
	*(u32 *)(0xB100 + 0) = lo;
	*(u32 *)(0xB100 + 4) = hi;
	dcache_wbinv_lines(0xB100, 8);

	/* map 1 MB window containing target SMN addr */
	memw();
	u32 page = ((u64)hi << 32 | lo) >> 20;
	io_write16(0x03220000 + 0x1C * 2, page & 0xFFFF);
	memw();

	/* store val through the mapped SMN window */
	void *ptr = (void *)(0x01000000 + (0x1C << 20) + (lo & 0x000FFFFF));
	if (width_sel == 0)
		io_write8(ptr, val);
	else if (width_sel == 1)
		io_write16(ptr, val);
	else if (width_sel == 2)
		io_write32(ptr, val);
	else /* invalid width */                                
		error_HANGS(...);

	wsr(0, saved_ps);
}
```

as you can see, nothing ever validates the SMN address passed as argument! the only constraint is for arg to be != 0.  
this weird and (almost perfectly) broken message handler doesn't really seem to exist on any other platform's SMU firmware (as far as I can tell) and strongly smells like some kind of debugging leftover.  
  
anyway, while it's not quite an arbitrary write, it does allow us to store 0x000000ff at any given address in SMN from the SMU side.  
which works out nicely for our core presence mask register, since 0x000000ff corresponds to the mask with all cores being enabled!  
  
I quickly threw around a small test script using the existing SMU interfacing code from https://github.com/bc250-collective/bc250_smu_oc/tree/main/bc250_smu (kudos to mrfrakes and shinf1x), fired it on the BC-250, and ...whoa! writes to the core presence mask actually seem to stick when coming from the SMU!  
but... unfortunately nothing (nothing ever happens).  
this is when I got extremely lucky. after working on some unrelated experiments I eventually rebooted the card without much thought.  
surprisingly, on the next startup, I was greeted by 8 cores! success!  

## license

MIT
