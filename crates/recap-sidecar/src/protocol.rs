use std::io::{self, Read, Write};

use serde::{Deserialize, Serialize};

/// Versi protokol. Naikkan bila format frame atau arti pesan berubah tidak kompatibel.
pub const PROTOCOL_VERSION: u32 = 1;
/// Batas ukuran frame (melindungi dari panjang rusak/berbahaya).
pub const MAX_FRAME: u32 = 16 * 1024 * 1024;

const KIND_CONTROL: u8 = 0;
const KIND_AUDIO: u8 = 1;

#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    #[error("stream ditutup")]
    Eof,
    #[error("frame terlalu besar: {0} byte")]
    TooLarge(u32),
    #[error("jenis frame tidak dikenal: {0}")]
    UnknownKind(u8),
    #[error("header audio tidak valid")]
    BadAudioHeader,
    #[error("JSON tidak valid: {0}")]
    Json(#[from] serde_json::Error),
    #[error("I/O: {0}")]
    Io(#[from] io::Error),
}

/// Pesan control. `id` dipakai untuk mencocokkan permintaan dan jawaban.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Control {
    Hello { v: u32, binary: String, version: String },
    Ping { id: u64 },
    Pong { id: u64 },
    Health { uptime_ms: u64, frames_sent: u64 },
    /// Hanya untuk uji: minta sidecar crash (abort) atau macet.
    Crash,
    Stall,
    Shutdown,
    Error { message: String },
}

/// Header 32 byte frame audio (diadaptasi dari header paket prismical).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AudioHeader {
    pub version: u8,
    /// 0 = mic, 1 = mic_aec, 2 = system
    pub channel: u8,
    /// 0 = f32le, 1 = s16le
    pub format: u8,
    pub channels: u8,
    pub sample_rate: u32,
    pub seq: u32,
    pub sample_start: u64,
    pub host_time_ns: u64,
    pub payload_len: u32,
}

impl AudioHeader {
    pub const LEN: usize = 32;

    pub fn to_bytes(&self) -> [u8; 32] {
        let mut b = [0u8; 32];
        b[0] = self.version;
        b[1] = self.channel;
        b[2] = self.format;
        b[3] = self.channels;
        b[4..8].copy_from_slice(&self.sample_rate.to_le_bytes());
        b[8..12].copy_from_slice(&self.seq.to_le_bytes());
        b[12..20].copy_from_slice(&self.sample_start.to_le_bytes());
        b[20..28].copy_from_slice(&self.host_time_ns.to_le_bytes());
        b[28..32].copy_from_slice(&self.payload_len.to_le_bytes());
        b
    }

