# Complete Artifactory WIC\-to\-NetBoot Jenkins Guide

This guide builds a repeatable deployment system for TI U\-Boot boards using:

- **Artifactory Pro** as the permanent source of `.wic` images;
- **Jenkins** to select a product, image type, version, and target board;
- **dnsmasq/TFTP** to serve the kernel and device tree;
- **NFS** to serve a separate writable root filesystem to each board;
- **uEnv\.txt** to tell U\-Boot exactly which release to boot\.

The board does not boot the `.wic` directly and the pipeline does not `dd` it to the board\. Jenkins downloads the WIC, verifies it, extracts it once into an immutable release, creates a board\-specific runtime rootfs, installs `uEnv.txt`, and reboots the board\.

---

## 1\. Recommended architecture

Artifactory remains the source of truth\. The NetBoot server is an extracted release cache and board\-runtime server\.

```text
Artifactory
└── yocto-images/
    └── product-a/
        └── 2.5.0/
            ├── product-a-release-2.5.0.wic
            ├── product-a-release-2.5.0.wic.sha256
            ├── product-a-debug-2.5.0.wic
            └── product-a-debug-2.5.0.wic.sha256

NetBoot VM
└── /srv/netboot/
    ├── releases/                         # Immutable extracted releases
    │   └── product-a/
    │       ├── release/2.5.0/
    │       │   ├── Image
    │       │   ├── board.dtb
    │       │   ├── rootfs/
    │       │   ├── manifest.env
    │       │   └── source.wic.sha256
    │       └── debug/2.5.0/
    ├── boards/                           # Writable rootfs per board/deployment
    │   └── board-01/
    │       ├── deployments/
    │       │   └── product-a-release-2.5.0/
    │       │       └── rootfs/
    │       ├── current -> deployments/product-a-release-2.5.0
    │       └── uEnv.txt
    ├── staging/                          # Temporary WIC downloads
    └── locks/

TFTP root
└── /opt/tftpboot/releases                # Bind mount of /srv/netboot/releases
```

### Why two rootfs copies exist

The rootfs under `releases/` is immutable and never booted read/write\. For every board assignment, the pipeline copies that rootfs into a board\-specific deployment directory\. This prevents two boards from sharing writable logs, SSH keys, machine IDs, DHCP state, databases, or configuration\.

The `current` symlink is for operators and inventory\. The generated `uEnv.txt` uses an exact product/type/version path, so changing a symlink cannot silently change what the board boots\.

---

## 2\. End\-to\-end pipeline

1. Trigger Jenkins with `PRODUCT`, `IMAGE_TYPE`, `VERSION`, and `BOARD_ID`\.
2. Jenkins constructs the Artifactory artifact path\.
3. If the extracted release does not exist, Jenkins downloads the WIC and `.sha256` file\.
4. Jenkins verifies SHA\-256 before using the image\.
5. The NetBoot server attaches the WIC read\-only using a loop device\.
6. It mounts the boot and root partitions read\-only\.
7. It extracts `Image`, the selected DTB, and the rootfs into a temporary directory\.
8. It validates and atomically publishes the immutable release\.
9. It creates a writable, versioned rootfs for the selected board\.
10. Jenkins generates a board\-specific `uEnv.txt`\.
11. Jenkins records the assignment on the server\.
12. Jenkins installs `uEnv.txt` on the board’s real local boot partition\.
13. Jenkins reboots the board\.
14. U\-Boot downloads the kernel and DTB by TFTP\.
15. Linux mounts its board\-specific rootfs over NFS\.
16. Jenkins waits for SSH to return and verifies the running assignment file\.

---

## 3\. Assumptions and values to change

The examples use:

```text
NetBoot VM:             192.168.50.10
Target board:           192.168.50.20
Network:                192.168.50.0/24
TFTP root:              /opt/tftpboot
NetBoot data:           /srv/netboot
Artifactory repository: yocto-images
WIC boot partition:     1
WIC root partition:     2
Kernel:                 Image
DTB:                    k3-am625-sk.dtb
Board boot mount:       /boot
```

Confirm your actual WIC layout:

```bash
fdisk -l product-a-release-2.5.0.wic
```

Confirm your U\-Boot variables at the serial console:

```bash
printenv kernel_addr_r fdt_addr_r console
```

Confirm where the running board mounts the FAT boot partition:

```bash
findmnt
lsblk -f
```

Do not assume `/boot` is correct\. Some Yocto images mount the U\-Boot\-readable partition under `/run/media/...`\.

---

## 4\. Prepare the NetBoot VM

### RHEL/Fedora family

```bash
sudo dnf install -y dnsmasq nfs-utils rsync util-linux curl
```

### Debian/Ubuntu family

```bash
sudo apt-get update
sudo apt-get install -y dnsmasq nfs-kernel-server rsync util-linux curl
```

Create service accounts and directories\. Replace `jenkins-deploy` if your SSH deployment account has a different name\.

```bash
sudo useradd --create-home --shell /bin/bash jenkins-deploy

sudo install -d -o root -g root -m 0755 /srv/netboot
sudo install -d -o root -g root -m 0755 /srv/netboot/releases
sudo install -d -o jenkins-deploy -g jenkins-deploy -m 0750 /srv/netboot/staging
sudo install -d -o root -g root -m 0755 /srv/netboot/boards
sudo install -d -o root -g root -m 0755 /srv/netboot/locks
sudo install -d -o root -g root -m 0755 /opt/tftpboot
sudo install -d -o root -g root -m 0755 /opt/tftpboot/releases
sudo install -d -o root -g root -m 0755 /usr/local/libexec/wic-netboot
```

---

## 5\. Configure dnsmasq TFTP

If this dnsmasq instance is used only for TFTP, create `/etc/dnsmasq.d/netboot-tftp.conf`:

```ini
port=0
enable-tftp
tftp-root=/opt/tftpboot
log-dhcp
```

If dnsmasq already supplies DHCP or DNS, do **not** add `port=0`\. Add only:

```ini
enable-tftp
tftp-root=/opt/tftpboot
log-dhcp
```

Validate and restart:

```bash
sudo dnsmasq --test
sudo systemctl restart dnsmasq
sudo systemctl enable dnsmasq
sudo systemctl status dnsmasq
```

### Bind\-mount releases into the TFTP root

Using a bind mount avoids TFTP/SELinux problems caused by following a symlink outside the configured TFTP root\.

Add this to `/etc/fstab`:

```fstab
/srv/netboot/releases /opt/tftpboot/releases none bind 0 0
```

Mount it:

```bash
sudo mount /opt/tftpboot/releases
findmnt /opt/tftpboot/releases
```

On SELinux systems, label the TFTP tree appropriately for your distribution:

```bash
sudo semanage fcontext -a -t tftpdir_t '/opt/tftpboot(/.*)?'
sudo restorecon -RFv /opt/tftpboot
```

If `semanage` is unavailable, install the distribution package providing SELinux policy\-management utilities\. Do not solve TFTP failures by setting global permissive mode\.

---

## 6\. Configure NFS

Export only board runtime roots as writable\. Add this to `/etc/exports`:

```exports
/srv/netboot/boards 192.168.50.0/24(rw,sync,no_subtree_check,no_root_squash)
```

Apply and verify:

```bash
sudo exportfs -rav
sudo exportfs -v
sudo systemctl enable --now nfs-server
```

On Debian/Ubuntu, the service may be named `nfs-kernel-server`:

```bash
sudo systemctl enable --now nfs-kernel-server
```

`no_root_squash` is commonly required for an NFS root filesystem\. Restrict the export to the isolated board network and firewall it accordingly\.

---

## 7\. Firewall checks

At minimum the boards need access to:

- UDP 69 for TFTP;
- NFS and RPC services required by your NFS version;
- SSH from Jenkins to the management address of the board;
- ICMP if the pipeline uses ping diagnostics\.

For a controlled lab, prefer placing the boards and boot server on a dedicated VLAN rather than opening these services broadly\.

Test TFTP from another Linux host when possible:

```bash
tftp 192.168.50.10 -c get releases/test-file
```

Test NFS visibility:

```bash
showmount -e 192.168.50.10
```

---

## 8\. Jenkins repository structure

The repository contains three Bash programs with separate responsibilities:

