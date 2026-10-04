//! PTY Linux: setsid + TIOCSCTTY + PR_SET_PDEATHSIG + exec, sin helper de Python.

use std::collections::HashMap;
use std::os::fd::{IntoRawFd, RawFd};
use std::path::Path;

use nix::fcntl::{fcntl, FcntlArg, OFlag};
use nix::pty::{openpty, Winsize};
use nix::sys::signal::{kill, Signal};
use nix::sys::wait::{waitpid, WaitPidFlag, WaitStatus};
use nix::unistd::{close, dup2, execvp, fork, setsid, ForkResult, Pid};
use pyo3::exceptions::PyOSError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

#[pyclass]
pub struct NativePty {
    fd: RawFd,
    pid: Pid,
    cols: u16,
    rows: u16,
    dead: bool,
    code: Option<i32>,
}

fn os_err(message: impl Into<String>) -> PyErr {
    PyOSError::new_err(message.into())
}

fn set_nonblocking(fd: RawFd) -> Result<(), String> {
    let flags = fcntl(fd, FcntlArg::F_GETFL).map_err(|err| err.to_string())?;
    let flags = OFlag::from_bits_truncate(flags) | OFlag::O_NONBLOCK;
    fcntl(fd, FcntlArg::F_SETFL(flags)).map_err(|err| err.to_string())?;
    Ok(())
}

fn set_winsize(fd: RawFd, cols: u16, rows: u16) {
    let mut size = libc::winsize {
        ws_row: rows.max(2),
        ws_col: cols.max(2),
        ws_xpixel: 0,
        ws_ypixel: 0,
    };
    unsafe {
        libc::ioctl(fd, libc::TIOCSWINSZ, std::ptr::from_mut(&mut size));
    }
}

fn child_exec(
    slave_fd: RawFd,
    argv: &[String],
    cwd: &str,
    env: &HashMap<String, String>,
) -> ! {
    let _ = setsid();
    unsafe {
        libc::ioctl(slave_fd, libc::TIOCSCTTY, 0);
        libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0);
        if libc::getppid() <= 1 {
            libc::kill(libc::getpid(), libc::SIGKILL);
        }
    }
    let _ = dup2(slave_fd, 0);
    let _ = dup2(slave_fd, 1);
    let _ = dup2(slave_fd, 2);
    if slave_fd > 2 {
        let _ = close(slave_fd);
    }
    if !cwd.is_empty() {
        let path = Path::new(cwd);
        if path.is_dir() {
            let _ = nix::unistd::chdir(path);
        }
    }
    for (key, value) in env {
        std::env::set_var(key, value);
    }
    if argv.is_empty() {
        unsafe { libc::_exit(125) };
    }
    let c_argv: Vec<std::ffi::CString> = argv
        .iter()
        .filter_map(|part| std::ffi::CString::new(part.as_str()).ok())
        .collect();
    if c_argv.len() != argv.len() || c_argv.is_empty() {
        unsafe { libc::_exit(125) };
    }
    let refs: Vec<&std::ffi::CStr> = c_argv.iter().map(std::ffi::CString::as_c_str).collect();
    let _ = execvp(&c_argv[0], &refs);
    let message = format!(
        "\r\n[rncli] no se encontró el comando '{}'\r\n",
        argv[0]
    );
    unsafe {
        libc::write(
            libc::STDERR_FILENO,
            message.as_ptr().cast(),
            message.len(),
        );
        libc::_exit(127)
    };
}

