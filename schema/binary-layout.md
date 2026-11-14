# Snapshot binary layout (`snapshot.bin`)

The compact binary form of an Insurgency Report. Decoded by `rebellion-core` (Rust/WASM)
and produced by `pipeline` (Python). **Single source of truth** — change both sides together.

- Byte order: **little-endian**
- Magic: ASCII `RBMN` ("Rebellion of the Machines")

## Header — 16 bytes

| Offset | Field       | Type      | Notes                                   |
| ------ | ----------- | --------- | --------------------------------------- |
| 0      | `magic`     | `[u8; 4]` | `RBMN` (0x52 0x42 0x4D 0x4E)            |
| 4      | `version`   | `u8`      | currently `1`                           |
| 5      | `_pad`      | `[u8; 3]` | zero padding (keeps records 4-aligned)  |
| 8      | `date_days` | `u32`     | report date, days since Unix epoch      |
| 12     | `count`     | `u32`     | number of records that follow           |

## Record — 24 bytes each (`count` of them)

| Offset | Field        | Type      | Notes                                         |
| ------ | ------------ | --------- | --------------------------------------------- |
| 0      | `lat`        | `f32`     | source latitude (degrees)                     |
| 4      | `lon`        | `f32`     | source longitude (degrees)                    |
| 8      | `tgt_lat`    | `f32`     | assault-vector target latitude                |
| 12     | `tgt_lon`    | `f32`     | assault-vector target longitude               |
| 16     | `severity`   | `u8`      | 0 Flatline · 1 Haunting · 2 Possession · 3 Singularity |
| 17     | `source`     | `u8`      | 0 Feodo · 1 URLhaus · 2 other                 |
| 18     | `country`    | `[u8; 2]` | ISO-3166 alpha-2, ASCII (e.g. `US`)           |
| 20     | `first_seen` | `u32`     | first-seen date, days since Unix epoch        |

Total file size = `16 + 24 * count` bytes.

## Validation rules

- Reject if `magic != RBMN` or `version != 1`.
- Reject if remaining bytes `!= 24 * count`.
- `severity` must be 0–3; `source` must be 0–2; out-of-range values are clamped and logged.
