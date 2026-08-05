Returning Remote SSH Exit Codes in a Jenkins Pipeline

This guide shows how to run a command on a boot server over SSH and return the remote command’s numeric exit code to a Jenkins pipeline.

It does not require a Java function. Jenkins can capture the same exit code that a normal shell exposes through $?.

What Jenkins should return

For a command such as:

```bash
ssh jenkins-netboot@192.168.50.10 'test -f /opt/tftpboot/Image'
echo $?
```

the expected results are:

|Exit code|Meaning                                                                     |
|---------|----------------------------------------------------------------------------|
|`0`      |SSH connected and the remote command succeeded                              |
|`1`      |SSH connected, but `test` reported that the file does not exist             |
|`2–254`  |The remote command returned another failure code                            |
|`255`    |SSH itself failed, such as authentication, DNS, network, or host-key failure|

SSH automatically forwards the remote command’s exit code. Jenkins only needs to capture the exit code returned by the local ssh process.

The important Jenkins syntax

Use returnStatus: true as an argument to the sh step:

```groovy
int exitCode = sh(
    script: 'some command',
    returnStatus: true
)
```

The word true is not the exit code. It tells Jenkins:

> Do not immediately fail the pipeline when this shell command returns nonzero. Give me the numeric exit code instead.

The variable exitCode should then contain 0, 1, 2, 255, or another integer.

Incorrect forms

These examples can result in incorrect behavior or null.

Incorrect: using status instead of returnStatus

```groovy
def exitCode = sh(
    script: 'some command',
    status: true
)
```

The Jenkins sh option is named returnStatus, not status.

Incorrect: setting a variable after calling sh

```groovy
def exitCode = sh(script: 'some command')
status = true
```

This does not ask sh to return the status. Without returnStatus: true, Jenkins normally fails the step when the command returns nonzero.

Incorrect: converting the number to a Boolean

```groovy
return exitCode == 0
```

That returns only true or false. Return the integer itself:

```groovy
return exitCode
```

Incorrect: forgetting to return from a wrapper

```groovy
def withBootServerCredentials(Closure operation) {
    withCredentials([/* credentials */]) {
        operation()
    }

    echo 'Finished'
}
```

The final echo does not return the SSH exit code. Depending on the surrounding code, the caller may receive null.

Use explicit returns:

```groovy
def withBootServerCredentials(Closure operation) {
    return withCredentials([/* credentials */]) {
        return operation()
    }
}
```

First test: prove returnStatus works without SSH

Before troubleshooting SSH, run this small Jenkins stage:

```groovy
stage('Test Local Exit Codes') {
    steps {
        script {
            int successCode = sh(
                script: 'exit 0',
                returnStatus: true
            )

            int failureCode = sh(
                script: 'exit 7',
                returnStatus: true
            )

            echo "Success code: ${successCode}"
            echo "Failure code: ${failureCode}"
        }
    }
}
```

Expected output:

```text
Success code: 0
Failure code: 7
```

If either value is null, check the exact placement of the assignment and returnStatus: true against this example.

Recommended two-function design

The first function binds the Jenkins credentials. The second function runs SSH and returns its numeric exit code.

Place these functions outside the pipeline {} block in the Jenkinsfile.

Function 1: bind the SSH credentials

```groovy
def withBootServerCredentials(Closure operation) {
    return withCredentials([
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
        return operation()
    }
}
```

The two explicit return statements are intentional:

```groovy
return withCredentials(...)
return operation()
```

They ensure the value returned by sshCommand() travels back through the credential wrapper to the calling stage.

Function 2: run SSH and return its exit code

```groovy
def sshCommand(String remoteCommand) {
    int exitCode = sh(
        script: """
            set +x

            ssh \\
                -i "\${SSH_KEY_FILE}" \\
                -o IdentitiesOnly=yes \\
                -o BatchMode=yes \\
                -o StrictHostKeyChecking=yes \\
                -o UserKnownHostsFile="\${KNOWN_HOSTS_FILE}" \\
                "\${SSH_USERNAME}@\${NETBOOT_SERVER}" \\
                '${remoteCommand}'
        """,
        returnStatus: true
    )

    return exitCode
}
```

Notice that returnStatus: true belongs inside the sh(...) call, after the script argument.

Also notice that the function returns the integer:

```groovy
return exitCode
```

It does not return this Boolean expression:

```groovy
return exitCode == 0
```

Complete copyable Jenkinsfile

```groovy
def withBootServerCredentials(Closure operation) {
    return withCredentials([
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
        return operation()
    }
}

def sshCommand(String remoteCommand) {
    int exitCode = sh(
        script: """
            set +x

            ssh \\
                -i "\${SSH_KEY_FILE}" \\
                -o IdentitiesOnly=yes \\
                -o BatchMode=yes \\
                -o StrictHostKeyChecking=yes \\
                -o UserKnownHostsFile="\${KNOWN_HOSTS_FILE}" \\
                "\${SSH_USERNAME}@\${NETBOOT_SERVER}" \\
                '${remoteCommand}'
        """,
        returnStatus: true
    )

    echo "sshCommand exit code: ${exitCode}"
    return exitCode
}

pipeline {
    agent any

    environment {
        NETBOOT_SERVER = '192.168.50.10'
    }

    stages {
        stage('Test Remote Exit Codes') {
            steps {
                script {
                    int successCode = withBootServerCredentials {
                        return sshCommand('exit 0')
                    }

                    int failureCode = withBootServerCredentials {
                        return sshCommand('exit 7')
                    }

                    echo "Remote success code: ${successCode}"
                    echo "Remote failure code: ${failureCode}"

                    if (successCode != 0) {
                        error("Expected success code 0, received ${successCode}")
                    }

                    if (failureCode != 7) {
                        error("Expected failure code 7, received ${failureCode}")
                    }
                }
            }
        }

        stage('Check Netboot Image') {
            steps {
                script {
                    int exitCode = withBootServerCredentials {
                        return sshCommand(
                            'test -f /opt/tftpboot/Image'
                        )
                    }

                    echo "Image check returned: ${exitCode}"

                    if (exitCode == 0) {
                        echo 'The image exists on the boot server.'
                    } else if (exitCode == 1) {
                        echo 'The image does not exist on the boot server.'
                    } else if (exitCode == 255) {
                        error('SSH could not connect or authenticate.')
                    } else {
                        error("Unexpected remote exit code: ${exitCode}")
                    }
                }
            }
        }
    }
}
```

