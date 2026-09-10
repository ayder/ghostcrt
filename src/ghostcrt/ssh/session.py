from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable

from ghostcrt.models import SessionState
from ghostcrt.ssh.pty_process import PtyProcess

DEFAULT_HISTORY = 5000
DEFAULT_ROWS = 24
DEFAULT_COLS = 80


class SshSession:
    def __init__(self, alias: str, *, history_size: int = DEFAULT_HISTORY) -> None:
        self.alias = alias
        self.history_size = history_size
        self.state = SessionState.CONNECTING
        self.exit_code: int | None = None
        self.on_output: Callable[[bytes], None] | None = None
        self.on_state: Callable[[SessionState], None] | None = None
        self._proc: PtyProcess | None = None
        self._pump_task: asyncio.Task[None] | None = None
        self._operation_lock = asyncio.Lock()
        self._disposed = False
        self._rows = DEFAULT_ROWS
        self._cols = DEFAULT_COLS

    def _set_state(self, state: SessionState) -> None:
        self.state = state
        if self.on_state:
            self.on_state(state)

    def _notify_output(self, data: bytes) -> None:
        if self.on_output:
            self.on_output(data)

    async def start(
        self,
        argv: list[str],
        *,
        pass_fds: tuple[int, ...] = (),
        password: str | None = None,
        write_fd: int | None = None,
        read_fd: int | None = None,
    ) -> None:
        async with self._operation_lock:
            if self._disposed:
                raise RuntimeError("session has been closed")
            await self._start(
                argv,
                pass_fds=pass_fds,
                password=password,
                write_fd=write_fd,
                read_fd=read_fd,
            )

    async def _start(
        self,
        argv: list[str],
        *,
        pass_fds: tuple[int, ...],
        password: str | None,
        write_fd: int | None,
        read_fd: int | None,
    ) -> None:
        if self._proc is not None:
            raise RuntimeError("session is already started")
        self.exit_code = None
        self._set_state(SessionState.CONNECTING)
        proc: PtyProcess | None = None
        try:
            proc = await PtyProcess.spawn(
                argv,
                pass_fds=pass_fds,
                rows=self._rows,
                cols=self._cols,
            )
            proc.resize(self._rows, self._cols)
            if password is not None and write_fd is not None:
                os.write(write_fd, (password + "\n").encode("utf-8"))
            self._proc = proc
            self._set_state(SessionState.CONNECTED)
            self._pump_task = asyncio.create_task(
                self._pump(proc), name=f"ssh-output:{self.alias}"
            )
        except BaseException:
            if proc is not None:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=0.5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                finally:
                    proc.close()
            self._set_state(SessionState.DISCONNECTED)
            raise
        finally:
            for fd in (write_fd, read_fd):
                if fd is not None:
                    try:
                        os.close(fd)
                    except OSError:
                        pass

    async def _pump(self, proc: PtyProcess) -> None:
        try:
            while True:
                data = await proc.read(4096)
                if not data:
                    break
                self._notify_output(data)
        finally:
            code = await proc.wait()
            if self._proc is proc:
                self.exit_code = code
                self._set_state(SessionState.DISCONNECTED)

    async def send(self, data: bytes) -> None:
        if self._proc is None or self.state != SessionState.CONNECTED:
            return
        await self._proc.write(data)

    def resize(self, rows: int, cols: int) -> None:
        self._rows = max(1, rows)
        self._cols = max(1, cols)
        if self._proc is not None:
            self._proc.resize(self._rows, self._cols)

    async def reconnect(
        self,
        argv: list[str],
        *,
        pass_fds: tuple[int, ...] = (),
        password: str | None = None,
        write_fd: int | None = None,
        read_fd: int | None = None,
        before_start: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        async with self._operation_lock:
            if self._disposed:
                raise RuntimeError("session has been closed")
            await self._close()
            if before_start is not None:
                await before_start()
            await self._start(
                argv,
                pass_fds=pass_fds,
                password=password,
                write_fd=write_fd,
                read_fd=read_fd,
            )

    async def close(self) -> None:
        async with self._operation_lock:
            self._disposed = True
            await self._close()

    async def _close(self) -> None:
        proc = self._proc
        pump_task = self._pump_task
        if proc is None:
            if self.state != SessionState.DISCONNECTED:
                if self.exit_code is None:
                    self.exit_code = -1
                self._set_state(SessionState.DISCONNECTED)
            return

        # Signal first. Cancelling the pump first used to deadlock because
        # its finally block waits for the still-running SSH process.
        proc.terminate()
        try:
            if pump_task is not None:
                await asyncio.wait_for(asyncio.shield(pump_task), timeout=2.0)
            else:
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        except TimeoutError:
            proc.kill()
            if pump_task is not None:
                pump_task.cancel()
                try:
                    await pump_task
                except asyncio.CancelledError:
                    pass
            self.exit_code = await proc.wait()
        finally:
            proc.close()
            if self._proc is proc:
                self._proc = None
            if self._pump_task is pump_task:
                self._pump_task = None

        if self.state != SessionState.DISCONNECTED:
            if self.exit_code is None:
                self.exit_code = -1
            self._set_state(SessionState.DISCONNECTED)
