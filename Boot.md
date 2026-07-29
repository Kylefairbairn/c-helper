Manual HTTP Netboot with TI U-Boot and uEnv.txt

This guide explains how to safely test HTTP netbooting on a Texas Instruments board using U-Boot.

The process is intentionally split into two stages:

1. Test every command manually at the U-Boot prompt.
2. Move the working commands into uEnv.txt.

The initial procedure does not write to eMMC, NAND, SPI flash, or the saved U-Boot environment.

As long as you do not run commands such as the following, your changes should remain temporary:

saveenv
env save
mmc write
nand write
sf write
erase

A reboot or power cycle should return the board to its previous configuration.

⸻

Goal

The safest initial setup is:

* U-Boot loads normally from SD card, eMMC, or another existing boot source.
* The Linux kernel is downloaded over HTTP.
* The device tree is downloaded over HTTP.
* The root filesystem remains on the existing SD card or eMMC.
* The board uses a manually assigned static IP address.
* Nothing is written to permanent storage.

Once this works, the root filesystem can later be moved to NFS, initramfs, or another network-based solution.

⸻

Example Network

This guide uses the following example network:

Device	IP address
HTTP server	192.168.50.10
TI board	192.168.50.20
Netmask	255.255.255.0

The board and HTTP server are on the same subnet, so a gateway is not required.

Adjust these addresses for your environment.

⸻

Example HTTP Server Layout

Place the boot files in a directory served by your HTTP server.

For a newer 64-bit TI board:

/var/www/html/netboot/
├── Image
└── k3-am625-sk.dtb

For an older 32-bit TI board:

/var/www/html/netboot/
├── zImage
└── am335x-boneblack.dtb

An optional initramfs might also be included:

/var/www/html/netboot/
├── Image
├── k3-am625-sk.dtb
└── rootfs.cpio.gz

Verify the files from another computer:

curl -I http://192.168.50.10/netboot/Image
curl -I http://192.168.50.10/netboot/k3-am625-sk.dtb

Use plain HTTP for the first test.

Do not begin with HTTPS unless the U-Boot build is known to support it.

⸻

Part 1: Inspect the U-Boot Environment

Connect to the board through its serial console and interrupt autoboot.

Example:

Hit any key to stop autoboot:

At the U-Boot prompt, inspect the version and available commands:

version
help wget
help ping
help booti
help bootz
printenv

Verify HTTP Support

Run:

help wget

If U-Boot responds with information about wget, HTTP download support is available.

If U-Boot responds with:

Unknown command 'wget'

the installed U-Boot build does not include HTTP download support.

In that case, use one of the following:

* TFTP for initial network boot testing
* A TI U-Boot image with wget support
* A custom U-Boot build with HTTP support enabled

Do not replace or reflash U-Boot until the rest of the boot process has been tested.

⸻

Part 2: Inspect the Ethernet Interface

List the available Ethernet devices:

eth list

Inspect the active Ethernet interface:

printenv ethact
printenv ethprime

Inspect the board’s Ethernet MAC address:

printenv ethaddr

A valid MAC address is normally required.

Do not permanently save a randomly invented MAC address if the board already has a factory-programmed address.

If necessary, temporarily select an Ethernet device:

setenv ethact ethernet@8000000

Replace ethernet@8000000 with the device name shown by:

eth list

⸻

Part 3: Configure a Static IP Address

Because DHCP is not available, manually configure the board’s network settings.

setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0

Optionally prevent an automatic network load:

setenv autoload no

Verify the settings:

printenv ipaddr
printenv serverip
printenv netmask
printenv ethaddr
printenv ethact

Expected values:

ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0

Do not run:

saveenv

The settings should remain temporary.

⸻

Part 4: Test Network Connectivity

Ping the HTTP server:

ping ${serverip}

Expected result:

host 192.168.50.10 is alive

Do not continue until the ping works.

If the ping fails, check:

* Ethernet link LEDs
* The selected U-Boot Ethernet interface
* The board’s MAC address
* Switch VLAN configuration
* Switch access-port configuration
* Server firewall rules
* Server network interface configuration
* Board and server subnet configuration
* Physical cabling

For a directly connected isolated network, both devices should be in the same subnet.

⸻

Part 5: Determine Safe RAM Load Addresses

Do not guess RAM addresses unless absolutely necessary.

Inspect the addresses already provided by the TI U-Boot environment:

