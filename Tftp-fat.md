# Manual TFTP Netboot with TI U-Boot

This guide explains how to safely test TFTP netbooting on a TI board using U-Boot.

The process is intentionally split into two phases:

1. Test every command manually.
2. Move the working commands into `uEnv.txt`.

Nothing in this guide writes to flash.

Do **NOT** run:

```
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

A reboot discards all temporary `setenv` changes.

---

# Goal

U-Boot loads normally from SD/eMMC.

Kernel is downloaded via TFTP.

Device Tree is downloaded via TFTP.

Root filesystem stays on the existing SD/eMMC installation.

---

# Example Network

| Device | Address |
|---------|----------|
| TFTP Server | 192.168.50.10 |
| Board | 192.168.50.20 |
| Netmask | 255.255.255.0 |

---

# Example TFTP Directory

```
/opt/tftpboot/
├── Image
├── zImage
├── k3-am625-sk.dtb
└── am335x-boneblack.dtb
```

---

# Configure Networking

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no
```

Verify:

```
printenv ipaddr
printenv serverip
printenv netmask
```

---

# Verify Connectivity

```
ping ${serverip}
```

Expected:

```
host 192.168.50.10 is alive
```

Do not continue until ping succeeds.

---

# Determine Load Addresses

Inspect:

```
printenv loadaddr
printenv fdtaddr

printenv kernel_addr_r
printenv fdt_addr_r
```

If using TI variables:

```
setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
```

If using upstream variables:

```
setenv kernel_addr ${kernel_addr_r}
setenv dtb_addr ${fdt_addr_r}
```

---

# Download the Device Tree

AM62x:

```
tftp ${dtb_addr} k3-am625-sk.dtb
```

AM335x:

```
tftp ${dtb_addr} am335x-boneblack.dtb
```

Verify:

```
echo ${filesize}
md.b ${dtb_addr} 40

fdt addr ${dtb_addr}
fdt header
```

A valid DTB begins with:

```
d0 0d fe ed
```

---

# Download the Kernel

ARM64

```
tftp ${kernel_addr} Image
```

ARM32

```
tftp ${kernel_addr} zImage
```

Verify:

```
echo ${filesize}
```

---

# Preserve Existing Root Filesystem

Inspect:

```
printenv bootargs
printenv console
printenv mmcroot
```

Reuse the existing root partition.

Example:

```
setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"
```

---

# Boot

ARM64

```
booti ${kernel_addr} - ${dtb_addr}
```

ARM32

```
bootz ${kernel_addr} - ${dtb_addr}
```

The dash indicates:

```
No initramfs supplied.
```

---

# Minimal ARM64 Test

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}

tftp ${kernel_addr} Image
tftp ${dtb_addr} k3-am625-sk.dtb

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"

booti ${kernel_addr} - ${dtb_addr}
```

---

# Minimal ARM32 Test

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}

tftp ${kernel_addr} zImage
tftp ${dtb_addr} am335x-boneblack.dtb

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} root=/dev/mmcblk0p2 rootwait rw"

bootz ${kernel_addr} - ${dtb_addr}
```

---

# Example uEnv.txt

ARM64

```
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no

kernel_file=Image
fdt_file=k3-am625-sk.dtb

tftp_kernel=tftp ${loadaddr} ${kernel_file}
tftp_fdt=tftp ${fdtaddr} ${fdt_file}

boot_linux=setenv bootargs console=${console} root=/dev/mmcblk0p2 rootwait rw

tftp_boot=run tftp_kernel; run tftp_fdt; run boot_linux; booti ${loadaddr} - ${fdtaddr}

uenvcmd=run tftp_boot
```

---

# Safety Checklist

- Serial console works
- Ping succeeds
- Kernel downloads
- DTB downloads
- DTB validates
- Root partition confirmed
- No flash writes performed