|Script                   |Runs on               |Responsibility                                                                                                         |
|-------------------------|----------------------|-----------------------------------------------------------------------------------------------------------------------|
|`publish-wic-release.sh` |NetBoot server as root|Mount the WIC read-only, extract the kernel/DTB/rootfs, preserve Linux metadata, and publish an immutable release.     |
|`prepare-board-rootfs.sh`|NetBoot server as root|Copy an immutable rootfs into a writable, versioned rootfs owned by one board and record what it should boot.          |
|`render-uenv.sh`         |Jenkins agent         |Convert deployment parameters into a validated board-specific `uEnv.txt`; it does not mount images or modify the board.|

The three Python files later in this guide implement the same command\-line interfaces and behavior\. You can choose Bash or Python without changing the directory layout or `uEnv.txt` format\.

Jenkins itself downloads and verifies the WIC, calls these scripts in order, copies the rendered `uEnv.txt` onto the board’s boot partition, reboots the board, and confirms that the intended NFS root came online\.

Create a Git repository with:

```text
wic-netboot/
├── Jenkinsfile
├── README.md
├── scripts/
│   ├── publish-wic-release.sh
│   ├── prepare-board-rootfs.sh
│   ├── render-uenv.sh
│   ├── publish_wic_release.py
│   ├── prepare_board_rootfs.py
│   └── render_uenv.py
└── templates/
    └── uEnv.txt.template
```

---

## 9\. WIC publication script

Save as `scripts/publish-wic-release.sh`:

This is the extraction script\. It treats the WIC as a read\-only virtual disk, mounts its boot and root partitions, copies the three NetBoot components, validates them, and publishes the release with one atomic directory rename\. The cleanup trap ensures mounts and loop devices are released even if extraction fails\.

```bash
#!/usr/bin/env bash

# Exit on the first error (-e), reject unset variables (-u), propagate pipeline
# failures (-o pipefail), and preserve ERR traps inside functions (-E).
set -Eeuo pipefail

# Print the required positional arguments when the caller supplies the wrong
# number of values.
usage() {
    echo "Usage: $0 WIC PRODUCT IMAGE_TYPE VERSION BOOT_PART ROOT_PART KERNEL_PATH DTB_PATH" >&2
    exit 2
}

[[ $# -eq 8 ]] || usage

# Arguments supplied by Jenkins. kernel_path and dtb_path are paths inside the
# WIC boot filesystem, not paths on the NetBoot server.
wic=$1
product=$2
image_type=$3
version=$4
boot_part=$5
root_part=$6
kernel_path=$7
dtb_path=$8

netboot_root=/srv/netboot

# Immutable final destination, for example:
# /srv/netboot/releases/product-a/release/2.5.0
release_dir=${netboot_root}/releases/${product}/${image_type}/${version}
release_parent=$(dirname "${release_dir}")

# Mounts live in /tmp. Extracted content is built beside the final release so
# the final mv remains on one filesystem and is atomic.
mount_dir=$(mktemp -d /tmp/wic-mount.XXXXXX)
work_dir=
loop_device=

# Always unmount partitions, detach the loop device, and remove incomplete
# temporary content. This runs on success, error, or interruption.
cleanup() {
    set +e
    mountpoint -q "${mount_dir}/boot" && umount "${mount_dir}/boot"
    mountpoint -q "${mount_dir}/root" && umount "${mount_dir}/root"
    [[ -n "${loop_device}" ]] && losetup -d "${loop_device}"
    rmdir "${mount_dir}/boot" "${mount_dir}/root" "${mount_dir}" 2>/dev/null || true
    [[ -n "${work_dir}" && -d "${work_dir}" ]] && rm -rf -- "${work_dir}"
}
trap cleanup EXIT

# Restrict names before using them as directory components. This prevents path
# traversal and accidental publication outside /srv/netboot/releases.
valid_name='^[A-Za-z0-9][A-Za-z0-9._-]*$'
[[ "${product}" =~ ${valid_name} ]] || { echo "Invalid product" >&2; exit 1; }
[[ "${image_type}" == release || "${image_type}" == debug ]] || { echo "IMAGE_TYPE must be release or debug" >&2; exit 1; }
[[ "${version}" =~ ${valid_name} ]] || { echo "Invalid version" >&2; exit 1; }
[[ "${boot_part}" =~ ^[0-9]+$ ]] || { echo "Invalid boot partition" >&2; exit 1; }
[[ "${root_part}" =~ ^[0-9]+$ ]] || { echo "Invalid root partition" >&2; exit 1; }
[[ -f "${wic}" ]] || { echo "WIC not found: ${wic}" >&2; exit 1; }

# Published releases are immutable. A repeated product/type/version must fail
# instead of silently replacing a known release.
[[ ! -e "${release_dir}" ]] || { echo "Release already exists: ${release_dir}" >&2; exit 3; }

# Prepare mount points and a hidden, incomplete release directory.
mkdir -p "${release_parent}" "${mount_dir}/boot" "${mount_dir}/root"
work_dir=$(mktemp -d "${release_parent}/.publish-${version}.XXXXXX")
mkdir -p "${work_dir}/rootfs"

# Attach the WIC as a read-only virtual block device and ask the kernel to scan
# its partition table. A result might be /dev/loop0, producing /dev/loop0p1.
loop_device=$(losetup --find --show --partscan --read-only "${wic}")
boot_device=${loop_device}p${boot_part}
root_device=${loop_device}p${root_part}

[[ -b "${boot_device}" ]] || { echo "Boot partition not found: ${boot_device}" >&2; exit 1; }
[[ -b "${root_device}" ]] || { echo "Root partition not found: ${root_device}" >&2; exit 1; }

# Never write to the source image during extraction.
mount -o ro "${boot_device}" "${mount_dir}/boot"
mount -o ro "${root_device}" "${mount_dir}/root"

kernel_source=${mount_dir}/boot/${kernel_path#/}
dtb_source=${mount_dir}/boot/${dtb_path#/}

# Yocto layouts vary. First look in the dedicated boot partition; if the files
# are absent, try /boot inside the root filesystem.
if [[ ! -f "${kernel_source}" ]]; then
    kernel_source=${mount_dir}/root/boot/${kernel_path#/}
fi
if [[ ! -f "${dtb_source}" ]]; then
    dtb_source=${mount_dir}/root/boot/${dtb_path#/}
fi

[[ -f "${kernel_source}" ]] || { echo "Kernel not found: ${kernel_path}" >&2; exit 1; }
[[ -f "${dtb_source}" ]] || { echo "DTB not found: ${dtb_path}" >&2; exit 1; }

# Catch an obviously unusable root filesystem before publishing it.
[[ -e "${mount_dir}/root/sbin/init" || -e "${mount_dir}/root/init" ]] || {
    echo "Rootfs has neither /sbin/init nor /init" >&2
    exit 1
}

# Normalize filenames for U-Boot. Every release exposes Image and board.dtb
# even if Artifactory's WIC uses a product-specific DTB filename.
install -m 0644 "${kernel_source}" "${work_dir}/Image"
install -m 0644 "${dtb_source}" "${work_dir}/board.dtb"

# Preserve permissions, ownership, symlinks, hard links, ACLs, extended
# attributes, and numeric UIDs/GIDs. Those details are essential for /sbin/init
# and a functional Linux userspace.
rsync -aHAX --numeric-ids "${mount_dir}/root/" "${work_dir}/rootfs/"

# Record provenance so an extracted release can be traced back to its WIC.
sha256sum "${wic}" | awk '{print $1}' > "${work_dir}/source.wic.sha256"
cat > "${work_dir}/manifest.env" <<EOF
PRODUCT=${product}
IMAGE_TYPE=${image_type}
VERSION=${version}
SOURCE_WIC=$(basename "${wic}")
KERNEL_PATH=${kernel_path}
DTB_PATH=${dtb_path}
CREATED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

# Final validation before anything becomes visible at the permanent path.
test -s "${work_dir}/Image"
test -s "${work_dir}/board.dtb"
test -d "${work_dir}/rootfs/etc"

# Rename on the same filesystem publishes the complete directory atomically.
mv "${work_dir}" "${release_dir}"

# Prevent the EXIT trap from trying to remove the directory after it has moved.
work_dir=
echo "Published ${release_dir}"
```

Make it executable:

```bash
chmod +x scripts/publish-wic-release.sh
```

---

