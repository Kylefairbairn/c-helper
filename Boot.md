# Manual HTTP Netboot with TI U\-Boot and `uEnv.txt`

This guide explains how to safely test HTTP netbooting on a Texas Instruments board using U\-Boot\.

The process is split into two stages:

1. Test every command manually at the U\-Boot prompt\.
2. Move the working commands into `uEnv.txt`\.

The initial procedure only loads files into RAM\. It does not write to eMMC, NAND, SPI flash, or the saved U\-Boot environment\.

Do **not** run any of these commands during initial testing:

```text
saveenv
env save
mmc write
mmc erase
nand write
nand erase
sf write
sf erase
erase
```

A reboot or power cycle should discard temporary `setenv` changes\.

---

## Accessing the U\-Boot Prompt

The manual commands in this guide are entered at the **U\-Boot prompt**, not in a Linux shell\.

Use a serial terminal such as Minicom:

```bash
sudo minicom -D /dev/ttyUSB0 -b 115200
```

Start Minicom before powering on or rebooting the board\. When you see:

```text
Hit any key to stop autoboot:
```

press a key before the countdown ends\.

The U\-Boot prompt normally looks like:

```text
=>
```

Do not type the leading `=>`; enter only the command after it\.

A Linux shell normally looks like:

```text
root@board:~#
```

or:

```text
user@board:~$
```

If you are at a Linux shell, reboot and interrupt autoboot to return to U\-Boot\.

---

## Goal

The safest first test is:

- U\-Boot loads normally from SD card, eMMC, or another existing boot source\.
- The Linux kernel is downloaded over HTTP\.
- The device tree is downloaded over HTTP\.
- The root filesystem remains on the existing SD card or eMMC\.
- The board uses a manually assigned static IP address\.
- Nothing is written to permanent storage\.

---

## Example Network

|Device     |IP address     |
|-----------|---------------|
|HTTP server|`192.168.50.10`|
|TI board   |`192.168.50.20`|
|Netmask    |`255.255.255.0`|

Because the board and server are on the same subnet, a gateway is not required\.

---

## Example HTTP Server Layout

For a newer 64\-bit TI board:

```text
/var/www/html/netboot/
├── Image
└── k3-am625-sk.dtb
```

For an older 32\-bit TI board:

```text
/var/www/html/netboot/
├── zImage
└── am335x-boneblack.dtb
```

Optional initramfs:

```text
/var/www/html/netboot/
├── Image
├── k3-am625-sk.dtb
└── rootfs.cpio.gz
```

Verify the files from another computer:

```bash
curl -I http://192.168.50.10/netboot/Image
curl -I http://192.168.50.10/netboot/k3-am625-sk.dtb
```

Use plain HTTP for the first test\.

---

## Part 1: Inspect U\-Boot

At the U\-Boot prompt, run:

```text
version
help wget
help ping
help booti
help bootz
printenv
```

### Verify HTTP Support

```text
help wget
```

If U\-Boot reports:

```text
Unknown command 'wget'
```

then this U\-Boot build does not include HTTP download support\. Use TFTP temporarily or use a U\-Boot build with `wget` support\.

---

## Part 2: Inspect Ethernet

List Ethernet devices:

```text
eth list
```

Inspect the selected interface and MAC address:

```text
printenv ethact
printenv ethprime
printenv ethaddr
```

If necessary, temporarily select an interface:

```text
setenv ethact ethernet@8000000
```

Replace `ethernet@8000000` with the name shown by `eth list`\.

Do not permanently save a randomly generated MAC address if the board already has a factory\-programmed one\.

---

## Part 3: Set a Static IP

Because DHCP is unavailable, set the network configuration manually:

```text
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no
```

Verify it:

```text
printenv ipaddr
printenv serverip
printenv netmask
printenv ethaddr
printenv ethact
```

Expected values:

```text
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
```

Do not run `saveenv`\.

---

## Part 4: Test Connectivity

Ping the HTTP server:

```text
ping ${serverip}
```

Expected result:

```text
host 192.168.50.10 is alive
```

If ping fails, check:

- Ethernet link LEDs
- The selected U\-Boot Ethernet interface
- The board MAC address
- Switch VLAN and access\-port configuration
- Server firewall rules
- Server interface configuration
- IP addresses and netmask
- Physical cabling

Do not continue until ping works\.

---

## Part 5: Determine RAM Load Addresses

Do not guess addresses\. Inspect the values already provided by U\-Boot:

```text
printenv loadaddr
printenv fdtaddr
printenv rdaddr
printenv kernel_addr_r
printenv fdt_addr_r
printenv ramdisk_addr_r
```

### TI\-style variables

If these are populated:

```text
loadaddr
fdtaddr
rdaddr
```

use:

```text
setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
setenv initrd_addr ${rdaddr}
```

### Upstream\-style variables

If these are populated:

```text
kernel_addr_r
fdt_addr_r
ramdisk_addr_r
```

use:

```text
setenv kernel_addr ${kernel_addr_r}
setenv dtb_addr ${fdt_addr_r}
setenv initrd_addr ${ramdisk_addr_r}
```

