# TI U-Boot Netboot Debugging Guide

This guide explains how to:

- Determine whether `uEnv.txt` is actually being loaded.
- Boot without using `uEnv.txt`.
- Verify you are editing the correct file.
- Configure reliable TFTP retries.
- Debug intermittent TFTP failures.

---

# Symptoms

Typical symptoms include:

- Manual `tftpboot` works but `uEnv.txt` does not.
- Changes made to `uEnv.txt` appear to have no effect.
- TFTP succeeds on the second or third attempt.
- The board attempts to boot even after a failed download.

These usually indicate one of the following:

- Wrong `uEnv.txt`
- Wrong boot partition
- Old environment variables still loaded
- Ethernet link not ready
- Missing retry logic

---

# Step 1 - Interrupt U-Boot

Connect via serial.

Example:

```bash
sudo minicom -D /dev/ttyUSB0 -b 115200
```

Interrupt autoboot until you reach:

```text
=>
```

Do **not** run:

```bash
run bootcmd
```

or

```bash
run envboot
```

Instead, inspect the environment.

---

# Step 2 - See How U-Boot Boots

Print the important variables.

```bash
printenv bootcmd
printenv envboot
printenv bootenvfile
printenv uenvcmd
```

Also determine which storage device is being used.

```bash
printenv mmcdev
printenv bootpart
```

Typical output might be

```text
mmcdev=1
bootpart=1:1
bootenvfile=uEnv.txt
```

Do **not** assume these values.

Always verify them.

---

# Step 3 - Verify the Correct uEnv.txt Exists

Select the boot device.

```bash
mmc dev ${mmcdev}
mmc rescan
```

If using FAT:

```bash
fatls mmc ${bootpart}
```

If using ext4:

```bash
ext4ls mmc ${bootpart} /
```

Verify that:

```text
uEnv.txt
```

is actually present.

---

# Step 4 - Load the File Manually

For FAT:

```bash
fatload mmc ${bootpart} ${loadaddr} ${bootenvfile}
echo ${filesize}
env import -t ${loadaddr} ${filesize}
```

For ext4:

```bash
ext4load mmc ${bootpart} ${loadaddr} /${bootenvfile}
echo ${filesize}
env import -t ${loadaddr} ${filesize}
```

Immediately verify the variables.

```bash
printenv uenvcmd
printenv netboot
printenv retry_tftp
```

If your changes do not appear, you are editing the wrong file.

---

# Step 5 - Add a Version Marker

The easiest way to know which file was loaded is to place a version inside `uEnv.txt`.

Example:

```text
uenv_version=2026-07-31-test1
```

After importing:

```bash
printenv uenv_version
```

If it is missing, your edits are not being loaded.

---

# Step 6 - Clear Old Variables

Old variables can remain in memory.

Delete the ones you are testing.

```bash
setenv uenv_version
setenv uenvcmd
setenv netboot
setenv retry_tftp
```

Reload the file.

```bash
fatload mmc ${bootpart} ${loadaddr} ${bootenvfile}
env import -t ${loadaddr} ${filesize}
```

Verify again.

```bash
printenv uenv_version
```

---

# Step 7 - Restore Default Environment

To completely reset the current environment:

```bash
env default -a
```

This only affects RAM.

It does **not** permanently change flash unless `saveenv` is used.

Afterward, restore networking.

```bash
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv gatewayip 192.168.50.1
setenv autoload no
```

---

# Step 8 - Boot Without uEnv.txt

If you suspect `uEnv.txt` is the problem, simply do **not** run:

```bash
run envboot
```

Instead, configure networking manually.

```bash
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv netmask 255.255.255.0
setenv gatewayip 192.168.50.1
```

Then execute your boot commands manually.

---

# Step 9 - Configure TFTP

Recommended settings:

```bash
setenv netretry once
setenv tftptimeout 3000
setenv tftptimeoutcountmax 5
```

These settings:

- Retry lost packets
- Reduce long waits
- Allow your own retry script to control retries

---

# Step 10 - Wait for Ethernet

Many first-attempt failures occur because Ethernet has not fully initialized.

Before downloading:

```bash
setenv ethrotate no

sleep 3

ping ${serverip}

sleep 1
```

If the ping succeeds, begin downloading.

---

# Step 11 - Three Attempt Retry Example

```bash
if tftpboot ${kernel_addr_r} Image; then
    echo "Kernel downloaded on attempt 1";
else
    echo "Attempt 1 failed";
    sleep 2;
    if tftpboot ${kernel_addr_r} Image; then
        echo "Kernel downloaded on attempt 2";
    else
        echo "Attempt 2 failed";
        sleep 2;
        if tftpboot ${kernel_addr_r} Image; then
            echo "Kernel downloaded on attempt 3";
        else
            echo "Kernel download failed";
        fi;
    fi;
fi
```

Repeat the same pattern for the DTB and initramfs.

---

# Example uEnv.txt

```text
uenv_version=2026-07-31

ipaddr=192.168.50.20
serverip=192.168.50.10
netmask=255.255.255.0
gatewayip=192.168.50.1

autoload=no

kernel_file=Image
dtb_file=k3-am625-sk.dtb
rootfs_file=rootfs.cpio.gz

netretry=once
tftptimeout=3000
tftptimeoutcountmax=5

get_kernel=if tftpboot ${kernel_addr_r} ${kernel_file}; then echo Kernel OK; else echo Kernel Failed; false; fi

get_dtb=if tftpboot ${fdt_addr_r} ${dtb_file}; then echo DTB OK; else echo DTB Failed; false; fi

get_rootfs=if tftpboot ${ramdisk_addr_r} ${rootfs_file}; then setenv initrd_size ${filesize}; echo RootFS OK; else echo RootFS Failed; false; fi

netboot=if ping ${serverip}; then if run get_kernel; then if run get_dtb; then if run get_rootfs; then setenv bootargs "console=${console} rdinit=/init rw"; booti ${kernel_addr_r} ${ramdisk_addr_r}:${initrd_size} ${fdt_addr_r}; fi; fi; fi; fi

uenvcmd=echo Running ${uenv_version}; run netboot
```

---

# Useful Debug Commands

Show all networking variables:

```bash
printenv ipaddr
printenv serverip
printenv gatewayip
printenv netmask
printenv ethact
printenv ethprime
printenv ethrotate
```

Show boot configuration:

```bash
printenv bootcmd
printenv envboot
printenv bootenvfile
printenv uenvcmd
```

List files:

```bash
fatls mmc ${bootpart}
```

or

```bash
ext4ls mmc ${bootpart} /
```

Load environment manually:

```bash
fatload mmc ${bootpart} ${loadaddr} ${bootenvfile}
env import -t ${loadaddr} ${filesize}
```

Verify imported variables:

```bash
printenv uenv_version
printenv uenvcmd
printenv netboot
```

---

# Recommended Debug Procedure

1. Interrupt U-Boot.
2. Verify `bootcmd`, `envboot`, and `bootenvfile`.
3. Verify the correct storage device and partition.
4. List the partition contents.
5. Load `uEnv.txt` manually.
6. Confirm `uenv_version` matches your edits.
7. Reset the environment if necessary.
8. Wait for Ethernet.
9. Ping the server.
10. Manually execute one `tftpboot`.
11. Once successful, test the retry logic.
12. Finally, enable `uenvcmd` and verify the automated boot path behaves exactly like the manual commands.

Following these steps eliminates nearly every common cause of U-Boot netboot issues, including editing the wrong `uEnv.txt`, stale environment variables, incorrect boot partitions, and intermittent TFTP failures.