## 10\. Per\-board rootfs preparation script

Save as `scripts/prepare-board-rootfs.sh`:

This script turns the immutable release rootfs into a writable runtime rootfs for one board\. It serializes work per board, copies the filesystem only when that exact deployment does not already exist, writes an assignment marker inside it, and updates an operator\-facing `current` symlink\.

```bash
#!/usr/bin/env bash

# Use strict Bash behavior so partial deployments stop immediately.
set -Eeuo pipefail

# Describe the four values Jenkins must supply.
usage() {
    echo "Usage: $0 PRODUCT IMAGE_TYPE VERSION BOARD_ID" >&2
    exit 2
}

[[ $# -eq 4 ]] || usage

# The selected immutable release and target board.
product=$1
image_type=$2
version=$3
board_id=$4

netboot_root=/srv/netboot
release=${netboot_root}/releases/${product}/${image_type}/${version}

# A board receives its own writable copy. Including product, image type, and
# version in the name lets older deployments remain available for rollback.
deployment_name=${product}-${image_type}-${version}
board_dir=${netboot_root}/boards/${board_id}
deployment=${board_dir}/deployments/${deployment_name}
temporary=${board_dir}/deployments/.prepare-${deployment_name}.$$
lock_file=${netboot_root}/locks/${board_id}.lock

# Validate every value used as part of a filesystem path.
valid_name='^[A-Za-z0-9][A-Za-z0-9._-]*$'
[[ "${product}" =~ ${valid_name} ]] || { echo "Invalid product" >&2; exit 1; }
[[ "${image_type}" == release || "${image_type}" == debug ]] || { echo "Invalid image type" >&2; exit 1; }
[[ "${version}" =~ ${valid_name} ]] || { echo "Invalid version" >&2; exit 1; }
[[ "${board_id}" =~ ${valid_name} ]] || { echo "Invalid board ID" >&2; exit 1; }
[[ -s "${release}/Image" && -s "${release}/board.dtb" ]] || { echo "Release is incomplete" >&2; exit 1; }
[[ -d "${release}/rootfs/etc" ]] || { echo "Release rootfs is incomplete" >&2; exit 1; }

# Hold an exclusive per-board lock on file descriptor 9. Two Jenkins builds
# cannot prepare or change the same board at the same time.
exec 9>"${lock_file}"
flock 9

mkdir -p "${board_dir}/deployments"

# Reuse an existing deployment during rollback or redeployment. Otherwise,
# build a complete temporary copy and publish it with a single rename.
if [[ ! -d "${deployment}/rootfs" ]]; then
    # Remove only this validated temporary directory if rsync fails.
    trap 'rm -rf -- "${temporary}"' EXIT
    mkdir -p "${temporary}/rootfs"

    # Create a private writable rootfs while preserving Linux filesystem
    # metadata. Multiple boards must never share one writable NFS root.
    rsync -aHAX --numeric-ids "${release}/rootfs/" "${temporary}/rootfs/"

    # Jenkins reads this file after reboot to prove that the intended NFS root
    # actually booted, rather than merely accepting an SSH connection.
    mkdir -p "${temporary}/rootfs/etc"
    cat > "${temporary}/rootfs/etc/netboot-assignment" <<EOF
BOARD_ID=${board_id}
PRODUCT=${product}
IMAGE_TYPE=${image_type}
VERSION=${version}
DEPLOYED_UTC=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF

    # Atomically expose the finished board deployment.
    mv "${temporary}" "${deployment}"

    # The temporary path no longer exists, so disable its failure cleanup.
    trap - EXIT
fi

# This symlink is for inventory and human inspection. uEnv.txt uses the exact
# versioned deployment path and does not boot through this mutable pointer.
ln -sfn "deployments/${deployment_name}" "${board_dir}/current"
echo "Prepared ${deployment}"
```

Make it executable:

```bash
chmod +x scripts/prepare-board-rootfs.sh
```

The script intentionally does not overwrite an existing board deployment\. If you need a clean redeployment of the exact same version, publish a new unique build version or explicitly remove that board deployment while the board is not using it\.

---

## 11\. uEnv\.txt template

Save as `templates/uEnv.txt.template`:

```text
board_id=@@BOARD_ID@@
product=@@PRODUCT@@
image_type=@@IMAGE_TYPE@@
version=@@VERSION@@

ipaddr=@@BOARD_IP@@
serverip=@@SERVER_IP@@
gatewayip=@@GATEWAY_IP@@
netmask=@@NETMASK@@
autoload=no

netboot=setenv kernel_file releases/${product}/${image_type}/${version}/Image; setenv dtb_file releases/${product}/${image_type}/${version}/board.dtb; setenv nfs_path /srv/netboot/boards/${board_id}/deployments/${product}-${image_type}-${version}/rootfs; ping ${serverip}; tftpboot ${kernel_addr_r} ${kernel_file}; tftpboot ${fdt_addr_r} ${dtb_file}; setenv bootargs "console=${console} root=/dev/nfs rw rootwait nfsroot=${serverip}:${nfs_path},vers=3,tcp ip=${ipaddr}:${serverip}:${gatewayip}:${netmask}::eth0:off"; booti ${kernel_addr_r} - ${fdt_addr_r}

uenvcmd=run netboot
```

Keep the `netboot=` value on one physical line\. A U\-Boot environment file is not a Bash script, and shell\-style line continuations are not consistently supported during environment import\.

If the image uses a 32\-bit ARM kernel, replace `booti` with `bootz`\. If your U\-Boot build uses different load variables, change `kernel_addr_r` and `fdt_addr_r` only after confirming them with `printenv`\.

---

## 12\. uEnv\.txt renderer

Save as `scripts/render-uenv.sh`:

This script does not contact the board or run U\-Boot commands\. It validates Jenkins parameters, substitutes them into the text template, and refuses to produce a file if any placeholder remains unresolved\.

```bash
#!/usr/bin/env bash

# Fail immediately on errors, unset variables, or failed pipelines.
set -Eeuo pipefail

# Two file arguments plus eight deployment/network values are required.
if [[ $# -ne 10 ]]; then
    echo "Usage: $0 TEMPLATE OUTPUT BOARD_ID PRODUCT IMAGE_TYPE VERSION BOARD_IP SERVER_IP GATEWAY_IP NETMASK" >&2
    exit 2
fi

template=$1
output=$2

# Board assignment values that will be embedded in uEnv.txt.
board_id=$3
product=$4
image_type=$5
version=$6
board_ip=$7
server_ip=$8
gateway_ip=$9
netmask=${10}

# Validate values used in remote paths. IMAGE_TYPE is deliberately limited to
# the two Artifactory image classes supported by this pipeline.
valid_name='^[A-Za-z0-9][A-Za-z0-9._-]*$'
[[ "${board_id}" =~ ${valid_name} ]] || { echo "Invalid board ID" >&2; exit 1; }
[[ "${product}" =~ ${valid_name} ]] || { echo "Invalid product" >&2; exit 1; }
[[ "${image_type}" == release || "${image_type}" == debug ]] || { echo "Invalid image type" >&2; exit 1; }
[[ "${version}" =~ ${valid_name} ]] || { echo "Invalid version" >&2; exit 1; }

# Replace every explicit @@PLACEHOLDER@@ token. The separator is | so IP
# addresses and normal forward-slash-free values remain readable.
sed \
    -e "s|@@BOARD_ID@@|${board_id}|g" \
    -e "s|@@PRODUCT@@|${product}|g" \
    -e "s|@@IMAGE_TYPE@@|${image_type}|g" \
    -e "s|@@VERSION@@|${version}|g" \
    -e "s|@@BOARD_IP@@|${board_ip}|g" \
    -e "s|@@SERVER_IP@@|${server_ip}|g" \
    -e "s|@@GATEWAY_IP@@|${gateway_ip}|g" \
    -e "s|@@NETMASK@@|${netmask}|g" \
    "${template}" > "${output}"

# Confirm that automatic NetBoot is present and that no required placeholder
# was accidentally omitted from the sed replacement list.
grep -q '^uenvcmd=run netboot$' "${output}"
if grep -Eq '@@[A-Z_]+@@' "${output}"; then
    echo "The rendered file contains unresolved placeholders" >&2
    exit 1
fi
```

Make it executable and validate all scripts:

