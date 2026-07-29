# Troubleshooting dnsmasq TFTP Failures (U-Boot)

This guide walks through diagnosing a `dnsmasq` TFTP server that is reachable (the board can `ping` it) but fails to serve a file (for example, `helloworld.txt`) to U-Boot.

---

## Symptoms

- Board can successfully ping the server.
- U-Boot `tftp` command fails.
- `journalctl -u dnsmasq` reports a failure serving the requested file.
- File permissions have already been opened (even `777`).
- TFTP root is:

```text
/opt/tftpboot
```

---

# Step 1 – Verify dnsmasq Configuration

Check the active configuration:

```bash
sudo grep -RniE 'enable-tftp|tftp-root' \
    /etc/dnsmasq.conf /etc/dnsmasq.d/
```

Expected configuration:

```ini
enable-tftp
tftp-root=/opt/tftpboot
```

Validate the configuration:

```bash
sudo dnsmasq --test
```

Restart the service:

```bash
sudo systemctl restart dnsmasq
sudo systemctl status dnsmasq
```

---

# Step 2 – Watch the Logs

Monitor dnsmasq while attempting the transfer:

```bash
sudo journalctl -fu dnsmasq
```

In another terminal (or from your serial console), attempt:

```bash
tftp ${loadaddr} helloworld.txt
```

The log output is often the fastest way to identify the failure.

---

# Step 3 – Verify the File Exists

```bash
ls -l /opt/tftpboot
```

Example:

```text
helloworld.txt
```

Do **not** request:

```text
/opt/tftpboot/helloworld.txt
```

From U-Boot, request only:

```bash
tftp ${loadaddr} helloworld.txt
```

because dnsmasq automatically prepends the configured `tftp-root`.

---

# Step 4 – Verify SELinux Context

If permissions are already open and dnsmasq still cannot read the file, SELinux is the most likely cause.

View the current labels:

```bash
ls -ldZ /opt/tftpboot
ls -lZ /opt/tftpboot/helloworld.txt
```

The directory and files should have the type:

```text
tftpdir_t
```

Example:

```text
system_u:object_r:tftpdir_t:s0
```

---

# Step 5 – Permanently Label the TFTP Directory

Since `/opt/tftpboot` is not the default TFTP location, create a persistent SELinux rule:

```bash
sudo semanage fcontext -a -t tftpdir_t '/opt/tftpboot(/.*)?'
```

If the rule already exists:

```bash
sudo semanage fcontext -m -t tftpdir_t '/opt/tftpboot(/.*)?'
```

Apply the labels:

```bash
sudo restorecon -RFv /opt/tftpboot
```

Verify:

```bash
ls -ldZ /opt/tftpboot
ls -lZ /opt/tftpboot/helloworld.txt
```

---

# Step 6 – Check for SELinux Denials

Immediately after attempting the TFTP transfer:

```bash
sudo ausearch -m AVC,USER_AVC -ts recent
```

or

```bash
sudo journalctl -k | grep -i 'avc.*denied'
```

If SELinux is blocking access, you'll see an AVC denial mentioning:

- dnsmasq
- tftp
- /opt/tftpboot
- helloworld.txt

---

# Step 7 – Verify dnsmasq Can Access the File

Confirm the file exists:

```bash
realpath /opt/tftpboot/helloworld.txt
```

Check permissions:

```bash
ls -l /opt/tftpboot/helloworld.txt
```

---

# Step 8 – Confirm dnsmasq Owns UDP Port 69

```bash
sudo ss -lunp | grep ':69'
```

Expected:

```text
dnsmasq
```

If another TFTP daemon is running (such as `tftpd-hpa`), disable it.

---

# Step 9 – Verify U-Boot Variables

From the serial console:

```bash
printenv ipaddr
printenv serverip
printenv loadaddr
```

If necessary:

```bash
setenv serverip <SERVER_IP>
setenv ipaddr <BOARD_IP>
```

Test connectivity:

```bash
ping ${serverip}
```

Then:

```bash
tftp ${loadaddr} helloworld.txt
```

---

# Step 10 – Examine Downloaded Memory

If the transfer succeeds:

```bash
md.b ${loadaddr} 40
```

You should see the ASCII text of the file in memory.

---

# Helpful Diagnostic Commands

## View dnsmasq logs

```bash
sudo journalctl -fu dnsmasq
```

## Validate dnsmasq configuration

```bash
sudo dnsmasq --test
```

## Restart dnsmasq

```bash
sudo systemctl restart dnsmasq
```

## Check SELinux labels

```bash
ls -ldZ /opt/tftpboot
ls -lZ /opt/tftpboot/*
```

## Show SELinux file context rules

```bash
sudo semanage fcontext -l | grep '/opt/tftpboot'
```

## Restore SELinux labels

```bash
sudo restorecon -RFv /opt/tftpboot
```

## Search for SELinux denials

```bash
sudo ausearch -m AVC,USER_AVC -ts recent
```

## Check UDP port 69

```bash
sudo ss -lunp | grep ':69'
```

---

# Common Root Causes

| Problem | Symptoms | Fix |
|----------|----------|-----|
| Incorrect `tftp-root` | File not found | Verify `tftp-root` matches the directory |
| Wrong filename requested | "File not found" | Request only `helloworld.txt` from U-Boot |
| SELinux labels | Permissions appear correct but access fails | Label `/opt/tftpboot` as `tftpdir_t` and run `restorecon` |
| Another TFTP server running | Intermittent failures or no response | Ensure `dnsmasq` owns UDP port 69 |
| dnsmasq configuration error | Service won't start | Run `sudo dnsmasq --test` |
| Firewall | Timeouts | Allow UDP port 69 or temporarily disable the firewall for testing |

---

# Notes

- File permissions (`chmod 777`) do **not** override SELinux policy.
- Always request only the filename from U-Boot; dnsmasq automatically prepends the configured `tftp-root`.
- For non-standard TFTP directories such as `/opt/tftpboot`, a persistent SELinux file context is typically required.
- The combination of `journalctl -fu dnsmasq` and `ausearch` is usually enough to identify the exact cause of a failed transfer.
