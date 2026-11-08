# Reconocimiento (8 nov 2026, solo lectura)

## Aparato

| | |
| --- | --- |
| Modelo | `Goldshell-SC5ProⅡ` |
| Hardware | `30.50.SA` |
| Placa de control | `MCB_V3_3` |
| Firmware | `2.2.0` |
| Minero | intminer 5.4.2 (cgminer/BFGMiner, API 3.1) |
| Algoritmo | `blake2b(SC)`: el mismo identificador que paperclip-flasher usa para BLAKE2b (XBT) |
| Hashboards | 4, a 700 MHz y 11,74 V; ~3,5 TH/s cada una, ~14 TH/s en total |
| Temperaturas | 3 sensores por placa (`tstemp-0..2`); 86–90 °C en el punto caliente |
| Planes de energía | `700 MHz 11750 V` (actual), `513 MHz 10700 V`, `0 MHz` (parado) |

## Puertos

- **80**: web (Vue, título `cloud-box`) y API `/mcb/*`.
- **4028**: API de cgminer en JSON. La respuesta a `stats` viene rota (falta una coma entre
  objetos: `}{`); `sc5.api.parse_cgminer` lo arregla.
- **22 (SSH)**: cerrado.

## API web

Login: `GET /user/login?username=admin&password=…` → `{"JWT Token": "…"}`. Con `&cipher=false`
devuelve 500. El token es siempre el mismo y no lleva caducidad (`aud: yotta mc`, `sub: minerd`).

**Fallo de seguridad:** `/mcb/status`, `/mcb/setting` y `/mcb/pools` responden **sin token**, y
`/mcb/pools` incluye las contraseñas de los pools. No se ha probado si las escrituras también
funcionan sin token (eso ya sería escribir).

Rutas que usa la interfaz (de su JS):

- Lectura: `status`, `setting`, `pools`, `algosetting`, `ip`, `tutorial`, `cmossetting`, `rgbsetting`, `wifisetting`, `wifiresult`, `resultpool`, `cgminer`.
- **Escritura (no tocar en fase 1):** `PUT setting`, `PUT algosetting`, `newpool`, `delpool`,
  `PUT ip`, `PUT wifisetting`, `PUT rgbsetting`, `PUT cmossetting`, `PUT restart`, `PUT facrst`
  (reset de fábrica), `POST uploadimage` (firmware), `PUT protect`, `PUT defend`, `/user/updatepd`.

Según paperclip-flasher, en el KDBox `PUT /mcb/protect` es lo que enciende el SSH de serie. Falta
confirmar que en el SC5 Pro Ⅱ hace lo mismo antes de usarlo (fase 2).
