Jenkins SSH Deployment to a Boot Server

This guide creates a dedicated Linux account on the boot-server VM and allows a Jenkins pipeline to connect to it using an SSH key stored in Jenkins Credentials.

The Jenkins agent still runs the ssh and scp commands. The dedicated account separates the pipeline from personal administrator accounts and limits what Jenkins can access.

Final authentication flow

1. Jenkins temporarily exposes the private key from its credential store.
2. The Jenkins agent connects to the boot server as netboot-deploy.
3. The boot server checks the matching public key in authorized_keys.
4. Commands run with the permissions of netboot-deploy.

No interactive password is required.

Example values

Change these values for your environment:

|Setting              |Example                 |
|---------------------|------------------------|
|Boot server          |`192.168.50.10`         |
|Deployment user      |`netboot-deploy`        |
|Jenkins credential ID|`netboot-server-ssh-key`|
|TFTP directory       |`/opt/tftpboot`         |
|NFS root directory   |`/srv/nfs/netboot`      |

1. Create the deployment account

Run these commands on the boot server from an account with sudo access:

```bash
sudo useradd --create-home --shell /bin/bash netboot-deploy
sudo passwd --lock netboot-deploy
```

The locked password prevents password-based login. SSH key authentication will still work.

If the user already exists, do not run useradd again. Confirm it with:

```bash
id netboot-deploy
getent passwd netboot-deploy
```

2. Generate the SSH key as the deployment user

Open a login shell as the new user:

```bash
sudo -iu netboot-deploy
```

Create the SSH directory and a dedicated Ed25519 key:

```bash
install -d -m 700 ~/.ssh

ssh-keygen \
    -t ed25519 \
    -f ~/.ssh/jenkins_netboot \
    -C "jenkins-netboot-deploy" \
    -N ""
```

The empty -N value means the key has no passphrase, which allows a noninteractive Jenkins job to use it. Jenkins Credentials must protect the private key.

The command creates:

```text
~/.ssh/jenkins_netboot       Private key for Jenkins
~/.ssh/jenkins_netboot.pub   Public key for the boot server
```

3. Authorize the public key

Still running as netboot-deploy:

```bash
cat ~/.ssh/jenkins_netboot.pub >> ~/.ssh/authorized_keys

chmod 700 ~/.ssh
chmod 600 ~/.ssh/authorized_keys
chmod 600 ~/.ssh/jenkins_netboot
chmod 644 ~/.ssh/jenkins_netboot.pub
```

Verify the ownership and permissions:

```bash
ls -la ~/.ssh
```

All files should be owned by netboot-deploy.

Exit the deployment-user shell when finished:

```bash
exit
```

4. Give the user access to the netboot directories

Create a group for netboot deployments and add the account to it:

```bash
sudo groupadd --force netboot
sudo usermod --append --groups netboot netboot-deploy
```

Create the directories if they do not already exist:

```bash
sudo install -d -m 2775 -o root -g netboot /opt/tftpboot
sudo install -d -m 2775 -o root -g netboot /srv/nfs/netboot
```

If the directories already contain files, apply the group carefully:

```bash
sudo chgrp -R netboot /opt/tftpboot /srv/nfs/netboot
sudo chmod -R g+rwX /opt/tftpboot /srv/nfs/netboot
sudo find /opt/tftpboot /srv/nfs/netboot -type d -exec chmod g+s {} +
```

The set-group-ID bit on the directories makes newly created files inherit the netboot group.

Test access:

```bash
sudo -iu netboot-deploy
touch /opt/tftpboot/jenkins-write-test
rm /opt/tftpboot/jenkins-write-test
exit
```

Avoid giving this account unrestricted sudo. If a future operation truly requires elevated privileges, allow only the exact command through a tightly scoped sudoers rule.

5. Add the private key to Jenkins Credentials

Display the private key on the boot server:

```bash
sudo -iu netboot-deploy cat /home/netboot-deploy/.ssh/jenkins_netboot
```

Copy the complete output, including these boundary lines:

```text
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

In Jenkins, open:

```text
Manage Jenkins -> Credentials -> System -> Global credentials -> Add Credentials
```

Create this credential:

|Field      |Value                          |
|-----------|-------------------------------|
|Kind       |`SSH Username with private key`|
|ID         |`netboot-server-ssh-key`       |
|Username   |`netboot-deploy`               |
|Private Key|`Enter directly`               |

Paste the private key and save the credential. Do not put the private key in the Jenkinsfile, Git repository, build parameters, or a normal environment variable.

6. Record and verify the boot server host key

Strict host-key checking prevents Jenkins from connecting to an impersonated server.

From a trusted administrative machine, collect the server key:

```bash
ssh-keyscan -H 192.168.50.10 > boot-server-known_hosts
ssh-keygen -lf boot-server-known_hosts
```

Verify the displayed fingerprint directly against the boot server:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

The Ed25519 fingerprints must match. Do not blindly run ssh-keyscan during every deployment because that accepts whichever host answers at that moment.

Add boot-server-known_hosts to Jenkins as a Secret file credential:

|Field|Value                       |
|-----|----------------------------|
|Kind |`Secret file`               |
|ID   |`netboot-server-known-hosts`|
|File |`boot-server-known_hosts`   |

7. Jenkins pipeline example

This example does not require the Jenkins SSH Agent plugin. It uses withCredentials to provide temporary paths to the private key and known_hosts file.

```groovy
pipeline {
    agent any

    parameters {
        string(
            name: 'RELEASE_NAME',
            defaultValue: 'product-a/release',
            description: 'Release directory to deploy'
        )
    }

    environment {
        NETBOOT_SERVER = '192.168.50.10'
        REMOTE_RELEASE_ROOT = '/opt/tftpboot/releases'
    }

    stages {
        stage('Test SSH') {
            steps {
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'netboot-server-ssh-key',
                        keyFileVariable: 'SSH_KEY_FILE',
                        usernameVariable: 'SSH_USERNAME'
                    ),
                    file(
                        credentialsId: 'netboot-server-known-hosts',
                        variable: 'KNOWN_HOSTS_FILE'
                    )
                ]) {
                    sh '''
                        set +x

                        ssh \
                            -i "${SSH_KEY_FILE}" \
                            -o IdentitiesOnly=yes \
                            -o StrictHostKeyChecking=yes \
                            -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
                            "${SSH_USERNAME}@${NETBOOT_SERVER}" \
                            'whoami && hostname'
                    '''
                }
            }
        }

        stage('Deploy Netboot Files') {
            steps {
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'netboot-server-ssh-key',
                        keyFileVariable: 'SSH_KEY_FILE',
                        usernameVariable: 'SSH_USERNAME'
                    ),
                    file(
                        credentialsId: 'netboot-server-known-hosts',
                        variable: 'KNOWN_HOSTS_FILE'
                    )
                ]) {
                    sh '''
                        set -eu
                        set +x

                        test -f "${WORKSPACE}/deploy/Image"
                        test -f "${WORKSPACE}/deploy/board.dtb"
                        test -f "${WORKSPACE}/deploy/uEnv.txt"

                        ssh \
                            -i "${SSH_KEY_FILE}" \
                            -o IdentitiesOnly=yes \
                            -o StrictHostKeyChecking=yes \
                            -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
                            "${SSH_USERNAME}@${NETBOOT_SERVER}" \
                            "mkdir -p '${REMOTE_RELEASE_ROOT}/${RELEASE_NAME}'"

                        scp \
                            -i "${SSH_KEY_FILE}" \
                            -o IdentitiesOnly=yes \
                            -o StrictHostKeyChecking=yes \
                            -o UserKnownHostsFile="${KNOWN_HOSTS_FILE}" \
                            "${WORKSPACE}/deploy/Image" \
                            "${WORKSPACE}/deploy/board.dtb" \
                            "${WORKSPACE}/deploy/uEnv.txt" \
                            "${SSH_USERNAME}@${NETBOOT_SERVER}:${REMOTE_RELEASE_ROOT}/${RELEASE_NAME}/"
                    '''
                }
            }
        }
    }
}
```

Important parameter warning

The example places RELEASE_NAME inside a remote shell command. In a production pipeline, validate it before use so a malicious or accidental value cannot inject shell syntax:

```groovy
stage('Validate Parameters') {
    steps {
        script {
            if (!(params.RELEASE_NAME ==~ /[A-Za-z0-9._-]+\/[A-Za-z0-9._-]+/)) {
                error('RELEASE_NAME must look like product/release and contain only letters, numbers, dot, underscore, or dash')
            }
        }
    }
}
```

Place this stage before any SSH deployment stage.

8. Test the connection

Run the pipeline’s Test SSH stage. Expected output resembles:

```text
netboot-deploy
boot-server
```

If it fails, check the boot-server SSH logs:

```bash
sudo journalctl -u sshd --since "10 minutes ago"
```

On Debian or Ubuntu, the service may be named ssh:

```bash
sudo journalctl -u ssh --since "10 minutes ago"
```

Confirm the account and SSH file permissions:

```bash
sudo namei -l /home/netboot-deploy/.ssh/authorized_keys
sudo -iu netboot-deploy ls -la /home/netboot-deploy/.ssh
```

9. Remove the temporary private-key copy from the boot server

Only do this after the Jenkins credential has been saved and the pipeline has connected successfully:

```bash
sudo rm /home/netboot-deploy/.ssh/jenkins_netboot
```

Keep these files on the boot server:

```text
/home/netboot-deploy/.ssh/authorized_keys
/home/netboot-deploy/.ssh/jenkins_netboot.pub
```

The private key should ultimately be held by Jenkins Credentials and any approved secure backup—not left on the server it authenticates to.

10. Revoke or rotate the key

To revoke Jenkins access, remove the matching public-key line from:

```text
/home/netboot-deploy/.ssh/authorized_keys
```

To rotate the key:

1. Generate a new key pair.
2. Add the new public key to authorized_keys without removing the old key.
3. replace the Jenkins credential with the new private key.
4. Test the pipeline.
5. Remove the old public key from authorized_keys.

Security summary

• Use a dedicated account such as netboot-deploy.
• Lock its Linux password and authenticate using SSH keys.
• Store the private key only in Jenkins Credentials and an approved secure backup.
• Verify and pin the server’s SSH host key.
• Use directory groups instead of unrestricted sudo.
• Wrap credentials only around the commands that need them.
• Keep command tracing disabled while credentials are bound.
• Validate any Jenkins parameter used in a shell command or remote path.
• Revoke access by removing the public key from authorized_keys.