```bash
chmod +x scripts/render-uenv.sh
bash -n scripts/publish-wic-release.sh
bash -n scripts/prepare-board-rootfs.sh
bash -n scripts/render-uenv.sh
```

---

## 13\. Install trusted server scripts

Install the two privileged scripts on the NetBoot VM from a reviewed Git revision:

```bash
sudo install -o root -g root -m 0755 \
  scripts/publish-wic-release.sh \
  /usr/local/libexec/wic-netboot/publish-wic-release.sh

sudo install -o root -g root -m 0755 \
  scripts/prepare-board-rootfs.sh \
  /usr/local/libexec/wic-netboot/prepare-board-rootfs.sh
```

Do not let Jenkins replace a root\-executed script immediately before calling it\. Review and install changes separately so the sudo allowlist applies to trusted code\.

Create `/etc/sudoers.d/wic-netboot` with `visudo -f /etc/sudoers.d/wic-netboot`:

```sudoers
jenkins-deploy ALL=(root) NOPASSWD: /usr/local/libexec/wic-netboot/publish-wic-release.sh *
jenkins-deploy ALL=(root) NOPASSWD: /usr/local/libexec/wic-netboot/prepare-board-rootfs.sh *
jenkins-deploy ALL=(root) NOPASSWD: /usr/bin/install -m 0644 /tmp/*.uEnv.txt /srv/netboot/boards/*/uEnv.txt
```

Use the actual absolute path returned by `command -v install` on your server\. Sudoers wildcard matching is not a substitute for the validation inside the scripts\.

---

## 14\. Jenkins credentials

Create these credentials in Jenkins:

|Credential ID      |Type           |Purpose                                |
|-------------------|---------------|---------------------------------------|
|`artifactory-token`|Secret text    |Artifactory access token               |
|`boot-server-ssh`  |SSH private key|`jenkins-deploy` account on NetBoot VM |
|`board-ssh`        |SSH private key|Restricted deployment account on boards|

Also configure SSH host keys on the Jenkins agent\. Keep `StrictHostKeyChecking=yes`; do not disable host\-key verification in production\.

The board deployment account needs restricted sudo access to:

```text
install /tmp/uEnv.txt <actual-boot-mount>/uEnv.txt
systemctl reboot
cat /etc/netboot-assignment
```

The exact sudoers entry depends on the real boot mount and command locations\.

---

## 15\. Complete Jenkinsfile

Save as `Jenkinsfile`:

