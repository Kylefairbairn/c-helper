
# Manual NFS Root Boot with TI U-Boot

This guide demonstrates how to boot Linux using an NFS root filesystem.

Unlike an initramfs RAM boot:

- Only the Linux kernel and Device Tree are downloaded into RAM.
- The Linux kernel mounts the root filesystem from an NFS server.
- No local root filesystem is required.
- No SD card partitions are mounted as the root filesystem.

---

# Boot Flow

```
                U-Boot
                   |
        Configure Network
                   |
          Download Kernel (TFTP)
                   |
      Download Device Tree (TFTP)
                   |
             booti / bootz
                   |
         Linux Kernel Starts
                   |
       Configure Network Driver
                   |
        Mount Root Filesystem
              from NFS
                   |
          Execute /sbin/init
                   |
            Userspace Starts
```

---

# Example Network

Board

```
IP Address : 192.168.50.20
```

Server

```
IP Address : 192.168.50.10
```

Example export

```
/srv/nfs/rootfs
```

---

# Expected NFS Root Filesystem

The exported directory should look similar to:

```
/srv/nfs/rootfs/

bin/
boot/
dev/
etc/
home/
lib/
lib64/
media/
mnt/
opt/
proc/
root/
run/
sbin/
srv/
sys/
tmp/
usr/
var/
```

Verify that init exists:

```
ls -l /srv/nfs/rootfs/sbin/init
```

Example:

```
-rwxr-xr-x
```

If it is a symbolic link:

```
ls -l /srv/nfs/rootfs/sbin/init
```

Example:

```
/sbin/init -> /lib/systemd/systemd
```

Verify the target exists:

```
ls -l /srv/nfs/rootfs/lib/systemd/systemd
```

---

# Verify the NFS Export

View exports:

```
exportfs -v
```

Example:

```
/srv/nfs/rootfs
192.168.50.0/24(rw,sync,no_subtree_check,no_root_squash)
```

Verify the export is visible:

```
showmount -e localhost
```

Example:

```
Export list

/srv/nfs/rootfs
```

---

# Configure U-Boot Networking

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv autoload no
```

Verify connectivity:

```
ping ${serverip}
```

---

# Determine RAM Addresses

Inspect the addresses already configured by U-Boot.

```
printenv loadaddr
printenv fdtaddr

printenv kernel_addr_r
printenv fdt_addr_r
```

Example:

```
setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}
```

Always use the addresses supplied by your U-Boot.

---

# Download the Device Tree

ARM64 Example

```
tftp ${dtb_addr} k3-am625-sk.dtb
```

Verify:

```
fdt addr ${dtb_addr}
fdt header
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

---

# Configure Kernel Boot Arguments

Unlike initramfs boot, do NOT use:

```
rdinit=/init
```

Instead tell Linux to mount an NFS root filesystem.

Static IP example:

```
setenv bootargs "console=${console} root=/dev/nfs rw ip=192.168.50.20:::::eth0:off nfsroot=192.168.50.10:/srv/nfs/rootfs,v3,tcp"
```

DHCP example:

```
setenv bootargs "console=${console} root=/dev/nfs rw ip=dhcp nfsroot=192.168.50.10:/srv/nfs/rootfs,v3,tcp"
```

NFSv4 example:

```
setenv bootargs "console=${console} root=/dev/nfs rw ip=192.168.50.20:::::eth0:off nfsroot=192.168.50.10:/srv/nfs/rootfs,v4,tcp"
```

---

# Boot Linux

ARM64

```
booti ${kernel_addr} - ${dtb_addr}
```

ARM32

```
bootz ${kernel_addr} - ${dtb_addr}
```

Notice the dash (`-`).

No initramfs is passed to the kernel.

---

# Minimal ARM64 Example

```
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0

ping ${serverip}

setenv kernel_addr ${loadaddr}
setenv dtb_addr ${fdtaddr}

tftp ${kernel_addr} Image
tftp ${dtb_addr} k3-am625-sk.dtb

fdt addr ${dtb_addr}
fdt header

setenv bootargs "console=${console} root=/dev/nfs rw ip=192.168.50.20:::::eth0:off nfsroot=192.168.50.10:/srv/nfs/rootfs,v3,tcp"

booti ${kernel_addr} - ${dtb_addr}
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

tftp_kernel=tftp ${loadaddr} ${kernel_file}
tftp_fdt=tftp ${fdtaddr} ${fdt_file}

boot_linux=setenv bootargs console=${console} root=/dev/nfs rw ip=192.168.50.20:::::eth0:off nfsroot=192.168.50.10:/srv/nfs/rootfs,v3,tcp

nfs_boot=run tftp_kernel; run tftp_fdt; run boot_linux; booti ${loadaddr} - ${fdtaddr}

uenvcmd=run nfs_boot
```

---

# Memory Layout

```
+----------------------------+
| Linux Kernel               |
+----------------------------+

        Free Memory

+----------------------------+
| Device Tree                |
+----------------------------+

        Free Memory

(No initramfs is loaded)
```

---

# Troubleshooting

## Verify the kernel actually mounted the NFS root

Look for messages similar to:

```
VFS: Mounted root (nfs filesystem)
```

If you never see this message, Linux never mounted your NFS export.

---

## Verify init exists

```
ls -l /srv/nfs/rootfs/sbin/init
```

If it is a symbolic link, verify the destination exists.

---

## Verify init is executable

```
chmod 755 /srv/nfs/rootfs/sbin/init
```

---

## Verify the architecture

```
file /srv/nfs/rootfs/sbin/init
```

Expected for ARM64:

```
ELF 64-bit LSB executable, ARM aarch64
```

Expected for ARM32:

```
ELF 32-bit LSB executable, ARM
```

The kernel and userspace architectures must match.

---

## Verify Required Libraries

If `/sbin/init` is dynamically linked, verify the runtime loader exists.

ARM64 examples:

```
ls -l /srv/nfs/rootfs/lib/ld-linux-aarch64.so.1
```

or

```
ls -l /srv/nfs/rootfs/lib64/ld-linux-aarch64.so.1
```

Missing runtime libraries can cause the kernel to report:

```
No working init found.
```

even when `/sbin/init` exists.

---

# Safety Checklist

- ✓ Board can ping the server
- ✓ Kernel downloads successfully
- ✓ Device Tree downloads successfully
- ✓ Device Tree validates with `fdt header`
- ✓ NFS export is visible with `showmount`
- ✓ `/sbin/init` exists
- ✓ `/sbin/init` is executable
- ✓ If `/sbin/init` is a symbolic link, the destination exists
- ✓ Required runtime libraries exist
- ✓ Root filesystem architecture matches the kernel
- ✓ `root=/dev/nfs` is present in `bootargs`
- ✓ `nfsroot=` points to the exported directory
- ✓ No flash writes performed
- ✓ No `saveenv` performed
