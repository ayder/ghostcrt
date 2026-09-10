from __future__ import annotations

import asyncio
import errno
import fcntl
import os
import pty
import signal
import struct
import termios


class PtyProcess:
    def __init__(self, pid: int, master_fd: int) -> None:
        self.pid = pid
        self.master_fd = master_fd
        self._closed = False
        self._exit_code: int | None = None
        self._wait_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()
        os.set_blocking(master_fd, False)

    @classmethod
    async def spawn(
        cls,
        argv: list[str],
        *,
        pass_fds: tuple[int, ...] = (),
        env: dict[str, str] | None = None,
        rows: int | None = None,
        cols: int | None = None,
    ) -> PtyProcess:
        if not argv:
            raise ValueError("argv must be non-empty")

        master_fd, slave_fd = pty.openpty()
        if rows is not None and cols is not None:
            winsize = struct.pack("HHHH", max(1, rows), max(1, cols), 0, 0)
            try:
                fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
            except BaseException:
                os.close(master_fd)
                os.close(slave_fd)
                raise

        # Make pass_fds inheritable; close others in child via close_fds pattern
        for fd in pass_fds:
            try:
                os.set_inheritable(fd, True)
            except OSError:
                pass

        try:
            pid = os.fork()
        except BaseException:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        if pid == 0:
            # Child
            try:
                os.setsid()
                # Set controlling tty
                try:
                    fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                except OSError:
                    pass
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)
                if slave_fd > 2:
                    os.close(slave_fd)
                os.close(master_fd)
                # Close non-pass fds that we don't need is hard after fork;
                # exec replaces image.
                child_env = os.environ.copy()
                if env:
                    child_env.update(env)
                os.execvpe(argv[0], argv, child_env)
            except Exception:
                os._exit(127)

        # Parent
        os.close(slave_fd)
        return cls(pid, master_fd)

    async def read(self, n: int = 4096) -> bytes:
        if self._closed:
            return b""
        loop = asyncio.get_running_loop()
        fut: asyncio.Future[bytes] = loop.create_future()

        def _on_readable() -> None:
            if fut.done():
                return
            try:
                data = os.read(self.master_fd, n)
            except BlockingIOError:
                return
            except OSError as exc:
                if exc.errno in (errno.EIO, errno.EBADF):
                    loop.remove_reader(self.master_fd)
                    fut.set_result(b"")
                    return
                loop.remove_reader(self.master_fd)
                fut.set_exception(exc)
                return
            loop.remove_reader(self.master_fd)
            fut.set_result(data)

        try:
            loop.add_reader(self.master_fd, _on_readable)
        except (OSError, ValueError):
            return b""
        try:
            return await fut
        finally:
            try:
                loop.remove_reader(self.master_fd)
            except (OSError, ValueError):
                pass

    async def write(self, data: bytes) -> None:
        if not data or self._closed:
            return
        async with self._write_lock:
            loop = asyncio.get_running_loop()
            view = memoryview(data)
            while view and not self._closed:
                try:
                    written = os.write(self.master_fd, view)
                    if written == 0:
                        raise BrokenPipeError("PTY write returned zero bytes")
                    view = view[written:]
                except BlockingIOError:
                    fut: asyncio.Future[None] = loop.create_future()

                    def _on_writable(f: asyncio.Future[None] = fut) -> None:
                        if not f.done():
                            loop.remove_writer(self.master_fd)
                            f.set_result(None)

                    loop.add_writer(self.master_fd, _on_writable)
                    try:
                        await fut
                    finally:
                        try:
                            loop.remove_writer(self.master_fd)
                        except (OSError, ValueError):
                            pass
                except OSError as exc:
                    if exc.errno in (errno.EBADF, errno.EIO, errno.EPIPE):
                        return
                    raise

    def resize(self, rows: int, cols: int) -> None:
        if self._closed:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    async def wait(self) -> int:
        async with self._wait_lock:
            if self._exit_code is not None:
                return self._exit_code
            while True:
                try:
                    pid, status = os.waitpid(self.pid, os.WNOHANG)
                except ChildProcessError:
                    # Another owner should never reap this child, but retain a
                    # stable result if it happens rather than racing forever.
                    self._exit_code = 0
                    return self._exit_code
                if pid == 0:
                    await asyncio.sleep(0.05)
                    continue
                if os.WIFEXITED(status):
                    self._exit_code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    self._exit_code = 128 + os.WTERMSIG(status)
                else:
                    self._exit_code = status
                return self._exit_code

    def send_signal(self, sig: signal.Signals) -> None:
        if self._exit_code is not None:
            return
        try:
            # The child creates a new session, so signalling the process group
            # also cleans up helpers started by ssh/ProxyCommand.
            os.killpg(self.pid, sig)
        except ProcessLookupError:
            try:
                os.kill(self.pid, sig)
            except OSError:
                pass
        except PermissionError:
            try:
                os.kill(self.pid, sig)
            except OSError:
                pass

    def terminate(self) -> None:
        self.send_signal(signal.SIGTERM)

    def kill(self) -> None:
        self.send_signal(signal.SIGKILL)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            loop = asyncio.get_running_loop()
            loop.remove_reader(self.master_fd)
            loop.remove_writer(self.master_fd)
        except (RuntimeError, OSError, ValueError):
            pass
        try:
            os.close(self.master_fd)
        except OSError:
            pass