```groovy
pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    parameters {
        choice(name: 'SCRIPT_IMPL', choices: ['python', 'bash'], description: 'Use the Python or Bash implementation')
        string(name: 'PRODUCT', defaultValue: 'product-a', description: 'Product name used in Artifactory')
        choice(name: 'IMAGE_TYPE', choices: ['release', 'debug'], description: 'Yocto image type')
        string(name: 'VERSION', defaultValue: '', description: 'Immutable build/version, for example 2.5.0-42')
        string(name: 'BOARD_ID', defaultValue: 'board-01', description: 'Stable board identifier')
        string(name: 'BOARD_IP', defaultValue: '192.168.50.20', description: 'Current SSH management address')
        string(name: 'SERVER_IP', defaultValue: '192.168.50.10', description: 'TFTP and NFS server address')
        string(name: 'GATEWAY_IP', defaultValue: '192.168.50.1', description: 'Gateway appropriate to the board VLAN')
        string(name: 'NETMASK', defaultValue: '255.255.255.0', description: 'Static IPv4 netmask')
        string(name: 'BOOT_PARTITION', defaultValue: '1', description: 'WIC boot partition number')
        string(name: 'ROOT_PARTITION', defaultValue: '2', description: 'WIC rootfs partition number')
        string(name: 'KERNEL_PATH', defaultValue: 'Image', description: 'Path relative to WIC boot partition')
        string(name: 'DTB_PATH', defaultValue: 'k3-am625-sk.dtb', description: 'Path relative to WIC boot partition')
        string(name: 'BOARD_BOOT_MOUNT', defaultValue: '/boot', description: 'Actual local boot partition mount on board')
        booleanParam(name: 'PUBLISH_IF_MISSING', defaultValue: true, description: 'Download and extract when release is absent')
        booleanParam(name: 'REBOOT_BOARD', defaultValue: true, description: 'Reboot after installing uEnv.txt')
        booleanParam(name: 'HEALTH_CHECK', defaultValue: true, description: 'Wait for SSH and verify assignment')
    }

    environment {
        ARTIFACTORY_BASE = 'https://artifactory.example.com/artifactory'
        ARTIFACTORY_REPO = 'yocto-images'
        BOOT_SERVER = 'jenkins-deploy@192.168.50.10'
        NETBOOT_ROOT = '/srv/netboot'
        BOARD_USER = 'netboot-deploy'
    }

    stages {
        stage('Validate parameters') {
            steps {
                script {
                    def safeName = ~/^[A-Za-z0-9][A-Za-z0-9._-]*$/
                    if (!(params.PRODUCT ==~ safeName)) { error('Invalid PRODUCT') }
                    if (!(params.VERSION ==~ safeName)) { error('Invalid VERSION') }
                    if (!(params.BOARD_ID ==~ safeName)) { error('Invalid BOARD_ID') }
                    if (!(params.IMAGE_TYPE in ['release', 'debug'])) { error('Invalid IMAGE_TYPE') }
                    if (!(params.BOOT_PARTITION ==~ /^[0-9]+$/)) { error('Invalid BOOT_PARTITION') }
                    if (!(params.ROOT_PARTITION ==~ /^[0-9]+$/)) { error('Invalid ROOT_PARTITION') }
                    if (!(params.KERNEL_PATH ==~ /^[A-Za-z0-9._\/-]+$/)) { error('Invalid KERNEL_PATH') }
                    if (!(params.DTB_PATH ==~ /^[A-Za-z0-9._\/-]+$/)) { error('Invalid DTB_PATH') }
                    if (!(params.BOARD_BOOT_MOUNT ==~ /^\/[A-Za-z0-9._\/-]+$/)) { error('Invalid BOARD_BOOT_MOUNT') }
                }
            }
        }

        stage('Determine artifact') {
            steps {
                script {
                    env.WIC_NAME = "${params.PRODUCT}-${params.IMAGE_TYPE}-${params.VERSION}.wic"
                    env.ARTIFACT_RELATIVE = "${params.PRODUCT}/${params.VERSION}/${env.WIC_NAME}"
                    env.RELEASE_DIR = "${env.NETBOOT_ROOT}/releases/${params.PRODUCT}/${params.IMAGE_TYPE}/${params.VERSION}"
                    env.STAGING_DIR = "${env.NETBOOT_ROOT}/staging/${env.BUILD_TAG}"
                    if (params.SCRIPT_IMPL == 'python') {
                        env.PUBLISH_TOOL = '/usr/local/libexec/wic-netboot/publish_wic_release.py'
                        env.PREPARE_TOOL = '/usr/local/libexec/wic-netboot/prepare_board_rootfs.py'
                    } else {
                        env.PUBLISH_TOOL = '/usr/local/libexec/wic-netboot/publish-wic-release.sh'
                        env.PREPARE_TOOL = '/usr/local/libexec/wic-netboot/prepare-board-rootfs.sh'
                    }
                }
                echo "Artifact: ${env.ARTIFACTORY_REPO}/${env.ARTIFACT_RELATIVE}"
            }
        }

        stage('Check release cache') {
            steps {
                sshagent(credentials: ['boot-server-ssh']) {
                    script {
                        env.RELEASE_EXISTS = sh(
                            returnStatus: true,
                            script: '''ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" "test -s '$RELEASE_DIR/Image' -a -s '$RELEASE_DIR/board.dtb' -a -d '$RELEASE_DIR/rootfs/etc'"'''
                        ) == 0 ? 'true' : 'false'
                    }
                }
                echo "Release already extracted: ${env.RELEASE_EXISTS}"
            }
        }

        stage('Download and verify WIC') {
            when {
                allOf {
                    expression { env.RELEASE_EXISTS != 'true' }
                    expression { params.PUBLISH_IF_MISSING }
                }
            }
            steps {
                withCredentials([string(credentialsId: 'artifactory-token', variable: 'ARTIFACTORY_TOKEN')]) {
                    sh '''
                        set -Eeuo pipefail
                        mkdir -p download

                        curl --fail --location --retry 3 \
                          -H "Authorization: Bearer $ARTIFACTORY_TOKEN" \
                          -o "download/$WIC_NAME" \
                          "$ARTIFACTORY_BASE/$ARTIFACTORY_REPO/$ARTIFACT_RELATIVE"

                        curl --fail --location --retry 3 \
                          -H "Authorization: Bearer $ARTIFACTORY_TOKEN" \
                          -o "download/$WIC_NAME.sha256" \
                          "$ARTIFACTORY_BASE/$ARTIFACTORY_REPO/$ARTIFACT_RELATIVE.sha256"

                        expected=$(awk '{print $1}' "download/$WIC_NAME.sha256")
                        actual=$(sha256sum "download/$WIC_NAME" | awk '{print $1}')
                        test -n "$expected"
                        test "$expected" = "$actual"
                    '''
                }
            }
        }

        stage('Publish immutable release') {
            when {
                allOf {
                    expression { env.RELEASE_EXISTS != 'true' }
                    expression { params.PUBLISH_IF_MISSING }
                }
            }
            steps {
                sshagent(credentials: ['boot-server-ssh']) {
                    sh '''
                        set -Eeuo pipefail
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" "mkdir -p '$STAGING_DIR'"
                        scp -o StrictHostKeyChecking=yes "download/$WIC_NAME" "$BOOT_SERVER:$STAGING_DIR/$WIC_NAME"
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
                          "sudo '$PUBLISH_TOOL' \
                            '$STAGING_DIR/$WIC_NAME' '$PRODUCT' '$IMAGE_TYPE' '$VERSION' \
                            '$BOOT_PARTITION' '$ROOT_PARTITION' '$KERNEL_PATH' '$DTB_PATH'"
                    '''
                }
            }
        }

        stage('Require release') {
            steps {
                sshagent(credentials: ['boot-server-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
                          "test -s '$RELEASE_DIR/Image' && test -s '$RELEASE_DIR/board.dtb' && test -d '$RELEASE_DIR/rootfs/etc'"
                    '''
                }
            }
        }

        stage('Prepare board rootfs') {
            steps {
                sshagent(credentials: ['boot-server-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
                          "sudo '$PREPARE_TOOL' '$PRODUCT' '$IMAGE_TYPE' '$VERSION' '$BOARD_ID'"
                    '''
                }
            }
        }

        stage('Generate and record uEnv.txt') {
            steps {
                sh '''
                    set -Eeuo pipefail
                    if [[ "$SCRIPT_IMPL" == python ]]; then
                        python3 scripts/render_uenv.py templates/uEnv.txt.template uEnv.txt \
                          "$BOARD_ID" "$PRODUCT" "$IMAGE_TYPE" "$VERSION" \
                          "$BOARD_IP" "$SERVER_IP" "$GATEWAY_IP" "$NETMASK"
                    else
                        scripts/render-uenv.sh templates/uEnv.txt.template uEnv.txt \
                          "$BOARD_ID" "$PRODUCT" "$IMAGE_TYPE" "$VERSION" \
                          "$BOARD_IP" "$SERVER_IP" "$GATEWAY_IP" "$NETMASK"
                    fi
                '''
                archiveArtifacts artifacts: 'uEnv.txt', fingerprint: true
                sshagent(credentials: ['boot-server-ssh']) {
                    sh '''
                        set -Eeuo pipefail
                        scp -o StrictHostKeyChecking=yes uEnv.txt "$BOOT_SERVER:/tmp/$BOARD_ID.uEnv.txt"
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
                          "sudo /usr/bin/install -m 0644 '/tmp/$BOARD_ID.uEnv.txt' '$NETBOOT_ROOT/boards/$BOARD_ID/uEnv.txt'"
                    '''
                }
            }
        }

        stage('Install uEnv.txt on board') {
            steps {
                sshagent(credentials: ['board-ssh']) {
                    sh '''
                        set -Eeuo pipefail
                        scp -o StrictHostKeyChecking=yes uEnv.txt "$BOARD_USER@$BOARD_IP:/tmp/uEnv.txt"
                        ssh -o StrictHostKeyChecking=yes "$BOARD_USER@$BOARD_IP" \
                          "test -d '$BOARD_BOOT_MOUNT' && sudo install -m 0644 /tmp/uEnv.txt '$BOARD_BOOT_MOUNT/uEnv.txt' && sync"
                    '''
                }
            }
        }

        stage('Reboot') {
            when { expression { params.REBOOT_BOARD } }
            steps {
                sshagent(credentials: ['board-ssh']) {
                    sh '''
                        ssh -o StrictHostKeyChecking=yes "$BOARD_USER@$BOARD_IP" 'sudo systemctl reboot' || true
                    '''
                }
            }
        }

        stage('Health check') {
            when {
                allOf {
                    expression { params.REBOOT_BOARD }
                    expression { params.HEALTH_CHECK }
                }
            }
            steps {
                sshagent(credentials: ['board-ssh']) {
                    sh '''
                        set -Eeuo pipefail
                        success=false
                        for attempt in $(seq 1 36); do
                            if ssh -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=yes \
                              "$BOARD_USER@$BOARD_IP" \
                              "grep -qx 'BOARD_ID=$BOARD_ID' /etc/netboot-assignment && \
                               grep -qx 'PRODUCT=$PRODUCT' /etc/netboot-assignment && \
                               grep -qx 'IMAGE_TYPE=$IMAGE_TYPE' /etc/netboot-assignment && \
                               grep -qx 'VERSION=$VERSION' /etc/netboot-assignment"; then
                                success=true
                                break
                            fi
                            sleep 5
                        done
                        test "$success" = true
                    '''
                }
            }
        }
    }

    post {
        always {
            sshagent(credentials: ['boot-server-ssh']) {
                sh '''
                    if test -n "${STAGING_DIR:-}"; then
                        ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" "rm -rf -- '$STAGING_DIR'" || true
                    fi
                '''
            }
            deleteDir()
        }
        success {
            echo "${params.BOARD_ID} booted ${params.PRODUCT}/${params.IMAGE_TYPE}/${params.VERSION}"
        }
        failure {
            echo 'Deployment failed. Use the serial console if the board did not return after uEnv.txt installation.'
        }
    }
}
```

### Important cleanup hardening

The `STAGING_DIR` is derived from Jenkins `BUILD_TAG`, not user input\. Still, for production, replace the cleanup SSH command with a small root\-owned cleanup script that validates the path is directly beneath `/srv/netboot/staging`\. Never permit arbitrary `rm -rf` through sudo\.

---

## 16\. Artifactory naming convention

The Jenkinsfile expects:

```text
<repository>/<product>/<version>/<product>-<image-type>-<version>.wic
```

Example:

```text
yocto-images/product-a/2.5.0-42/product-a-release-2.5.0-42.wic
yocto-images/product-a/2.5.0-42/product-a-release-2.5.0-42.wic.sha256
yocto-images/product-a/2.5.0-42/product-a-debug-2.5.0-42.wic
yocto-images/product-a/2.5.0-42/product-a-debug-2.5.0-42.wic.sha256
```

The checksum file can contain either only the hash or standard `sha256sum` output\. Jenkins reads the first field\.

If your Artifactory layout differs, change only `ARTIFACT_RELATIVE` and `WIC_NAME` in the `Determine artifact` stage\.

---

## 17\. Create the Jenkins job

1. Push this repository to Git\.
2. Create a Jenkins **Pipeline** or **Multibranch Pipeline** job\.
3. Point it to the Git repository\.
4. Set the script path to `Jenkinsfile`\.
5. Add the three credentials from Section 14\.
6. Run once with `REBOOT_BOARD=false` to validate download, extraction, and generated `uEnv.txt`\.
7. Manually inspect the archived `uEnv.txt`\.
8. Test the commands manually at the serial U\-Boot prompt\.
9. Enable board installation and reboot only after the manual boot succeeds\.

---

## 18\. Trigger from Jenkins UI

Choose **Build with Parameters** and enter:

```text
PRODUCT=product-a
SCRIPT_IMPL=python
IMAGE_TYPE=release
VERSION=2.5.0-42
BOARD_ID=board-01
BOARD_IP=192.168.50.20
SERVER_IP=192.168.50.10
PUBLISH_IF_MISSING=true
REBOOT_BOARD=true
HEALTH_CHECK=true
```

