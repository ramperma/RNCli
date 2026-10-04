//! PTY Linux: setsid + TIOCSCTTY + PR_SET_PDEATHSIG + exec, sin helper de Python.

use std::collections::HashMap;
use std::ffi::CString;
use std::os::fd::{IntoRawFd, RawFd};

use nix::fcntl::{fcntl, FcntlArg, OFlag};
use nix::pty::{openpty, Winsize};
use nix::sys::signal::{kill, Signal};
use nix::sys::wait::{waitpid, WaitPidFlag, WaitStatus};
use nix::unistd::{fork, ForkResult, Pid};
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

/// Todo lo que el proceso hijo necesita tras el `fork`, reservado de antemano.
///
/// Entre `fork()` y `execvpe()` solo se permiten operaciones async-signal-safe;
/// por eso las cadenas, el entorno y los mensajes de error se construyen aquí.
struct ChildPlan {
    // `argv` y `env` solo se conservan para que los punteros sigan siendo válidos.
    #[allow(dead_code)]
    argv: Vec<CString>,
    argv_ptrs: Vec<*const libc::c_char>,
    #[allow(dead_code)]
    env: Vec<CString>,
    env_ptrs: Vec<*const libc::c_char>,
    cwd: Option<CString>,
    not_found: CString,
    permission: CString,
    failed: CString,
}

impl ChildPlan {
    fn build(argv: &[String], cwd: &str, env: &HashMap<String, String>) -> Result<Self, String> {
        if argv.is_empty() {
            return Err("falta el comando a ejecutar".into());
        }
        let argv_c = argv
            .iter()
            .map(|part| CString::new(part.as_str()).map_err(|_| "argumento con byte nulo"))
            .collect::<Result<Vec<_>, _>>()?;
        let mut argv_ptrs: Vec<*const libc::c_char> =
            argv_c.iter().map(|part| part.as_ptr()).collect();
        argv_ptrs.push(std::ptr::null());

        let env_c = env
            .iter()
            .map(|(key, value)| {
                CString::new(format!("{key}={value}"))
                    .map_err(|_| "variable de entorno con byte nulo")
            })
            .collect::<Result<Vec<_>, _>>()?;
        let mut env_ptrs: Vec<*const libc::c_char> =
            env_c.iter().map(|entry| entry.as_ptr()).collect();
        env_ptrs.push(std::ptr::null());

        let cwd = if cwd.is_empty() {
            None
        } else {
            Some(CString::new(cwd).map_err(|_| "cwd con byte nulo")?)
        };

        let not_found =
            CString::new(format!("\r\n[rncli] no se encontró el comando '{}'\r\n", argv[0]))
                .unwrap();
        let permission =
            CString::new(format!("\r\n[rncli] sin permisos para ejecutar '{}'\r\n", argv[0]))
                .unwrap();
        let failed =
            CString::new(format!("\r\n[rncli] no se pudo ejecutar '{}'\r\n", argv[0])).unwrap();

        Ok(Self {
            argv: argv_c,
            argv_ptrs,
            env: env_c,
            env_ptrs,
            cwd,
            not_found,
            permission,
            failed,
        })
    }
}

fn child_exec(slave_fd: RawFd, plan: &ChildPlan) -> ! {
    let _ = unsafe { libc::setsid() };
    unsafe {
        libc::ioctl(slave_fd, libc::TIOCSCTTY, 0);
        libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0);
        if libc::getppid() <= 1 {
            libc::kill(libc::getpid(), libc::SIGKILL);
        }
        libc::dup2(slave_fd, 0);
        libc::dup2(slave_fd, 1);
        libc::dup2(slave_fd, 2);
    }
    if slave_fd > 2 {
        unsafe {
            libc::close(slave_fd);
        }
    }
    if let Some(dir) = &plan.cwd {
        unsafe {
            libc::chdir(dir.as_ptr());
        }
    }
    unsafe {
        libc::execvpe(
            plan.argv_ptrs[0],
            plan.argv_ptrs.as_ptr(),
            plan.env_ptrs.as_ptr(),
        );
        let errno = std::io::Error::last_os_error().raw_os_error().unwrap_or(0);
        let (code, message) = match errno {
            libc::ENOENT => (127, &plan.not_found),
            libc::EACCES => (126, &plan.permission),
            _ => (126, &plan.failed),
        };
        let bytes = message.as_bytes();
        libc::write(libc::STDERR_FILENO, bytes.as_ptr().cast(), bytes.len());
        libc::_exit(code);
    }
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

        // Reservar todo antes del fork: el hijo no debe asignar memoria.
        let plan = ChildPlan::build(&argv, &cwd, &env).map_err(os_err)?;

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
                child_exec(slave, &plan);
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
