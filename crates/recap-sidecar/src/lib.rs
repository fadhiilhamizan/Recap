//! Protokol stdio Recap (dokumen 03 bagian 4.2) dan host sidecar dengan supervisi.
//!
//! Frame di stdin/stdout:
//! ```text
//! u32 LE  panjang frame (tidak termasuk 4 byte ini)
//! u8      jenis: 0 = JSON control, 1 = audio
//! ...     payload
//! ```
//! Payload audio diawali header 32 byte (lihat [`AudioHeader`]), lalu PCM.

pub mod host;
pub mod protocol;

pub use protocol::*;