#[pymethods]
impl NativePty {
    #[new]
    fn new(
        argv: Vec<String>,
        cwd: String,
        env: HashMap<String, String>,
        cols: u16,
        rows: u16,
    ) -> PyResult<Self> {
        if argv.is_empty() {
            return Err(os_err("falta el comando a ejecutar"));
        }
        let cols = cols.max(2);
        let rows = rows.max(2);
        let winsize = Winsize {
            ws_row: rows,
            ws_col: cols,
            ws_xpixel: 0,
            ws_ypixel: 0,
        };
        let pair = openpty(Some(&winsize), None).map_err(|err| os_err(err.to_string()))?;
        match unsafe { fork() } {
            Ok(ForkResult::Parent { child }) => {
                drop(pair.slave);
                let fd = pair.master.into_raw_fd();
                set_nonblocking(fd).map_err(os_err)?;
                Ok(Self {
                    fd,
                    pid: child,
                    cols,
                    rows,
                    dead: false,
                    code: None,
                })
            }
            Ok(ForkResult::Child) => {
                drop(pair.master);
                let slave = pair.slave.into_raw_fd();
                child_exec(slave, &argv, &cwd, &env);
            }
            Err(err) => Err(os_err(format!("fork: {err}"))),
        }
    }

    fn fileno(&self) -> i32 {
        self.fd
    }

    fn pid(&self) -> i32 {
        self.pid.as_raw()
    }

    fn read<'py>(&mut self, py: Python<'py>, size: usize) -> PyResult<Option<Bound<'py, PyBytes>>> {
        if self.fd < 0 {
            return Ok(Some(PyBytes::new(py, b"")));
        }
        let mut buf = vec![0u8; size.max(1).min(65536)];
        let n = unsafe { libc::read(self.fd, buf.as_mut_ptr().cast(), buf.len()) };
        if n == 0 {
            return Ok(Some(PyBytes::new(py, b"")));
        }
        if n < 0 {
            return match std::io::Error::last_os_error().raw_os_error() {
                Some(libc::EAGAIN) => Ok(None),
                Some(libc::EIO | libc::EBADF) => Ok(Some(PyBytes::new(py, b""))),
                _ => Err(os_err(std::io::Error::last_os_error().to_string())),
            };
        }
        Ok(Some(PyBytes::new(py, &buf[..n as usize])))
    }

    fn write(&mut self, data: &[u8]) -> PyResult<usize> {
        if self.fd < 0 || data.is_empty() {
            return Ok(0);
        }
        let n = unsafe { libc::write(self.fd, data.as_ptr().cast(), data.len()) };
        if n < 0 {
            return match std::io::Error::last_os_error().raw_os_error() {
                Some(libc::EAGAIN) => Ok(0),
                _ => Err(os_err(std::io::Error::last_os_error().to_string())),
            };
        }
        Ok(n as usize)
    }

    fn resize(&mut self, cols: u16, rows: u16) {
        let cols = cols.max(2);
        let rows = rows.max(2);
        if cols == self.cols && rows == self.rows {
            return;
        }
        self.cols = cols;
        self.rows = rows;
        if self.fd >= 0 {
            set_winsize(self.fd, cols, rows);
        }
    }

    fn poll(&mut self) -> Option<i32> {
        if let Some(code) = self.code {
            return Some(code);
        }
        match waitpid(self.pid, Some(WaitPidFlag::WNOHANG)) {
            Ok(WaitStatus::Exited(_, code)) => {
                self.dead = true;
                self.code = Some(code);
                Some(code)
            }
            Ok(WaitStatus::Signaled(_, sig, _)) => {
                let code = 128 + sig as i32;
                self.dead = true;
                self.code = Some(code);
                Some(code)
            }
            Ok(WaitStatus::StillAlive) | Err(_) => None,
            Ok(_) => None,
        }
    }

    fn terminate(&self) {
        let _ = kill(self.pid, Signal::SIGTERM);
        let _ = kill(self.pid, Signal::SIGHUP);
        let pgid = Pid::from_raw(-self.pid.as_raw());
        let _ = kill(pgid, Signal::SIGTERM);
    }

    fn kill(&self) {
        let pgid = Pid::from_raw(-self.pid.as_raw());
        let _ = kill(pgid, Signal::SIGKILL);
        let _ = kill(self.pid, Signal::SIGKILL);
    }

    fn close(&mut self) {
        if self.fd >= 0 {
            unsafe { libc::close(self.fd) };
            self.fd = -1;
        }
    }
}

impl Drop for NativePty {
    fn drop(&mut self) {
        if self.fd >= 0 {
            unsafe { libc::close(self.fd) };
            self.fd = -1;
        }
    }
}