Run the Test Remote Exit Codes stage before using real deployment commands. It deliberately runs exit 0 and exit 7, so you can prove that both functions preserve the numeric status.

Expected output:

```text
sshCommand exit code: 0
sshCommand exit code: 7
Remote success code: 0
Remote failure code: 7
```

If you want to use $? explicitly

You normally do not need $? because Jenkins captures the exit status of the final ssh command. However, this equivalent function demonstrates the normal shell behavior:

```groovy
def sshCommand(String remoteCommand) {
    int exitCode = sh(
        script: """
            set +x

            ssh \\
                -i "\${SSH_KEY_FILE}" \\
                -o IdentitiesOnly=yes \\
                -o BatchMode=yes \\
                -o StrictHostKeyChecking=yes \\
                -o UserKnownHostsFile="\${KNOWN_HOSTS_FILE}" \\
                "\${SSH_USERNAME}@\${NETBOOT_SERVER}" \\
                '${remoteCommand}'

            ssh_status=\$?
            echo "SSH returned: \${ssh_status}"
            exit "\${ssh_status}"
        """,
        returnStatus: true
    )

    return exitCode
}
```

The important line is:

```bash
exit "${ssh_status}"
```

If you capture $?, print it, and then allow another command to run last, Jenkins will see the last command’s exit code instead. Explicitly exiting with the saved value preserves it.

Commands after SSH can hide the status

This shell script returns the status of echo, not necessarily SSH:

```bash
ssh user@server 'some-command'
echo "SSH finished"
```

Because echo normally succeeds, Jenkins may receive 0 even when SSH returned a failure.

Use one of these approaches.

Make SSH the final command

```bash
echo "Running SSH"
ssh user@server 'some-command'
```

Save and restore the SSH status

```bash
ssh user@server 'some-command'
ssh_status=$?

echo "SSH returned ${ssh_status}"
exit "${ssh_status}"
```

Pipes can also hide the SSH status

This normally returns the exit code from tee, because tee is the last command in the pipeline:

```bash
ssh user@server 'some-command' | tee ssh-output.log
```

If the Jenkins agent’s shell supports Bash, use pipefail:

```bash
set -o pipefail
ssh user@server 'some-command' | tee ssh-output.log
```

Or avoid the pipe while diagnosing the exit-code problem.

Simple commands versus complex command strings

The function shown above wraps the remote command in single quotes:

```groovy
'${remoteCommand}'
```

That is adequate for straightforward commands such as:

```groovy
sshCommand('test -f /opt/tftpboot/Image')
sshCommand('mkdir -p /opt/tftpboot/releases/product-a')
sshCommand('exit 7')
```

It is not safe for arbitrary input or a command containing its own single quotes. Do not pass unvalidated user-controlled Jenkins parameters into it.

For now, first confirm the numeric return behavior using exit 0 and exit 7. Once that works, command quoting can be handled separately based on the exact remote commands you need.

Debugging a null exit code

Work through these checks in order.

1. Test the Jenkins sh step directly

```groovy
int exitCode = sh(
    script: 'exit 7',
    returnStatus: true
)

echo "Direct exit code: ${exitCode}"
```

Expected:

```text
Direct exit code: 7
```

2. Test sshCommand() without the credentials wrapper

Run this only from inside an existing withCredentials block:

```groovy
int exitCode = sshCommand('exit 7')
echo "SSH function exit code: ${exitCode}"
```

Expected:

```text
SSH function exit code: 7
```

3. Test the complete wrapper

```groovy
int exitCode = withBootServerCredentials {
    return sshCommand('exit 7')
}

echo "Wrapped exit code: ${exitCode}"
```

Expected:

```text
Wrapped exit code: 7
```

If step 1 works but step 2 returns null, the missing return is inside sshCommand().

If steps 1 and 2 work but step 3 returns null, the missing return is inside withBootServerCredentials() or its closure.

Quick checklist

☐ Use returnStatus: true, not status: true.
☐ Assign the result of sh(...) to a variable.
☐ Return that variable from sshCommand().
☐ Return operation() from the credentials closure.
☐ Return the withCredentials(...) result from the wrapper.
☐ Return sshCommand(...) from the calling closure.
☐ Do not use return exitCode == 0 if you need the integer.
☐ Keep SSH as the last shell command or use exit "$ssh_status".
☐ Avoid pipes while diagnosing the problem.
☐ Test with remote exit 0 and exit 7 before using real commands.
☐ Treat exit code 255 as an SSH transport or authentication failure.
