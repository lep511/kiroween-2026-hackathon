# Snapshot binary layout (`snapshot.bin`)

The compact binary form of an Insurgency Report. Decoded by `rebellion-core` (Rust/WASM)
and produced by `pipeline` (Python). **Single source of truth** — change both sides together.

Each record is one **Machine Strike**: a real cyberattack reported by a recognized news
outlet (the "witness"). The binary carries only what the globe needs to *draw* a strike
fast; the full dossier (headline, stolen data, fallout, ward, article URL) lives in the
companion `snapshot.json`, joined to each strike by its `id`.

- Byte order: **little-endian**
- Magic: ASCII `RBMN` ("Rebellion of the Machines")
- Version: **2** (v1 was the legacy botnet-IP layout; see git history)

## Header — 16 bytes

| Offset | Field       | Type      | Notes                                   |
| ------ | ----------- | --------- | --------------------------------------- |
| 0      | `magic`     | `[u8; 4]` | `RBMN` (0x52 0x42 0x4D 0x4E)            |
| 4      | `version`   | `u8`      | currently `2`                           |
| 5      | `_pad`      | `[u8; 3]` | zero padding (keeps records 4-aligned)  |
| 8      | `date_days` | `u32`     | report date, days since Unix epoch      |
| 12     | `count`     | `u32`     | number of records that follow           |

## Record — 28 bytes each (`count` of them)

| Offset | Field         | Type      | Notes                                                        |
| ------ | ------------- | --------- | ------------------------------------------------------------ |
| 0      | `id`          | `u32`     | join key into `snapshot.json` (the strike's dossier)         |
| 4      | `lat`         | `f32`     | **ground zero** latitude (where the strike landed)           |
| 8      | `lon`         | `f32`     | **ground zero** longitude                                    |
| 12     | `origin_lat`  | `f32`     | attributed origin latitude (attacker; == ground zero if none)|
| 16     | `origin_lon`  | `f32`     | attributed origin longitude                                  |
| 20     | `severity`    | `u8`      | 0 Flatline · 1 Haunting · 2 Possession · 3 Singularity       |
| 21     | `witness`     | `u8`      | 0 BBC · 1 WaPo · 2 NYT · 3 CNN · 4 The Hacker News · 5 HackerNoon · 6 other |
| 22     | `country`     | `[u8; 2]` | ISO-3166 alpha-2 of ground zero, ASCII (e.g. `FR`)           |
| 24     | `published`   | `u32`     | article publication date, days since Unix epoch              |

Total file size = `16 + 28 * count` bytes.

The on-globe arc (Assault Vector) is drawn from `origin` → ground zero; when attribution is
unknown the two coincide and the arc collapses to the point.

## Validation rules

- Reject if `magic != RBMN` or `version != 2`.
- Reject if remaining bytes `!= 28 * count`.
- `severity` must be 0–3; `witness` must be 0–6; out-of-range values are clamped and logged.