Verify the selected addresses:

```text
echo Kernel address: ${kernel_addr}
echo DTB address: ${dtb_addr}
echo Initramfs address: ${initrd_addr}
```

Do not continue if the required values are empty\.

---

## Part 6: Test an HTTP Download

Start with the smaller DTB file\.

AM62x example:

```text
wget ${dtb_addr} ${serverip}:/netboot/k3-am625-sk.dtb
```

AM335x example:

```text
wget ${dtb_addr} ${serverip}:/netboot/am335x-boneblack.dtb
```

Some U\-Boot versions also support a full URL:

```text
wget ${dtb_addr} http://${serverip}/netboot/k3-am625-sk.dtb
```

Check the download:

```text
echo ${filesize}
md.b ${dtb_addr} 40
fdt addr ${dtb_addr}
fdt header
```

A valid DTB starts with this magic value:

```text
d0 0d fe ed
```

If validation fails, verify that the HTTP server did not return a `404` HTML page instead of the DTB\.

---

## Part 7: Download the Kernel

### ARM64 using `Image`

```text
wget ${kernel_addr} ${serverip}:/netboot/Image
echo Kernel size: ${filesize}
md.b ${kernel_addr} 40
```

### ARM32 using `zImage`

```text
wget ${kernel_addr} ${serverip}:/netboot/zImage
echo Kernel size: ${filesize}
```

---

## Part 8: Preserve the Existing Root Filesystem

For the first test, keep the root filesystem on SD card or eMMC\.

Inspect the current working boot configuration:

```text
printenv bootargs
printenv console
printenv optargs
printenv mmcroot
printenv mmcargs
printenv args_mmc
```

Common root devices include:

```text
/dev/mmcblk0p2
/dev/mmcblk1p2
```

Common console values include:

```text
ttyS0,115200n8
ttyS2,115200n8
ttyO0,115200n8
```

Reuse the values from the board’s known\-good local boot\.

Example only:

```text
setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"
```

If `${console}` is empty, set the correct console explicitly:

```text
setenv bootargs "console=ttyS2,115200n8 root=/dev/mmcblk0p2 rootwait rw"
```

Do not blindly copy that console value\.

---

## Part 9: Boot from RAM

### ARM64

```text
booti ${kernel_addr} - ${dtb_addr}
```

### ARM32

```text
bootz ${kernel_addr} - ${dtb_addr}
```

The `-` means no initramfs is supplied\.

---

## Minimal ARM64 Manual Test

```text
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}

wget ${kernel_addr} ${serverip}:/netboot/Image
wget ${dtb_addr} ${serverip}:/netboot/k3-am625-sk.dtb

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"

booti ${kernel_addr} - ${dtb_addr}
```

---

## Minimal ARM32 Manual Test

```text
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}

wget ${kernel_addr} ${serverip}:/netboot/zImage
wget ${dtb_addr} ${serverip}:/netboot/am335x-boneblack.dtb

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"

bootz ${kernel_addr} - ${dtb_addr}
```

---

## Optional Initramfs Boot

After kernel\-and\-DTB booting works:

```text
wget ${initrd_addr} ${serverip}:/netboot/rootfs.cpio.gz
setenv initrd_size ${filesize}
```

ARM64:

```text
booti ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}
```

ARM32:

```text
bootz ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}
```

Make sure the initramfs does not overlap the kernel or DTB in RAM\.

---

## Move the Working Commands into `uEnv.txt`

Only automate the process after the manual commands work\.

Back up the existing file:

```bash
cp uEnv.txt uEnv.txt.backup
```

Inspect how your TI U\-Boot environment imports `uEnv.txt`:

```text
printenv bootcmd
printenv uenvcmd
printenv importbootenv
printenv loadbootenv
```

Many TI environments execute `uenvcmd` after importing `uEnv.txt`\.

### Example ARM64 `uEnv.txt`

```ini
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no

kernel_file=/netboot/Image
fdt_file=/netboot/k3-am625-sk.dtb

http_get_kernel=wget ${loadaddr} ${serverip}:${kernel_file}
http_get_fdt=wget ${fdtaddr} ${serverip}:${fdt_file}
http_set_bootargs=setenv bootargs console=${console} root=/dev/mmcblk0p2 rootwait rw
http_boot=run http_get_kernel; run http_get_fdt; run http_set_bootargs; booti ${loadaddr} - ${fdtaddr}
uenvcmd=run http_boot
```

### Example ARM32 `uEnv.txt`

```ini
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no

kernel_file=/netboot/zImage
fdt_file=/netboot/am335x-boneblack.dtb

http_get_kernel=wget ${loadaddr} ${serverip}:${kernel_file}
http_get_fdt=wget ${fdtaddr} ${serverip}:${fdt_file}
http_set_bootargs=setenv bootargs console=${console} root=/dev/mmcblk0p2 rootwait rw
http_boot=run http_get_kernel; run http_get_fdt; run http_set_bootargs; bootz ${loadaddr} - ${fdtaddr}
uenvcmd=run http_boot
```

### Safer ARM64 `uEnv.txt` with Checks

