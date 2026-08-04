# Fix Jenkins SSH Asking for a Password

This guide configures the `jenkins-netboot` account so Jenkins can SSH into the boot server using a key without entering a password\.

> Creating a Linux user does not automatically enable passwordless SSH. The boot server must contain the public key, and Jenkins must supply the matching private key.

## Authentication flow

```text
Jenkins credential contains private key
                |
                v
Jenkins agent runs ssh as jenkins-netboot
                |
                v
Boot server checks ~/.ssh/authorized_keys
```

## 1\. Confirm the account

Run on the boot server:

```bash
id jenkins-netboot
getent passwd jenkins-netboot
```

The `getent` output should show the home directory as `/home/jenkins-netboot` and a valid shell such as `/bin/bash`\.

If the account does not exist, create it:

```bash
sudo useradd --create-home --shell /bin/bash jenkins-netboot
```

## 2\. Create the SSH key pair

Switch to the deployment account:

```bash
sudo -iu jenkins-netboot
```

Create its SSH directory and key pair:

```bash
install -d -m 700 ~/.ssh

ssh-keygen \
    -t ed25519 \
    -f ~/.ssh/jenkins_netboot \
    -C "jenkins-netboot" \
    -N ""
```

This creates:

```text
~/.ssh/jenkins_netboot       Private key—copy this into Jenkins
~/.ssh/jenkins_netboot.pub   Public key—authorize this on the server
```

If these files already exist, do not overwrite them unless you intend to rotate the Jenkins key\.

## 3\. Authorize the public key

Still running as `jenkins-netboot`:

```bash
touch ~/.ssh/authorized_keys

grep -qxF "$(cat ~/.ssh/jenkins_netboot.pub)" ~/.ssh/authorized_keys || \
    cat ~/.ssh/jenkins_netboot.pub >> ~/.ssh/authorized_keys

chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
chmod 600 ~/.ssh/jenkins_netboot
chmod 644 ~/.ssh/jenkins_netboot.pub
```

Confirm that the public key is present:

```bash
cat ~/.ssh/authorized_keys
```

Exit back to your administrator account:

```bash
exit
```

## 4\. Correct ownership and SELinux labels

Run on the boot server:

```bash
sudo chown -R jenkins-netboot:jenkins-netboot \
    /home/jenkins-netboot/.ssh

sudo chmod 700 /home/jenkins-netboot/.ssh
sudo chmod 600 /home/jenkins-netboot/.ssh/authorized_keys
```

On RHEL, Rocky Linux, AlmaLinux, CentOS, or another SELinux system, restore the expected labels:

```bash
sudo restorecon -RFv /home/jenkins-netboot/.ssh
```

Inspect every directory in the path:

```bash
sudo namei -l /home/jenkins-netboot/.ssh/authorized_keys
```

The home directory and SSH files must not be writable by other users\.

## 5\. Confirm the SSH server accepts public keys

Run:

```bash
sudo sshd -T | grep -E \
    '^(pubkeyauthentication|authorizedkeysfile|passwordauthentication)'
```

The important results are:

```text
pubkeyauthentication yes
authorizedkeysfile .ssh/authorized_keys
```

If `pubkeyauthentication` is disabled, edit `/etc/ssh/sshd_config` and ensure it contains:

```text
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
```

Validate the configuration before restarting SSH:

```bash
sudo sshd -t
```

If validation succeeds, restart the appropriate service:

```bash
sudo systemctl restart sshd
```

On Debian or Ubuntu, the service may instead be named `ssh`:

```bash
sudo systemctl restart ssh
```

## 6\. Test using the private key

A plain command such as this may still request a password:

```bash
ssh jenkins-netboot@BOOT_SERVER_IP
```

That happens when the computer running the command does not have or select the private key\. Test by explicitly specifying it:

```bash
chmod 600 ./jenkins_netboot

ssh \
    -vvv \
    -i ./jenkins_netboot \
    -o IdentitiesOnly=yes \
    jenkins-netboot@BOOT_SERVER_IP
```

Replace:

- `./jenkins_netboot` with the path to the private key\.
- `BOOT_SERVER_IP` with the boot server address\.

Successful verbose output will contain messages similar to:

```text
Offering public key
Server accepts key
Authenticated using "publickey"
```

If you generated the key on the boot server and only copied it into Jenkins, a test from your personal computer will still ask for a password because your computer does not possess that private key\.

## 7\. Add the private key to Jenkins

On the boot server, display the private key:

```bash
sudo -iu jenkins-netboot \
    cat /home/jenkins-netboot/.ssh/jenkins_netboot
```