---

## 19\. Trigger with Jenkins CLI

```bash
java -jar jenkins-cli.jar \
  -s https://jenkins.example.com/ \
  -auth "$JENKINS_USER:$JENKINS_API_TOKEN" \
  build wic-netboot-deploy \
  -p SCRIPT_IMPL=python \
  -p PRODUCT=product-a \
  -p IMAGE_TYPE=release \
  -p VERSION=2.5.0-42 \
  -p BOARD_ID=board-01 \
  -p BOARD_IP=192.168.50.20 \
  -p SERVER_IP=192.168.50.10 \
  -p GATEWAY_IP=192.168.50.1 \
  -p NETMASK=255.255.255.0 \
  -p BOOT_PARTITION=1 \
  -p ROOT_PARTITION=2 \
  -p KERNEL_PATH=Image \
  -p DTB_PATH=k3-am625-sk.dtb \
  -p BOARD_BOOT_MOUNT=/boot \
  -p PUBLISH_IF_MISSING=true \
  -p REBOOT_BOARD=true \
  -p HEALTH_CHECK=true \
  -s -v
```

Use an API token rather than a Jenkins account password\.

---

## 20\. Trigger with HTTP API

```bash
curl --fail-with-body \
  --user "$JENKINS_USER:$JENKINS_API_TOKEN" \
  -X POST \
  'https://jenkins.example.com/job/wic-netboot-deploy/buildWithParameters' \
  --data-urlencode 'SCRIPT_IMPL=python' \
  --data-urlencode 'PRODUCT=product-a' \
  --data-urlencode 'IMAGE_TYPE=release' \
  --data-urlencode 'VERSION=2.5.0-42' \
  --data-urlencode 'BOARD_ID=board-01' \
  --data-urlencode 'BOARD_IP=192.168.50.20' \
  --data-urlencode 'SERVER_IP=192.168.50.10' \
  --data-urlencode 'GATEWAY_IP=192.168.50.1' \
  --data-urlencode 'NETMASK=255.255.255.0' \
  --data-urlencode 'BOOT_PARTITION=1' \
  --data-urlencode 'ROOT_PARTITION=2' \
  --data-urlencode 'KERNEL_PATH=Image' \
  --data-urlencode 'DTB_PATH=k3-am625-sk.dtb' \
  --data-urlencode 'BOARD_BOOT_MOUNT=/boot' \
  --data-urlencode 'PUBLISH_IF_MISSING=true' \
  --data-urlencode 'REBOOT_BOARD=true' \
  --data-urlencode 'HEALTH_CHECK=true'
```

---

## 21\. Manual U\-Boot test before automation

At the serial U\-Boot prompt:

```bash
setenv ipaddr 192.168.50.20
setenv serverip 192.168.50.10
setenv gatewayip 192.168.50.1
setenv netmask 255.255.255.0
setenv autoload no

ping ${serverip}

tftpboot ${kernel_addr_r} releases/product-a/release/2.5.0-42/Image
tftpboot ${fdt_addr_r} releases/product-a/release/2.5.0-42/board.dtb

setenv bootargs "console=${console} root=/dev/nfs rw rootwait nfsroot=${serverip}:/srv/netboot/boards/board-01/deployments/product-a-release-2.5.0-42/rootfs,vers=3,tcp ip=${ipaddr}:${serverip}:${gatewayip}:${netmask}::eth0:off"

booti ${kernel_addr_r} - ${fdt_addr_r}
```

If TFTP sometimes requires multiple attempts, solve that in a tested U\-Boot retry script before enabling unattended deployments\. Do not assume Bash loops will work inside `uEnv.txt`; U\-Boot command syntax and available commands depend on its build configuration\.

---

## 22\. Roll back a board

Rollback is simply another assignment to an older version\. If the older immutable release and board deployment are still present, Jenkins will reuse them\.

```bash
java -jar jenkins-cli.jar \
  -s https://jenkins.example.com/ \
  -auth "$JENKINS_USER:$JENKINS_API_TOKEN" \
  build wic-netboot-deploy \
  -p SCRIPT_IMPL=python \
  -p PRODUCT=product-a \
  -p IMAGE_TYPE=release \
  -p VERSION=2.4.3-38 \
  -p BOARD_ID=board-01 \
  -p BOARD_IP=192.168.50.20 \
  -p PUBLISH_IF_MISSING=true \
  -p REBOOT_BOARD=true \
  -p HEALTH_CHECK=true \
  -s -v
```

Because every board deployment directory is versioned, rollback does not overwrite the currently running rootfs\.

---

## 23\. Retention policy

Keep permanently in Artifactory:

- every approved release WIC;
- debug WICs required by your engineering retention policy;
- SHA\-256 checksum and build metadata\.

Keep on the NetBoot server:

- releases currently assigned to boards;
- at least the previous two known\-good releases;
- current debug releases under active investigation;
- corresponding per\-board deployments\.

Before deleting an extracted release, verify no board `uEnv.txt`, `current` symlink, or deployment manifest references it\. Delete board runtime roots only while the affected board is shut down or confirmed to be using another deployment\.

---

## 24\. Troubleshooting

### Jenkins receives HTTP 401 or 403

Verify the token has read permission for the Artifactory repository and that the repository/path are correct\. Do not print the token or enable shell tracing around credential use\.

### Checksum download fails

Ensure the build publishing process uploads `<image>.wic.sha256`\. Do not disable checksum verification merely to continue the pipeline\.

### WIC partition does not exist

Inspect it:

```bash
fdisk -l image.wic
losetup --find --show --partscan --read-only image.wic
lsblk -f /dev/loop0
```

Then detach the loop device:

```bash
sudo losetup -d /dev/loop0
```

Update `BOOT_PARTITION` and `ROOT_PARTITION` based on the actual image\.

### Kernel or DTB not found

Mount the partitions and locate them:

```bash
find /mnt/wic-boot /mnt/wic-root/boot -maxdepth 5 -type f \
  \( -name Image -o -name zImage -o -name '*.dtb' \)
```

Update `KERNEL_PATH` or `DTB_PATH` to the path relative to the WIC boot filesystem\.

### Kernel reports that it cannot find init

Check the board\-specific NFS root:

```bash
ls -l /srv/netboot/boards/board-01/deployments/product-a-release-2.5.0-42/rootfs/sbin/init
file /srv/netboot/boards/board-01/deployments/product-a-release-2.5.0-42/rootfs/sbin/init
```

Also verify:

- ownership and symlinks were preserved by `rsync -aHAX --numeric-ids`;
- the executable’s dynamic loader exists;
- the kernel has NFS\-root and required filesystem/network support;
- the NFS export allows the board;
- the kernel mounted the intended path rather than an empty directory\.

### TFTP reports file not found

Verify all three views:

```bash
ls -l /srv/netboot/releases/product-a/release/2.5.0-42/Image
ls -l /opt/tftpboot/releases/product-a/release/2.5.0-42/Image
findmnt /opt/tftpboot/releases
```

Then monitor dnsmasq:

```bash
sudo journalctl -u dnsmasq -f
```

### Board does not use the new uEnv\.txt

Verify the file was installed on the partition U\-Boot actually reads:

```bash
findmnt
sudo find /boot /run/media -name uEnv.txt -type f -print 2>/dev/null
```

At the U\-Boot prompt inspect:

```bash
printenv uenvcmd board_id product image_type version
```

Your board vendor’s default boot environment must actually import `uEnv.txt`; merely placing the file on a partition does not guarantee it is loaded\.

---

## 25\. Python equivalents

The Python implementations below deliberately keep the same positional arguments, validation rules, output paths, and safety model as the Bash scripts\. They use Python for orchestration but still call Linux utilities such as `losetup`, `mount`, `umount`, and `rsync`; Python’s standard library does not replace those privileged filesystem operations\.

Use Python 3\.9 or newer\. No third\-party Python packages are required\.

### 25\.1 Python WIC publication script

Save as `scripts/publish_wic_release.py`:

```python
#!/usr/bin/env python3
"""Extract one WIC into an immutable TFTP/NFS NetBoot release."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone


NETBOOT_ROOT = Path("/srv/netboot")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def run(*args: str, capture: bool = False) -> subprocess.CompletedProcess[str]:
    """Run a required system command and raise immediately when it fails."""
    return subprocess.run(
        args,
        check=True,
        text=True,
        stdout=subprocess.PIPE if capture else None,
    )


def mounted(path: Path) -> bool:
    """Return True when path is currently a mount point."""
    return subprocess.run(
        ["mountpoint", "-q", str(path)], check=False
    ).returncode == 0


def sha256(path: Path) -> str:
    """Calculate the source WIC digest without loading the whole image in RAM."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def safe_component(label: str, value: str) -> str:
    """Reject path traversal and unsupported directory-name characters."""
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Publish an immutable NetBoot release from a WIC image."
    )
    parser.add_argument("wic", type=Path)
    parser.add_argument("product")
    parser.add_argument("image_type", choices=("release", "debug"))
    parser.add_argument("version")
    parser.add_argument("boot_partition", type=int)
    parser.add_argument("root_partition", type=int)
    parser.add_argument("kernel_path")
    parser.add_argument("dtb_path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    # Validate every value used to construct a server-side directory.
    product = safe_component("product", args.product)
    version = safe_component("version", args.version)
    image_type = args.image_type

    if args.boot_partition < 1 or args.root_partition < 1:
        raise ValueError("Partition numbers must be positive integers")
    if not args.wic.is_file():
        raise FileNotFoundError(f"WIC not found: {args.wic}")

    release_dir = NETBOOT_ROOT / "releases" / product / image_type / version
    release_parent = release_dir.parent
    if release_dir.exists():
        raise FileExistsError(f"Immutable release already exists: {release_dir}")

    release_parent.mkdir(parents=True, exist_ok=True)
    mount_dir = Path(tempfile.mkdtemp(prefix="wic-mount.", dir="/tmp"))
    boot_mount = mount_dir / "boot"
    root_mount = mount_dir / "root"
    boot_mount.mkdir()
    root_mount.mkdir()

    # Build beside the final release so os.rename() publishes on one filesystem.
    work_dir: Path | None = Path(
        tempfile.mkdtemp(prefix=f".publish-{version}.", dir=release_parent)
    )
    (work_dir / "rootfs").mkdir()
    loop_device: str | None = None

    try:
        # Treat the WIC as a read-only virtual disk and scan its partitions.
        result = run(
            "losetup", "--find", "--show", "--partscan", "--read-only",
            str(args.wic), capture=True
        )
        loop_device = result.stdout.strip()
        boot_device = Path(f"{loop_device}p{args.boot_partition}")
        root_device = Path(f"{loop_device}p{args.root_partition}")

        if not boot_device.exists():
            raise FileNotFoundError(f"Boot partition not found: {boot_device}")
        if not root_device.exists():
            raise FileNotFoundError(f"Root partition not found: {root_device}")

        # Source partitions are never mounted writable.
        run("mount", "-o", "ro", str(boot_device), str(boot_mount))
        run("mount", "-o", "ro", str(root_device), str(root_mount))

        kernel_relative = args.kernel_path.lstrip("/")
        dtb_relative = args.dtb_path.lstrip("/")
        kernel_source = boot_mount / kernel_relative
        dtb_source = boot_mount / dtb_relative

        # Some Yocto layouts store these beneath /boot in the root partition.
        if not kernel_source.is_file():
            kernel_source = root_mount / "boot" / kernel_relative
        if not dtb_source.is_file():
            dtb_source = root_mount / "boot" / dtb_relative

        if not kernel_source.is_file():
            raise FileNotFoundError(f"Kernel not found: {args.kernel_path}")
        if not dtb_source.is_file():
            raise FileNotFoundError(f"DTB not found: {args.dtb_path}")
        if not ((root_mount / "sbin/init").exists() or (root_mount / "init").exists()):
            raise FileNotFoundError("Rootfs contains neither /sbin/init nor /init")

        # Normalize TFTP filenames for every product.
        shutil.copy2(kernel_source, work_dir / "Image")
        shutil.copy2(dtb_source, work_dir / "board.dtb")
        os.chmod(work_dir / "Image", 0o644)
        os.chmod(work_dir / "board.dtb", 0o644)

        # rsync preserves owners, modes, links, ACLs, xattrs, and numeric IDs.
        run(
            "rsync", "-aHAX", "--numeric-ids",
            f"{root_mount}/", f"{work_dir / 'rootfs'}/"
        )

        (work_dir / "source.wic.sha256").write_text(
            sha256(args.wic) + "\n", encoding="utf-8"
        )
        created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        (work_dir / "manifest.env").write_text(
            "\n".join(
                (
                    f"PRODUCT={product}",
                    f"IMAGE_TYPE={image_type}",
                    f"VERSION={version}",
                    f"SOURCE_WIC={args.wic.name}",
                    f"KERNEL_PATH={args.kernel_path}",
                    f"DTB_PATH={args.dtb_path}",
                    f"CREATED_UTC={created}",
                    "",
                )
            ),
            encoding="utf-8",
        )

        if (work_dir / "Image").stat().st_size == 0:
            raise RuntimeError("Extracted kernel is empty")
        if (work_dir / "board.dtb").stat().st_size == 0:
            raise RuntimeError("Extracted DTB is empty")
        if not (work_dir / "rootfs/etc").is_dir():
            raise RuntimeError("Extracted rootfs has no /etc directory")

        # Atomic publication: an incomplete release never appears at final path.
        os.rename(work_dir, release_dir)
        work_dir = None
        print(f"Published {release_dir}")
        return 0
    finally:
        # Cleanup runs after success, exceptions, or interruption.
        if mounted(boot_mount):
            subprocess.run(["umount", str(boot_mount)], check=False)
        if mounted(root_mount):
            subprocess.run(["umount", str(root_mount)], check=False)
        if loop_device:
            subprocess.run(["losetup", "-d", loop_device], check=False)
        shutil.rmtree(mount_dir, ignore_errors=True)
        if work_dir is not None:
            shutil.rmtree(work_dir, ignore_errors=True)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
```

### 25\.2 Python per\-board rootfs script

Save as `scripts/prepare_board_rootfs.py`:

```python
#!/usr/bin/env python3
"""Create or select one writable, versioned NFS root for a board."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


NETBOOT_ROOT = Path("/srv/netboot")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def safe_component(label: str, value: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare one board's NFS rootfs.")
    parser.add_argument("product")
    parser.add_argument("image_type", choices=("release", "debug"))
    parser.add_argument("version")
    parser.add_argument("board_id")
    return parser.parse_args()


def replace_symlink(link: Path, relative_target: str) -> None:
    """Replace current using a temporary symlink and atomic rename."""
    temporary_link = link.with_name(f".{link.name}.{os.getpid()}")
    temporary_link.unlink(missing_ok=True)
    temporary_link.symlink_to(relative_target)
    os.replace(temporary_link, link)


def main() -> int:
    args = parse_args()
    product = safe_component("product", args.product)
    version = safe_component("version", args.version)
    board_id = safe_component("board ID", args.board_id)
    image_type = args.image_type

    release = NETBOOT_ROOT / "releases" / product / image_type / version
    if not (release / "Image").is_file() or not (release / "board.dtb").is_file():
        raise FileNotFoundError(f"Incomplete release: {release}")
    if not (release / "rootfs/etc").is_dir():
        raise FileNotFoundError(f"Release rootfs is incomplete: {release}")

    deployment_name = f"{product}-{image_type}-{version}"
    board_dir = NETBOOT_ROOT / "boards" / board_id
    deployments = board_dir / "deployments"
    deployment = deployments / deployment_name
    lock_path = NETBOOT_ROOT / "locks" / f"{board_id}.lock"

    deployments.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    # Keep the file open while flock is held. Another build for this board waits.
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)

        if not (deployment / "rootfs").is_dir():
            temporary = Path(
                tempfile.mkdtemp(prefix=f".prepare-{deployment_name}.", dir=deployments)
            )
            try:
                rootfs = temporary / "rootfs"
                rootfs.mkdir()

                # Preserve the Linux metadata required by the extracted userspace.
                subprocess.run(
                    [
                        "rsync", "-aHAX", "--numeric-ids",
                        f"{release / 'rootfs'}/", f"{rootfs}/",
                    ],
                    check=True,
                )

                # The Jenkins health check reads this after the board boots.
                created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                assignment = rootfs / "etc/netboot-assignment"
                assignment.parent.mkdir(parents=True, exist_ok=True)
                assignment.write_text(
                    "\n".join(
                        (
                            f"BOARD_ID={board_id}",
                            f"PRODUCT={product}",
                            f"IMAGE_TYPE={image_type}",
                            f"VERSION={version}",
                            f"DEPLOYED_UTC={created}",
                            "",
                        )
                    ),
                    encoding="utf-8",
                )

                # Make the complete rootfs visible in one operation.
                os.rename(temporary, deployment)
                temporary = None
            finally:
                if temporary is not None:
                    shutil.rmtree(temporary, ignore_errors=True)

        # Human-readable pointer only; uEnv.txt boots the exact versioned path.
        replace_symlink(board_dir / "current", f"deployments/{deployment_name}")

    print(f"Prepared {deployment}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
```

