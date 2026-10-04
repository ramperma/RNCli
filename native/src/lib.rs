mod pty;
mod vte;

use pyo3::prelude::*;

use crate::pty::NativePty;
use crate::vte::NativeVte;

#[pymodule]
fn rncli_native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NativePty>()?;
    m.add_class::<NativeVte>()?;
    m.add("AVAILABLE", true)?;
    Ok(())
}