Copy the complete value, including:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

In Jenkins, go to:

```text
Manage Jenkins
  -> Credentials
  -> System
  -> Global credentials
  -> Add Credentials
```

Create the credential with these values:

|Field      |Value                          |
|-----------|-------------------------------|
|Kind       |`SSH Username with private key`|
|ID         |`netboot-server-ssh-key`       |
|Username   |`jenkins-netboot`              |
|Private Key|`Enter directly`               |

Paste the private key and save it\. The username must be `jenkins-netboot`, not the earlier example name `netboot-deploy`\.

## 8\. Test from a Jenkins pipeline

This works without the SSH Agent plugin:

```groovy
pipeline {
    agent any

    environment {
        NETBOOT_SERVER = '192.168.50.10'
    }

    stages {
        stage('Test SSH') {
            steps {
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'netboot-server-ssh-key',
                        keyFileVariable: 'SSH_KEY_FILE',
                        usernameVariable: 'SSH_USERNAME'
                    )
                ]) {
                    sh '''
                        set +x

                        ssh \
                            -vvv \
                            -i "${SSH_KEY_FILE}" \
                            -o IdentitiesOnly=yes \
                            -o StrictHostKeyChecking=accept-new \
                            "${SSH_USERNAME}@${NETBOOT_SERVER}" \
                            'whoami && hostname'
                    '''
                }
            }
        }
    }
}
```

Expected command output includes:

```text
jenkins-netboot
BOOT_SERVER_HOSTNAME
```

`StrictHostKeyChecking=accept-new` is convenient for the first controlled test\. For the production pipeline, store and verify the boot server’s host key and use `StrictHostKeyChecking=yes`\.

## 9\. Check server logs when authentication fails

While running the Jenkins test, monitor the boot server:

```bash
sudo journalctl -u sshd -f
```

On Debian or Ubuntu:

```bash
sudo journalctl -u ssh -f
```

Common log messages indicate:

- Incorrect ownership or mode on `.ssh` or `authorized_keys`\.
- An invalid SELinux label\.
- The wrong username\.
- A key that does not match the authorized public key\.
- Public\-key authentication being disabled\.

## 10\. Confirm that the keys match

Print the fingerprint of the public key on the server:

```bash
sudo -iu jenkins-netboot \
    ssh-keygen -lf /home/jenkins-netboot/.ssh/jenkins_netboot.pub
```

Print the public fingerprint derived from a local copy of the private key:

```bash
ssh-keygen -y -f ./jenkins_netboot | ssh-keygen -lf -
```

The fingerprints must match\. If they do not, Jenkins has a different private key from the public key in `authorized_keys`\.

## 11\. Lock password authentication for the account

Only after key authentication works, lock the Linux password:

```bash
sudo passwd -l jenkins-netboot
```

This prevents password login but does not interfere with valid SSH key authentication\.

If this account should only use SSH keys, you can also restrict it in `/etc/ssh/sshd_config`:

```text
Match User jenkins-netboot
    PasswordAuthentication no
    PubkeyAuthentication yes
```

Validate and reload the configuration:

```bash
sudo sshd -t
sudo systemctl reload sshd
```

Use `sudo systemctl reload ssh` instead on systems where the service is named `ssh`\.

## 12\. Remove the private key from the boot server

After the key is safely stored in Jenkins and Jenkins has successfully authenticated, remove the private\-key copy from the boot server:

```bash
sudo rm /home/jenkins-netboot/.ssh/jenkins_netboot
```

Keep these server\-side files:

```text
/home/jenkins-netboot/.ssh/authorized_keys
/home/jenkins-netboot/.ssh/jenkins_netboot.pub
```

The private key should remain in Jenkins Credentials or an approved secure backup\.

## Quick checklist

- [ ] The SSH username is exactly `jenkins-netboot`\.
- [ ] Jenkins stores the private key as an SSH private\-key credential\.
- [ ] `authorized_keys` contains the matching public key\.
- [ ] The Jenkinsfile uses `-i "${SSH_KEY_FILE}"`\.
- [ ] The Jenkinsfile uses `-o IdentitiesOnly=yes`\.
- [ ] `.ssh` is mode `700`\.
- [ ] `authorized_keys` is mode `600`\.
- [ ] The files are owned by `jenkins-netboot`\.
- [ ] SELinux labels were restored if SELinux is enabled\.
- [ ] The Jenkins credential username is `jenkins-netboot`\.
- [ ] `sshd -T` reports `pubkeyauthentication yes`\.
- [ ] Jenkins reports `Authenticated using "publickey"`\.
