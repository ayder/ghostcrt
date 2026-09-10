from ghostcrt.ssh.command import build_ssh_command


def test_no_password():
    cmd = build_ssh_command("web", None)
    assert cmd.argv == ["ssh", "-tt", "--", "web"]
    assert cmd.password is None
    assert cmd.pass_fds == ()


def test_with_password_uses_sshpass_fd_not_argv():
    cmd = build_ssh_command("db", "s3cret-password")
    try:
        assert cmd.argv[0] == "sshpass"
        assert "-d" in cmd.argv
        assert "ssh" in cmd.argv
        assert "-tt" in cmd.argv
        assert "db" in cmd.argv
        joined = " ".join(cmd.argv)
        assert "s3cret-password" not in joined
        assert cmd.password == "s3cret-password"
        assert cmd.write_fd is not None
        assert cmd.pass_fds
    finally:
        cmd.close_pipe()
