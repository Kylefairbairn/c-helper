# Manual TFTP RAM Boot with TI U-Boot

This guide performs a complete RAM boot.

Nothing except U-Boot itself is loaded from local storage.

The following are downloaded via TFTP:

- Linux kernel
- Device Tree
- initramfs/root filesystem

No SD card partitions are mounted.

---

# Example TFTP Directory

```
/opt/tftpboot/

Image
k3-am625-sk.dtb
rootfs.cpio.gz
```

or

```
zImage
am335x-boneblack.dtb
rootfs.cpio.gz
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
ping ${serverip}
```

---

# Determine RAM Addresses

Inspect:

```
printenv loadaddr
printenv fdtaddr
printenv rdaddr

printenv kernel_addr_r
printenv fdt_addr_r
printenv ramdisk_addr_r
```

Example:

```
setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
setenv initrd_addr ${rdaddr}
```

---

# Download Device Tree

```
tftp ${dtb_addr} k3-am625-sk.dtb
```

Verify:

```
fdt addr ${dtb_addr}
fdt header
```

---

# Download Kernel

ARM64

```
tftp ${kernel_addr} Image
```

ARM32

```
tftp ${kernel_addr} zImage
```

---

# Download Root Filesystem

```
tftp ${initrd_addr} rootfs.cpio.gz
```

Record its size:

```
setenv initrd_size ${filesize}
```

---

# Boot Arguments

Since the root filesystem is inside the initramfs:

```
setenv bootargs "console=${console} rdinit=/init"
```

Some distributions instead use:

```
setenv bootargs "console=${console}"
```

Follow the requirements of your initramfs.

---

# Boot

ARM64

```
booti ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}
```

ARM32

```
bootz ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}
```

---

# Minimal ARM64 Test

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
setenv initrd_addr ${rdaddr}

tftp ${kernel_addr} Image
tftp ${dtb_addr} k3-am625-sk.dtb
tftp ${initrd_addr} rootfs.cpio.gz

setenv initrd_size ${filesize}

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} rdinit=/init"

booti ${kernel_addr} ${initrd_addr}:${initrd_size} ${dtb_addr}
```

---

# Example uEnv.txt

```
ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
autoload=no

kernel_file=Image
fdt_file=k3-am625-sk.dtb
initrd_file=rootfs.cpio.gz

tftp_kernel=tftp ${loadaddr} ${kernel_file}
tftp_fdt=tftp ${fdtaddr} ${fdt_file}
tftp_initrd=tftp ${rdaddr} ${initrd_file}

boot_linux=setenv bootargs console=${console} rdinit=/init

ram_boot=run tftp_kernel; run tftp_fdt; run tftp_initrd; setenv initrd_size ${filesize}; run boot_linux; booti ${loadaddr} ${rdaddr}:${initrd_size} ${fdtaddr}

uenvcmd=run ram_boot
```

---

# Memory Layout

Typical layout:

```
+----------------------------+
| Linux Kernel               |
+----------------------------+

        free memory

+----------------------------+
| Device Tree                |
+----------------------------+

        free memory

+----------------------------+
| initramfs                  |
+----------------------------+
```

Always use the addresses already provided by U-Boot.

Do not invent addresses.

---

# Safety Checklist

- Ping succeeds
- Kernel downloads
- DTB downloads
- initramfs downloads
- DTB validates
- Memory regions do not overlap
- No flash writes performed
- No saveenv performed