### 25\.3 Python uEnv\.txt renderer

Save as `scripts/render_uenv.py`:

```python
#!/usr/bin/env python3
"""Render and validate a board-specific uEnv.txt from the shared template."""

from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import sys


SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
UNRESOLVED = re.compile(r"@@[A-Z_]+@@")


def safe_name(label: str, value: str) -> str:
    if not SAFE_NAME.fullmatch(value):
        raise ValueError(f"Invalid {label}: {value!r}")
    return value


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render uEnv.txt.")
    parser.add_argument("template", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("board_id")
    parser.add_argument("product")
    parser.add_argument("image_type", choices=("release", "debug"))
    parser.add_argument("version")
    parser.add_argument("board_ip")
    parser.add_argument("server_ip")
    parser.add_argument("gateway_ip")
    parser.add_argument("netmask")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    values = {
        "@@BOARD_ID@@": safe_name("board ID", args.board_id),
        "@@PRODUCT@@": safe_name("product", args.product),
        "@@IMAGE_TYPE@@": args.image_type,
        "@@VERSION@@": safe_name("version", args.version),
        "@@BOARD_IP@@": str(ipaddress.IPv4Address(args.board_ip)),
        "@@SERVER_IP@@": str(ipaddress.IPv4Address(args.server_ip)),
        "@@GATEWAY_IP@@": str(ipaddress.IPv4Address(args.gateway_ip)),
        "@@NETMASK@@": str(ipaddress.IPv4Address(args.netmask)),
    }

    text = args.template.read_text(encoding="utf-8")
    for placeholder, value in values.items():
        text = text.replace(placeholder, value)

    if UNRESOLVED.search(text):
        raise ValueError("Rendered uEnv.txt contains unresolved placeholders")
    if "uenvcmd=run netboot\n" not in text + "\n":
        raise ValueError("Rendered uEnv.txt does not enable the netboot command")

    args.output.write_text(text, encoding="utf-8")
    print(f"Rendered {args.output}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
```

### 25\.4 Validate the Python scripts

```bash
python3 -m py_compile \
  scripts/publish_wic_release.py \
  scripts/prepare_board_rootfs.py \
  scripts/render_uenv.py

chmod +x \
  scripts/publish_wic_release.py \
  scripts/prepare_board_rootfs.py \
  scripts/render_uenv.py
```

The compile check validates Python syntax\. It does not mount a WIC or change the server\.

### 25\.5 Install the Python server scripts

Install reviewed copies beside the Bash implementations:

```bash
sudo install -o root -g root -m 0755 \
  scripts/publish_wic_release.py \
  /usr/local/libexec/wic-netboot/publish_wic_release.py

sudo install -o root -g root -m 0755 \
  scripts/prepare_board_rootfs.py \
  /usr/local/libexec/wic-netboot/prepare_board_rootfs.py
```

Add the Python commands to `/etc/sudoers.d/wic-netboot` using `visudo`:

```sudoers
jenkins-deploy ALL=(root) NOPASSWD: /usr/local/libexec/wic-netboot/publish_wic_release.py *
jenkins-deploy ALL=(root) NOPASSWD: /usr/local/libexec/wic-netboot/prepare_board_rootfs.py *
```

Both files use a Python shebang, so Jenkins may execute them directly\. Alternatively, allow an exact `/usr/bin/python3 <trusted-script>` command in sudoers, but do not grant unrestricted passwordless access to `/usr/bin/python3`\.

### 25\.6 Let Jenkins select Bash or Python

The complete Jenkinsfile in Section 15 already includes this selector\. If you are updating an older Bash\-only copy, add this build parameter:

```groovy
choice(
    name: 'SCRIPT_IMPL',
    choices: ['python', 'bash'],
    description: 'Implementation used for extraction, board-rootfs preparation, and uEnv rendering'
)
```

Add these values in the `Determine artifact` stage:

```groovy
if (params.SCRIPT_IMPL == 'python') {
    env.PUBLISH_TOOL = '/usr/local/libexec/wic-netboot/publish_wic_release.py'
    env.PREPARE_TOOL = '/usr/local/libexec/wic-netboot/prepare_board_rootfs.py'
} else {
    env.PUBLISH_TOOL = '/usr/local/libexec/wic-netboot/publish-wic-release.sh'
    env.PREPARE_TOOL = '/usr/local/libexec/wic-netboot/prepare-board-rootfs.sh'
}
```

Change the remote publication command to:

```groovy
ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
  "sudo '$PUBLISH_TOOL' \
    '$STAGING_DIR/$WIC_NAME' '$PRODUCT' '$IMAGE_TYPE' '$VERSION' \
    '$BOOT_PARTITION' '$ROOT_PARTITION' '$KERNEL_PATH' '$DTB_PATH'"
```

Change the board\-rootfs preparation command to:

```groovy
ssh -o StrictHostKeyChecking=yes "$BOOT_SERVER" \
  "sudo '$PREPARE_TOOL' '$PRODUCT' '$IMAGE_TYPE' '$VERSION' '$BOARD_ID'"
```

Change the local renderer call to:

```bash
if [[ "$SCRIPT_IMPL" == python ]]; then
    python3 scripts/render_uenv.py templates/uEnv.txt.template uEnv.txt \
      "$BOARD_ID" "$PRODUCT" "$IMAGE_TYPE" "$VERSION" \
      "$BOARD_IP" "$SERVER_IP" "$GATEWAY_IP" "$NETMASK"
else
    scripts/render-uenv.sh templates/uEnv.txt.template uEnv.txt \
      "$BOARD_ID" "$PRODUCT" "$IMAGE_TYPE" "$VERSION" \
      "$BOARD_IP" "$SERVER_IP" "$GATEWAY_IP" "$NETMASK"
fi
```

The two implementations produce the same server paths and `uEnv.txt`\. Do not run Bash for publication and Python simultaneously against the same release\. Immutable\-release checks and per\-board locking provide protection, but one implementation per Jenkins build keeps audit logs clear\.

---

## 26\. Production improvements

After the first working implementation:

1. Move board IP, DTB, boot mount, console, and board revision into a reviewed inventory file\.
2. Use a Jenkins lock per `BOARD_ID` instead of disabling all concurrent deployments\.
3. Add serial\-console capture or remote power control for recovery\.
4. Add U\-Boot boot\-count fallback to a known\-good local image\.
5. Add a stable local `uEnv.txt` that downloads a server\-side board assignment script, eliminating repeated writes to the board boot partition\.
6. Query Artifactory build properties so Jenkins can present approved versions instead of free\-text versions\.
7. Record the Artifactory build name, build number, commit SHA, and checksum in `manifest.env`\.
8. Sign release metadata and verify it in the pipeline if your environment requires stronger provenance\.

---

## 27\. Final safety checklist

Before allowing Jenkins to reboot a board automatically, verify:

- the exact WIC partition numbers;
- the correct DTB for that board revision;
- `booti` versus `bootz`;
- U\-Boot imports the intended `uEnv.txt`;
- the board can TFTP both files manually;
- the kernel can mount the board\-specific NFS root manually;
- `/sbin/init` and its loader work;
- the board boot mount is the real U\-Boot\-readable partition;
- Jenkins SSH host keys are pinned;
- Artifactory tokens and SSH keys are stored only in Jenkins credentials;
- the board retains a recoverable local boot path or serial\-console access;
- multiple boards never share the same writable rootfs\.

The initial production rule should be: **publish each product/type/version once, never mutate it, and assign boards to exact immutable versions\.**
