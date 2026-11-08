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

## Mecanismo del SSH (análisis estático, 8 nov 2026)

Goldshell no publica el firmware del SC5 Pro Ⅱ. Se analizó el oficial **KD5 2.2.0**, que usa la
**misma placa MCB_V3_3**, del repo `goldshellminer/firmware`. El `.cpb` lleva una cabecera de 512 B
(`firmware-MCB_V3_3.tgz`) y después un `.tgz`; dentro, `firmware.ius` empieza por `+ius` y lleva el
rootfs squashfs incrustado. Todo se extrajo e inspeccionó **sin ejecutar nada** (unsquashfs +
desensamblado ARM Thumb con capstone).

Hallazgos:

- `minerd` registra los handlers de `/mcb/*` en una tabla. **En el arranque ejecuta
  `/etc/init.d/S50sshd stop`**, así que el SSH queda apagado por defecto.
- **`PUT /mcb/protect`** es el único handler que reenciende el SSH: llama a un envoltorio tipo
  `system()` con `/etc/init.d/S50sshd start`. **`PUT /mcb/defend`** ejecuta el `stop`.
- El firmware incluye OpenSSH real (`/usr/sbin/sshd`, `/usr/bin/ssh-keygen`), `sshd_config` por
  defecto (puerto 22, `PermitRootLogin yes`, `PasswordAuthentication yes`) y usuario `root`.
  `S50sshd` genera las claves de host la primera vez (puede tardar 1-2 min) y sale sin hacer nada
  si falta `ssh-keygen`.

En el minero real, `PUT /mcb/protect` devolvió 200 pero el puerto 22 siguió cerrado (escaneo
completo), sin reiniciar ni perder hashrate. Hipótesis: la variante del SC5 aplica el cambio solo
al reiniciar, o las claves de host tardaban. **Paso seguro pendiente:** reiniciar una vez con
`/mcb/protect` ya aplicado y comprobar el 22. No se toca firmware ni arranque.