    pub fn from_bytes(b: &[u8]) -> Result<Self, FrameError> {
        if b.len() < Self::LEN {
            return Err(FrameError::BadAudioHeader);
        }
        let u32_at = |i: usize| u32::from_le_bytes(b[i..i + 4].try_into().unwrap());
        let u64_at = |i: usize| u64::from_le_bytes(b[i..i + 8].try_into().unwrap());
        Ok(Self {
            version: b[0], channel: b[1], format: b[2], channels: b[3],
            sample_rate: u32_at(4), seq: u32_at(8), sample_start: u64_at(12), host_time_ns: u64_at(20), payload_len: u32_at(28),
        })
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum Frame {
    Control(Control),
    Audio { header: AudioHeader, pcm: Vec<u8> },
}

impl Frame {
    pub fn encode(&self) -> Result<Vec<u8>, FrameError> {
        let (kind, payload) = match self {
            Frame::Control(c) => (KIND_CONTROL, serde_json::to_vec(c)?),
            Frame::Audio { header, pcm } => {
                let mut p = Vec::with_capacity(AudioHeader::LEN + pcm.len());
                p.extend_from_slice(&AudioHeader { payload_len: pcm.len() as u32, ..*header }.to_bytes());
                p.extend_from_slice(pcm);
                (KIND_AUDIO, p)
            }
        };
        let len = payload.len() as u32 + 1;
        if len > MAX_FRAME {
            return Err(FrameError::TooLarge(len));
        }
        let mut out = Vec::with_capacity(4 + len as usize);
        out.extend_from_slice(&len.to_le_bytes());
        out.push(kind);
        out.extend_from_slice(&payload);
        Ok(out)
    }
}

pub fn write_frame(w: &mut impl Write, f: &Frame) -> Result<(), FrameError> {
    w.write_all(&f.encode()?)?;
    w.flush()?;
    Ok(())
}

pub fn read_frame(r: &mut impl Read) -> Result<Frame, FrameError> {
    let mut len = [0u8; 4];
    match r.read_exact(&mut len) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::UnexpectedEof => return Err(FrameError::Eof),
        Err(e) => return Err(e.into()),
    }
    let len = u32::from_le_bytes(len);
    if len == 0 || len > MAX_FRAME {
        return Err(FrameError::TooLarge(len));
    }
    let mut buf = vec![0u8; len as usize];
    r.read_exact(&mut buf).map_err(|e| if e.kind() == io::ErrorKind::UnexpectedEof { FrameError::Eof } else { e.into() })?;
    match buf[0] {
        KIND_CONTROL => Ok(Frame::Control(serde_json::from_slice(&buf[1..])?)),
        KIND_AUDIO => {
            let header = AudioHeader::from_bytes(&buf[1..])?;
            let pcm = buf[1 + AudioHeader::LEN..].to_vec();
            if pcm.len() != header.payload_len as usize {
                return Err(FrameError::BadAudioHeader);
            }
            Ok(Frame::Audio { header, pcm })
        }
        k => Err(FrameError::UnknownKind(k)),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn golden_control_frame() {
        // Format kabel dikunci: perubahan tak sengaja akan memecahkan kompatibilitas sidecar.
        let f = Frame::Control(Control::Ping { id: 7 });
        let bytes = f.encode().unwrap();
        let json = br#"{"type":"ping","id":7}"#;
        let mut expected = ((json.len() + 1) as u32).to_le_bytes().to_vec();
        expected.push(0);
        expected.extend_from_slice(json);
        assert_eq!(bytes, expected);
    }

    #[test]
    fn golden_audio_header() {
        let h = AudioHeader { version: 1, channel: 2, format: 0, channels: 1, sample_rate: 16_000, seq: 3,
                              sample_start: 48_000, host_time_ns: 1_000_000_000, payload_len: 8 };
        let b = h.to_bytes();
        assert_eq!(&b[..4], &[1, 2, 0, 1]);
        assert_eq!(u32::from_le_bytes(b[4..8].try_into().unwrap()), 16_000);
        assert_eq!(AudioHeader::from_bytes(&b).unwrap(), h);
    }

    #[test]
    fn roundtrip_and_errors() {
        let frames = vec![
            Frame::Control(Control::Hello { v: 1, binary: "x".into(), version: "0.0.1".into() }),
            Frame::Audio { header: AudioHeader { version: 1, channel: 0, format: 0, channels: 1, sample_rate: 16_000, seq: 1,
                                                 sample_start: 0, host_time_ns: 5, payload_len: 0 }, pcm: vec![1, 2, 3, 4] },
        ];
        let mut buf = vec![];
        for f in &frames {
            write_frame(&mut buf, f).unwrap();
        }
        let mut r = &buf[..];
        for f in &frames {
            let got = read_frame(&mut r).unwrap();
            match (f, &got) {
                (Frame::Audio { pcm: a, .. }, Frame::Audio { pcm: b, header }) => {
                    assert_eq!(a, b);
                    assert_eq!(header.payload_len, 4);
                }
                _ => assert_eq!(f, &got),
            }
        }
        assert!(matches!(read_frame(&mut r), Err(FrameError::Eof)));
        // Panjang rusak ditolak, bukan dialokasikan.
        let bad = u32::MAX.to_le_bytes();
        assert!(matches!(read_frame(&mut &bad[..]), Err(FrameError::TooLarge(_))));
    }
}