```ini
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no

kernel_file=/netboot/Image
fdt_file=/netboot/k3-am625-sk.dtb

http_set_bootargs=setenv bootargs console=${console} root=/dev/mmcblk0p2 rootwait rw
http_boot=if ping ${serverip}; then if wget ${loadaddr} ${serverip}:${kernel_file}; then if wget ${fdtaddr} ${serverip}:${fdt_file}; then run http_set_bootargs; booti ${loadaddr} - ${fdtaddr}; fi; fi; fi
uenvcmd=run http_boot
```

For ARM32, replace:

```text
booti ${loadaddr} - ${fdtaddr}
```

with:

```text
bootz ${loadaddr} - ${fdtaddr}
```

---

## Recommended Fallback Strategy

Do not immediately replace the normal local boot path\.

Preferred behavior:

1. Attempt HTTP boot\.
2. If the server is unavailable, continue with the known\-good local boot\.
3. Keep serial\-console access available\.
4. Keep a known\-good SD card or boot partition available\.

Inspect the existing boot flow:

```text
printenv bootcmd
```

Copy the local fallback command from the board’s existing environment rather than guessing it\.

---

## Debugging Commands

### Network settings

```text
printenv ipaddr serverip netmask gatewayip ethaddr ethact
```

### Boot addresses

```text
printenv loadaddr fdtaddr rdaddr
printenv kernel_addr_r fdt_addr_r ramdisk_addr_r
```

### Boot configuration

```text
printenv bootargs
printenv bootcmd
printenv uenvcmd
printenv console
```

### Connectivity

```text
eth list
ping ${serverip}
```

### HTTP download

```text
wget ${loadaddr} ${serverip}:/netboot/Image
echo ${filesize}
md.b ${loadaddr} 40
```

### DTB validation

```text
fdt addr ${fdtaddr}
fdt header
```

---

## Common Failure Modes

### `wget` is unavailable

```text
Unknown command 'wget'
```

Use TFTP or a U\-Boot build with HTTP support\.

### Ping fails

Check `ethact`, link status, MAC address, VLAN configuration, firewall rules, subnet settings, and cabling\.

### HTTP download fails

Verify the URL from another computer:

```bash
curl -v http://192.168.50.10/netboot/Image
```

Check port 80, file permissions, redirects, firewall rules, and whether HTTPS was used accidentally\.

### `fdt header` fails

Inspect memory:

```text
md.b ${dtb_addr} 40
```

A valid DTB begins with:

```text
d0 0d fe ed
```

### Kernel cannot mount root

Typical errors:

```text
VFS: Cannot open root device
```

```text
Kernel panic - not syncing: VFS: Unable to mount root fs
```

Check the root partition, `rootwait`, built\-in storage/filesystem drivers, and kernel/rootfs compatibility\.

### No Linux console output

Check the console device, baud rate, boot arguments, and DTB\. Reuse the values from a known\-good local boot\.

### Memory overlap

Use U\-Boot’s existing `loadaddr`, `fdtaddr`, `rdaddr`, `kernel_addr_r`, `fdt_addr_r`, and `ramdisk_addr_r` values instead of inventing addresses\.

---

## Safety Checklist

- [ ] Serial console access works\.
- [ ] Autoboot can be interrupted\.
- [ ] A known\-good local boot method is available\.
- [ ] `wget` exists in U\-Boot\.
- [ ] `ping ${serverip}` succeeds\.
- [ ] The correct Ethernet interface is selected\.
- [ ] A valid MAC address exists\.
- [ ] The kernel downloads successfully\.
- [ ] The DTB downloads successfully\.
- [ ] `fdt header` validates the DTB\.
- [ ] Kernel and DTB addresses do not overlap\.
- [ ] The correct console value is known\.
- [ ] The correct root partition is known\.
- [ ] Manual `booti` or `bootz` succeeds\.
- [ ] No flash\-write or environment\-save commands were used\.
- [ ] The original `uEnv.txt` is backed up\.
- [ ] A local boot fallback has been tested\.

---

## Information to Capture

```text
version
bdinfo
eth list
help wget
help booti
help bootz
printenv
```

At minimum:

```text
printenv loadaddr
printenv fdtaddr
printenv rdaddr
printenv kernel_addr_r
printenv fdt_addr_r
printenv ramdisk_addr_r
printenv console
printenv bootargs
printenv bootcmd
printenv uenvcmd
printenv ethaddr
printenv ethact
```

Record:

```text
TI board model:
Processor:
U-Boot version:
Kernel filename:
DTB filename:
Root filesystem location:
Root partition:
Console device:
HTTP server IP:
Board static IP:
```

---

## Recommended Bring\-Up Sequence

1. Boot the board normally\.
2. Confirm serial\-console access\.
3. Stop at the U\-Boot prompt\.
4. Assign a static IP address\.
5. Ping the HTTP server\.
6. Download only the DTB\.
7. Validate the DTB with `fdt header`\.
8. Download the kernel\.
9. Boot the HTTP kernel with the existing local root filesystem\.
10. Repeat the manual boot several times\.
11. Add the tested c