printenv loadaddr
printenv fdtaddr
printenv rdaddr

Also check the upstream-style variable names:

printenv kernel_addr_r
printenv fdt_addr_r
printenv ramdisk_addr_r

TI environments often use:

loadaddr
fdtaddr
rdaddr

Other U-Boot environments often use:

kernel_addr_r
fdt_addr_r
ramdisk_addr_r

Print all likely variables at once:

printenv loadaddr fdtaddr rdaddr kernel_addr_r fdt_addr_r ramdisk_addr_r

Option A: TI-Style Variables

If these exist:

loadaddr
fdtaddr
rdaddr

use:

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
setenv initrd_addr ${rdaddr}

Option B: Upstream-Style Variables

If these exist:

kernel_addr_r
fdt_addr_r
ramdisk_addr_r

use:

setenv kernel_addr ${kernel_addr_r}
setenv dtb_addr ${fdt_addr_r}
setenv initrd_addr ${ramdisk_addr_r}

Verify the selected addresses:

echo Kernel address: ${kernel_addr}
echo DTB address: ${dtb_addr}
echo Initramfs address: ${initrd_addr}

Do not continue if the required values are empty.

⸻

Part 6: Test an HTTP Download

Start with the device tree because it is relatively small.

Example for an AM62x board:

wget ${dtb_addr} ${serverip}:/netboot/k3-am625-sk.dtb

Example for an AM335x board:

wget ${dtb_addr} ${serverip}:/netboot/am335x-boneblack.dtb

Some U-Boot versions may support a full URL:

wget ${dtb_addr} http://${serverip}/netboot/k3-am625-sk.dtb

The more widely compatible form is usually:

wget ${dtb_addr} ${serverip}:/netboot/k3-am625-sk.dtb

After the download, inspect the size:

echo ${filesize}

Inspect the first bytes in memory:

md.b ${dtb_addr} 40

Validate the device tree:

fdt addr ${dtb_addr}
fdt header

If fdt header reports a valid flattened device tree, the download worked.

If it fails, confirm that the HTTP server did not return an HTML error page instead of the DTB.

For example, verify that the file path is correct and that the server is not returning a 404 Not Found response.

⸻

Part 7: Download the Kernel

ARM64 Boards Using Image

Boards such as AM62x, AM64x, AM65x, and some Jacinto platforms commonly use an uncompressed ARM64 kernel named Image.

Download it:

wget ${kernel_addr} ${serverip}:/netboot/Image

Check the downloaded size:

echo Kernel size: ${filesize}

Inspect the beginning of the loaded data:

md.b ${kernel_addr} 40

ARM32 Boards Using zImage

Boards such as AM335x and some older TI processors commonly use zImage.

Download it:

wget ${kernel_addr} ${serverip}:/netboot/zImage

Check the downloaded size:

echo Kernel size: ${filesize}

⸻

Part 8: Preserve the Existing Root Filesystem

For the first test, keep the root filesystem on the SD card or eMMC.

Only the kernel and device tree should come from HTTP.

Before changing the kernel command line, inspect the current working boot configuration:

printenv bootargs
printenv console
printenv optargs
printenv mmcroot
printenv mmcargs
printenv args_mmc

The exact root device and console device depend on the board.

Common examples include:

/dev/mmcblk0p2
/dev/mmcblk1p2

Common console values include:

ttyS0,115200n8
ttyS2,115200n8
ttyO0,115200n8

Use the console and root-device values from the board’s existing successful local boot.

Example Boot Arguments

Example only:

setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"

If ${console} is empty, set the correct console explicitly.

Example:

setenv bootargs "console=ttyS2,115200n8 root=/dev/mmcblk0p2 rootwait rw"

Do not blindly copy this console value. It must match the TI board.

Verify the final command line:

printenv bootargs

⸻

Part 9: Boot Manually from RAM

ARM64 with Image

Boot without an initramfs:

booti ${kernel_addr} - ${dtb_addr}

The - means no initramfs is being supplied.

ARM32 with zImage

Boot without an initramfs:

bootz ${kernel_addr} - ${dtb_addr}

If Linux boots, then the following have been validated:

* U-Boot Ethernet support
* Static IP configuration
* Switch and VLAN configuration
* HTTP server access
* Kernel download
* Device-tree download
* RAM load addresses
* Kernel command line
* Existing root filesystem

