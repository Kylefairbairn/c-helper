# Jenkins Hardware-in-the-Loop (HIL) NetBoot Pipeline

This guide describes a scalable Jenkins architecture for automatically NetBooting multiple embedded Linux boards using:

- Jenkins
- U-Boot
- TFTP
- NFS
- DHCP (optional)
- Serial Console
- Linux Kernel
- Device Tree (DTB)
- Root Filesystem (NFS)

The goal is to allow Jenkins to boot one or many boards, execute tests, collect logs, and clean up automatically.

---

# High Level Architecture

```
                      Jenkins Controller
                              │
                              │
                    Schedules Pipeline Jobs
                              │
                              ▼
                 Jenkins Agent (Boot Server)
        ┌──────────────────────────────────────┐
        │                                      │
        │ TFTP Server                          │
        │ NFS Server                           │
        │ DHCP Server (optional)               │
        │ Python Automation                    │
        │ Serial Console Connections           │
        │ Power Control                        │
        └──────────────────────────────────────┘
              │          │          │
              │          │          │
          Board 1    Board 2    Board 3
```

The Boot Server should also run the Jenkins Agent because it already has access to:

- TFTP
- NFS
- Serial ports
- Power control
- Test tools
- Network

The Jenkins controller should only orchestrate jobs.

---

# Recommended Directory Layout

```
/opt/lab/

├── boards.yaml
├── Jenkinsfile
│
├── tools/
│   ├── netboot.py
│   ├── serial_console.py
│   ├── power.py
│   ├── prepare_rootfs.py
│   ├── verify_boot.py
│   └── cleanup.py
│
├── tftp/
│   ├── Image
│   ├── k3-am625-sk.dtb
│   └── pxelinux.cfg/
│
├── rootfs/
│   ├── templates/
│   └── jobs/
│
└── logs/
```

---

# Board Inventory

Never hardcode board information.

Instead create a single YAML file.

```yaml
boards:

  am62-board-01:
    ip: 192.168.50.21
    serial: /dev/serial/by-id/usb-board1
    power: 1
    dtb: k3-am625-sk.dtb

  am62-board-02:
    ip: 192.168.50.22
    serial: /dev/serial/by-id/usb-board2
    power: 2
    dtb: k3-am625-sk.dtb

  beaglebone:
    ip: 192.168.50.30
    serial: /dev/serial/by-id/usb-bbb
    power: 3
    dtb: am335x-boneblack.dtb
```

Using `/dev/serial/by-id` prevents issues when USB numbering changes.

---

# Boot Artifacts

Each build consists of:

```
Kernel
Device Tree
Root Filesystem
```

Example:

```
Image
k3-am625-sk.dtb
NFS RootFS
```

The kernel and DTB are downloaded from TFTP.

The root filesystem is mounted over NFS.

---

# TFTP Layout

```
/opt/tftpboot/

images/

    build-184/
        Image
        k3-am625-sk.dtb

    build-185/
        Image
        k3-am625-sk.dtb
```

Each Jenkins build may produce a unique kernel.

---

# NFS Layout

Do NOT share one writable root filesystem between multiple boards.

Bad

```
/srv/nfs/rootfs
```

Good

```
/srv/nfs/jobs/

    build-184/

        board1/

        board2/

    build-185/

        board1/

        board2/
```

Each board receives its own isolated writable root filesystem.

This prevents:

- log corruption
- PID conflicts
- SSH key conflicts
- database corruption
- package conflicts

---

# Preparing RootFS

A build starts by copying a template.

```
Template RootFS
        │
        ▼
rsync
        │
        ▼
Build RootFS
```

Example

```bash
mkdir -p /srv/nfs/jobs/$BUILD_NUMBER/$BOARD

rsync -aHAX --delete \
    /srv/nfs/templates/base/ \
    /srv/nfs/jobs/$BUILD_NUMBER/$BOARD/
```

Inject build information.

```bash
echo "$BUILD_NUMBER" \
> /srv/nfs/jobs/$BUILD_NUMBER/$BOARD/etc/build-number
```

---

# Jenkins Parameters

Recommended pipeline parameters.

```
BOARD

KERNEL

ROOTFS

RUN_BOOT

RUN_TESTS

POWER_CYCLE

CLEANUP
```

Example

```
BOARD = am62-board-01

RUN_BOOT = true

RUN_TESTS = true

POWER_CYCLE = true
```

---

# Pipeline Flow

