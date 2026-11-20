use thiserror::Error;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum CompressionMode {
    /// Строго без потерь: никаких удалений символов, только сжатие
    Lossless = 0,
    /// Лёгкое прореживание (сохраняем опорные буквы/частицы, читаемость высокая)
    ReadablePrune = 1,
    /// Агрессивный скелет / дельты для максимальной экономии
    Aggressive = 2,
}

impl CompressionMode {
    pub fn from_u8(v: u8) -> Result<Self, UhcError> {
        match v {
            0 => Ok(Self::Lossless),
            1 => Ok(Self::ReadablePrune),
            2 => Ok(Self::Aggressive),
            _ => Err(UhcError::InvalidHeader(format!("unknown mode: {v}"))),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[repr(u8)]
pub enum DataKind {
    Raw = 0,
    AlphaText = 1,
    IdeographText = 2,
    DeltaSeries = 3,
}

impl DataKind {
    pub fn from_u8(v: u8) -> Result<Self, UhcError> {
        match v {
            0 => Ok(Self::Raw),
            1 => Ok(Self::AlphaText),
            2 => Ok(Self::IdeographText),
            3 => Ok(Self::DeltaSeries),
            _ => Err(UhcError::InvalidHeader(format!("unknown kind: {v}"))),
        }
    }
}

#[derive(Debug, Error)]
pub enum UhcError {
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
    #[error("Compression error: {0}")]
    Codec(String),
    #[error("Invalid frame or header: {0}")]
    InvalidHeader(String),
    #[error("Checksum mismatch: {0}")]
    ChecksumMismatch(String),
}