⸻

Minimal ARM64 Manual Test

Adjust the board-specific DTB filename, root device, and console.

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

⸻

Minimal ARM32 Manual Test

Adjust the board-specific DTB filename, root device, and console.

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

⸻

Part 10: Optional Initramfs Boot

An initramfs can be downloaded over HTTP after kernel-and-DTB booting works.

Do not introduce it during the initial test unless required.

Download the initramfs:

wget ${initrd_addr} ${serverip}:/netboot/rootfs.cpio.gz

Save its size before downloading another file:

setenv initrd_size ${filesize}

ARM64 with Initramfs

booti ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}

ARM32 with Initramfs

bootz ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}

The initramfs load address must not overlap the kernel or device tree.

Use the RAM addresses already provided by the TI U-Boot environment.

⸻

Part 11: Move the Working Commands into uEnv.txt

Only create the automated uEnv.txt configuration after the commands work manually.

Before editing uEnv.txt, save a copy of the current file:

cp uEnv.txt uEnv.txt.backup

The exact way TI imports and runs uEnv.txt varies by SDK and U-Boot version.

Inspect the current boot flow:

printenv bootcmd
printenv uenvcmd
printenv importbootenv
printenv loadbootenv

Many TI environments automatically run uenvcmd after importing uEnv.txt.

⸻

Example ARM64 uEnv.txt

This example:

* Assigns a static IP
* Downloads Image
* Downloads the DTB
* Uses an existing local root filesystem
* Boots with booti

Adjust the board-specific filenames and boot arguments.

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

⸻

Example ARM32 uEnv.txt

This example uses zImage and bootz.

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

⸻

Safer uEnv.txt with Download Checks

A safer automated configuration checks that the server responds and that both downloads succeed before calling booti.

ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no
kernel_file=/netboot/Image
fdt_file=/netboot/k3-am625-sk.dtb
http_set_bootargs=setenv bootargs console=${console} root=/dev/mmcblk0p2 rootwait rw
http_boot=if ping ${serverip}; then if wget ${loadaddr} ${serverip}:${kernel_file}; then if wget ${fdtaddr} ${serverip}:${fdt_file}; then run http_set_bootargs; booti ${loadaddr} - ${fdtaddr}; fi; fi; fi
uenvcmd=run http_boot

For ARM32, replace the final command:

booti ${loadaddr} - ${fdtaddr}

with:

bootz ${loadaddr} - ${fdtaddr}

⸻

Recommended Fallback Strategy

Do not immediately replace the normal local boot path.

The preferred behavior is:

1. Attempt the HTTP boot.
2. If the HTTP server is unavailable, allow normal local boot to continue.
3. Keep serial-console access available.
4. Keep a known-good SD card or boot partition available.

Whether normal boot continues after uenvcmd fails depends on the TI U-Boot boot script.

Inspect:

printenv bootcmd

If necessary, explicitly call the board’s known-good local boot command after the HTTP attempt.

The local fallback command varies significantly between TI SDK versions, so it should be copied from the board’s existing environment rather than guessed.

⸻

Debugging Commands

Show Current Network Settings

printenv ipaddr serverip netmask gatewayip ethaddr ethact

Show Boot Addresses

printenv loadaddr fdtaddr rdaddr
printenv kernel_addr_r fdt_addr_r ramdisk_addr_r

Show Boot Configuration

printenv bootargs
printenv bootcmd
printenv uenvcmd
printenv console

List Ethernet Devices

eth list

Test the Server

ping ${serverip}

Download a File

wget ${loadaddr} ${serverip}:/netboot/Image

Show Downloaded File Size

echo ${filesize}

Inspect RAM

md.b ${loadaddr} 40

Validate a Device Tree

fdt addr ${fdtaddr}
fdt header

⸻

Common Failure Modes

wget Is Not Available

Symptom:

Unknown command 'wget'

Cause:

The U-Boot build does not include HTTP download support.

Possible solutions:

* Use TFTP
* Install a TI U-Boot build containing wget
* Rebuild U-Boot with the appropriate network and wget support

⸻

Ping Fails

Possible causes:

* Wrong ethact
* No Ethernet link
* Invalid or missing MAC address
* Incorrect VLAN configuration
* Board port is a tagged trunk when U-Boot expects untagged traffic
* Server firewall
* Incorrect subnet
* Incorrect static IP address
* Incorrect server address

