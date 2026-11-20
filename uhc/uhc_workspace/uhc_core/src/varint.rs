use crate::types::UhcError;

/// Кодирует `u64` в LEB128 varint (7 полезных бит на байт, старший бит — флаг продолжения)
pub fn encode_u64(mut val: u64, out: &mut Vec<u8>) {
    while val >= 0x80 {
        out.push(((val as u8) & 0x7F) | 0x80);
        val >>= 7;
    }
    out.push(val as u8);
}

/// Декодирует `u64` из LEB128 varint, сдвигая `offset`
pub fn decode_u64(buf: &[u8], offset: &mut usize) -> Result<u64, UhcError> {
    let mut result: u64 = 0;
    let mut shift: u32 = 0;
    loop {
        if *offset >= buf.len() {
            return Err(UhcError::InvalidHeader("unexpected end of varint u64".into()));
        }
        let byte = buf[*offset];
        *offset += 1;
        if shift >= 64 {
            return Err(UhcError::InvalidHeader("varint u64 overflow".into()));
        }
        result |= ((byte & 0x7F) as u64) << shift;
        if (byte & 0x80) == 0 {
            return Ok(result);
        }
        shift += 7;
    }
}

/// ZigZag-кодирование знакового `i64` в беззнаковый `u64`
pub fn zigzag_encode_i64(n: i64) -> u64 {
    ((n << 1) ^ (n >> 63)) as u64
}

/// Обратное ZigZag-декодирование `u64` -> `i64`
pub fn zigzag_decode_i64(z: u64) -> i64 {
    ((z >> 1) as i64) ^ (-((z & 1) as i64))
}

#[repr(u8)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeltaOp {
    Add = 0,
    Sub = 1,
    Mul = 2,
    Div = 3,
}

impl DeltaOp {
    pub fn from_byte(b: u8) -> Result<Self, UhcError> {
        match b {
            0 => Ok(Self::Add),
            1 => Ok(Self::Sub),
            2 => Ok(Self::Mul),
            3 => Ok(Self::Div),
            _ => Err(UhcError::InvalidHeader(format!("invalid delta op: {b}"))),
        }
    }
}

/// Упаковывает текстовый журнал вида `100\n+15\n*3\n-20\n` в бинарный поток
pub fn pack_delta_lines(text: &str) -> Result<Vec<u8>, UhcError> {
    let mut lines = text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty());

    let first_str = lines
        .next()
        .ok_or_else(|| UhcError::InvalidHeader("empty delta series".into()))?;
    let x0: i64 = first_str
        .parse()
        .map_err(|_| UhcError::InvalidHeader(format!("bad initial value: {first_str}")))?;
    let mut current: i64 = x0;

    let mut ops: Vec<(DeltaOp, u64)> = Vec::new();
    for line in lines {
        let (op_char, num_str) = line.split_at(1);
        let op = match op_char {
            "+" => DeltaOp::Add,
            "-" => DeltaOp::Sub,
            "*" => DeltaOp::Mul,
            "/" => DeltaOp::Div,
            _ => return Err(UhcError::InvalidHeader(format!("unknown op in line: {line}"))),
        };
        let step: u64 = num_str
            .trim()
            .parse()
            .map_err(|_| UhcError::InvalidHeader(format!("bad step in line: {line}")))?;

        match op {
            DeltaOp::Add => current = current.saturating_add(step as i64),
            DeltaOp::Sub => current = current.saturating_sub(step as i64),
            DeltaOp::Mul => current = current.saturating_mul(step as i64),
            DeltaOp::Div => {
                if step == 0 {
                    return Err(UhcError::InvalidHeader("division by zero in delta".into()));
                }
                current /= step as i64;
            }
        }
        ops.push((op, step));
    }

    let mut out = Vec::with_capacity(16 + ops.len() * 3);
    encode_u64(zigzag_encode_i64(x0), &mut out);
    encode_u64(ops.len() as u64, &mut out);
    for (op, step) in ops {
        out.push(op as u8);
        encode_u64(step, &mut out);
    }
    Ok(out)
}

/// Распаковывает бинарный дельта-поток обратно в текстовый журнал
pub fn unpack_delta_lines(bin: &[u8]) -> Result<String, UhcError> {
    let mut off = 0usize;
    let x0 = zigzag_decode_i64(decode_u64(bin, &mut off)?);
    let count = decode_u64(bin, &mut off)? as usize;

    let mut cur = x0;
    let mut out = String::new();
    out.push_str(&format!("{cur}\n"));

    for _ in 0..count {
        if off >= bin.len() {
            return Err(UhcError::InvalidHeader("truncated delta ops".into()));
        }
        let op = DeltaOp::from_byte(bin[off])?;
        off += 1;
        let step = decode_u64(bin, &mut off)?;

        match op {
            DeltaOp::Add => {
                cur = cur.saturating_add(step as i64);
                out.push_str(&format!("+{step}\n"));
            }
            DeltaOp::Sub => {
                cur = cur.saturating_sub(step as i64);
                out.push_str(&format!("-{step}\n"));
            }
            DeltaOp::Mul => {
                cur = cur.saturating_mul(step as i64);
                out.push_str(&format!("*{step}\n"));
            }
            DeltaOp::Div => {
                if step == 0 {
                    return Err(UhcError::InvalidHeader("division by zero on unpack".into()));
                }
                cur /= step as i64;
                out.push_str(&format!("/{step}\n"));
            }
        }
    }

    Ok(out)
}