```
Validate Parameters
        │
        ▼
Acquire Board Lock
        │
        ▼
Prepare RootFS
        │
        ▼
Prepare Boot Files
        │
        ▼
Open Serial Console
        │
        ▼
Power Cycle Board
        │
        ▼
NetBoot
        │
        ▼
Verify Boot
        │
        ▼
Run Tests
        │
        ▼
Collect Logs
        │
        ▼
Cleanup
        │
        ▼
Release Board
```

---

# Locking Boards

Only one Jenkins job should own a physical board.

Use the Jenkins Lockable Resources plugin.

Example resources

```
am62-board-01

am62-board-02

beaglebone
```

A job acquires the board before booting.

This prevents two jobs from attempting to:

- power cycle
- access serial
- overwrite boot configuration
- use the same board

at the same time.

---

# NetBoot Process

The Python automation should perform:

```
Power Cycle
        │
        ▼
Interrupt U-Boot
        │
        ▼
Configure Network
        │
        ▼
Download Kernel
        │
        ▼
Download DTB
        │
        ▼
Set Bootargs
        │
        ▼
Boot Linux
```

Example U-Boot commands

```
setenv ipaddr 192.168.50.21

setenv serverip 192.168.50.10

setenv netmask 255.255.255.0

tftpboot ${kernel_addr_r} Image

tftpboot ${fdt_addr_r} k3-am625-sk.dtb

setenv bootargs \
'console=ttyS2,115200 \
root=/dev/nfs rw \
nfsroot=192.168.50.10:/srv/nfs/jobs/184/board1,vers=3,tcp'

booti ${kernel_addr_r} - ${fdt_addr_r}
```

Nothing is permanently written to flash.

Everything exists only in RAM.

---

# Boot Verification

A successful boot should progress through these stages.

```
U-Boot

↓

Kernel Starts

↓

Mount NFS

↓

Run init

↓

SSH Available

↓

Run Tests
```

Verification levels

Level 1

Kernel downloaded successfully.

Level 2

Linux starts.

Level 3

RootFS mounted.

Level 4

Init started.

Level 5

SSH responds.

---

# Test Execution

Once SSH becomes available Jenkins can execute tests.

Example

```bash
ssh root@192.168.50.21

pytest

robot

custom_tests
```

Results are archived by Jenkins.

---

# Serial Logging

Always capture serial output.

Example

```
logs/

    board1.log

    board2.log
```

If Linux never boots, serial logs become the primary debugging source.

---

# Parallel Execution

Jenkins can boot multiple boards simultaneously.

```
Pipeline

├── Board 1

├── Board 2

└── Board 3
```

Requirements

Each board must have:

- unique IP
- unique serial port
- unique power channel
- unique NFS root
- Jenkins lock

Kernel images may be shared.

Root filesystems should not.

---

# Cleanup

After tests complete

```
Delete Build RootFS

Archive Logs

Release Board

Finish Pipeline
```

Example

```bash
rm -rf /srv/nfs/jobs/$BUILD_NUMBER
```

---

# Suggested Python Commands

The automation tool should expose simple commands.

Boot

```bash
python3 netboot.py boot \
    --board am62-board-01
```

Power Cycle

```bash
python3 netboot.py power \
    --board am62-board-01
```

Open Console

```bash
python3 netboot.py console \
    --board am62-board-01
```

Check Status

```bash
python3 netboot.py status \
    --board am62-board-01
```

Cleanup

```bash
python3 netboot.py cleanup \
    --build 184
```

---

# Recommended Development Order

1. Create Boot Server Jenkins Agent
2. Create `boards.yaml`
3. Automate one board over serial
4. Prepare isolated NFS root
5. Implement board locking
6. Capture serial logs
7. Wait for SSH
8. Execute tests
9. Archive results
10. Add additional boards
11. Enable parallel execution
12. Optionally transition to fully automatic DHCP/PXE boot

---

# Final Architecture

```
                     Jenkins Controller
                              │
                              ▼
                  Jenkins Agent (Boot Server)
       ┌────────────────────────────────────────────┐
       │                                            │
       │ Python Automation                          │
       │ TFTP                                       │
       │ NFS                                        │
       │ Serial                                     │
       │ Power Control                              │
       └────────────────────────────────────────────┘
           │              │              │
           ▼              ▼              ▼
      AM62 Board 1   AM62 Board 2   BeagleBone
           │              │              │
           └──────Parallel NetBoot──────┘
                      │
                      ▼
                Automated Testing
                      │
                      ▼
              Jenkins Test Reports
```

This architecture scales cleanly from a single development board to a hardware lab with many boards while keeping each board isolated, reproducible, and fully automated.