Resolve ping failures before debugging HTTP.

⸻

HTTP Download Returns an Error

Possible causes:

* Incorrect URL or path
* HTTP server not listening on port 80
* File permissions
* Server firewall
* Server returning a redirect
* U-Boot HTTP implementation not supporting the redirect
* HTTPS used instead of HTTP

Test from another computer:

curl -v http://192.168.50.10/netboot/Image

⸻

fdt header Fails

Possible causes:

* Wrong file downloaded
* HTTP server returned an HTML error page
* Incorrect load address
* Corrupted download
* DTB file is compressed
* Memory overlap

Inspect the memory:

md.b ${dtb_addr} 40

A valid DTB begins with the device-tree magic value:

d0 0d fe ed

⸻

Kernel Starts but Cannot Mount Root Filesystem

Typical messages include:

VFS: Cannot open root device

or:

Kernel panic - not syncing: VFS: Unable to mount root fs

Possible causes:

* Wrong /dev/mmcblkXpY value
* Missing storage driver in the kernel
* Root filesystem is on a different partition
* Missing rootwait
* Filesystem driver not built into the kernel
* Kernel and root filesystem are incompatible

Compare the HTTP-loaded kernel command line with the command line used during a successful local boot.

⸻

No Linux Console Output

Possible causes:

* Wrong console device
* Wrong baud rate
* Missing console argument
* Device-tree mismatch
* Kernel booted but is using another UART

Inspect the existing working U-Boot variables:

printenv console
printenv bootargs

Reuse the exact console setting from the known-good boot.

⸻

Kernel or DTB Memory Overlap

Symptoms can include:

* Random hangs
* Invalid device tree
* Kernel decompression failures
* Kernel image corruption

Use the board’s existing variables:

loadaddr
fdtaddr
rdaddr

or:

kernel_addr_r
fdt_addr_r
ramdisk_addr_r

Do not arbitrarily choose addresses without checking the board’s RAM map.

⸻

Safety Checklist

Before running the automated configuration, confirm all of the following:

* Serial console access works.
* Autoboot can be interrupted.
* A known-good local boot method is available.
* wget exists in U-Boot.
* ping ${serverip} succeeds.
* The correct Ethernet interface is selected.
* A valid MAC address exists.
* The kernel downloads successfully.
* The DTB downloads successfully.
* fdt header validates the DTB.
* The kernel and DTB load addresses do not overlap.
* The correct console value is known.
* The correct root partition is known.
* Manual booti or bootz succeeds.
* No flash write or environment-save commands are used.
* The original uEnv.txt is backed up.
* A local boot fallback has been tested.

⸻

Information to Capture for Board-Specific Configuration

Save the output of the following commands:

version
bdinfo
eth list
help wget
help booti
help bootz
printenv

At minimum, capture:

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

Also record:

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

⸻

Recommended Bring-Up Sequence

Use this order to reduce the number of variables being debugged at once:

1. Boot the board normally.
2. Confirm serial-console access.
3. Stop at the U-Boot prompt.
4. Assign a static IP address.
5. Ping the HTTP server.
6. Download only the DTB.
7. Validate the DTB with fdt header.
8. Download the kernel.
9. Boot the HTTP kernel with the existing local root filesystem.
10. Repeat the manual boot several times.
11. Add the tested commands to uEnv.txt.
12. Verify that local fallback still works.
13. Only then consider HTTP-loading an initramfs or using an NFS root filesystem.

⸻

Quick Reference

ARM64

setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no
ping ${serverip}
wget ${loadaddr} ${serverip}:/netboot/Image
wget ${fdtaddr} ${serverip}:/netboot/k3-am625-sk.dtb
fdt addr ${fdtaddr}
fdt header
setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"
booti ${loadaddr} - ${fdtaddr}

ARM32

setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no
ping ${serverip}
wget ${loadaddr} ${serverip}:/netboot/zImage
wget ${fdtaddr} ${serverip}:/netboot/am335x-boneblack.dtb
fdt addr ${fdtaddr}
fdt header
setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"
bootz ${loadaddr} - ${fdtaddr}

⸻

Important Warning

Do not run any of the following during initial testing:

saveenv
env save
mmc write
mmc erase
nand write
nand erase
sf write
sf erase

The purpose of the manual procedure is to load files into RAM and boot them without modifying permanent storage.
