FROM python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends openssh-server \
    && rm -rf /var/lib/apt/lists/*
RUN mkdir /run/sshd && useradd -m -s /bin/sh ghostcrt \
    && echo 'ghostcrt:synthetic-test-password' | chpasswd
RUN printf 'PasswordAuthentication yes\nKbdInteractiveAuthentication no\nUsePAM no\nPermitRootLogin no\n' \
    > /etc/ssh/sshd_config.d/ghostcrt-test.conf
CMD ["/usr/sbin/sshd", "-D", "-e"]
