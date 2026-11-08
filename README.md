# sc5-flasher

Herramientas para investigar el **Goldshell SC5 Pro Ⅱ** sin brickearlo, en la línea de
[connorslab/paperclip-flasher](https://github.com/connorslab/paperclip-flasher) (que es para el KDBox,
placa MCB_V5_4; el SC5 Pro Ⅱ lleva otra placa, MCB_V3_3, así que no se puede usar tal cual).

Python 3.9+ sin dependencias.

## Panel de solo lectura

```sh
python3 -m sc5 status 192.168.0.197          # informe de una vez
python3 -m sc5 status 192.168.0.197 --json   # lo mismo en JSON
python3 -m sc5 serve 192.168.0.197           # panel oscuro en http://127.0.0.1:8099
python3 -m unittest                          # tests
```

No escribe nada: la API de cgminer solo acepta `version`, `summary`, `devs`, `pools` y
`stats`, y la web solo hace `GET` a una lista cerrada de rutas.

## Panel con control

```sh
# contraseña del panel del minero, FUERA del repo:
install -m700 -d ~/.config/sc5-flasher
printf 'SC5_HOST=192.168.0.197\nSC5_WEB_PASSWORD=tu_contraseña\n' > ~/.config/sc5-flasher/secrets.env
chmod 600 ~/.config/sc5-flasher/secrets.env

python3 -m sc5 serve 192.168.0.197 --control   # panel con botones
```

Con `--control` el panel añade solo acciones **reversibles y de fábrica**:

- **Modo**: Hash (700 MHz) · Eco (513 MHz) · Reposo (0 MHz) — los presets del firmware.
- **Ventilador por temperatura**: activar/desactivar.
- **LED de identificación**: encender/apagar.
- **Reiniciar** el minero (~1-2 min sin minar; vuelve solo).

El navegador nunca manda una ruta ni un cuerpo crudo: solo un nombre de acción de una lista
cerrada (`sc5/control.py`), que el backend traduce a una operación fija. **No hay ningún camino a
`/mcb/facrst` (reset de fábrica) ni `/mcb/uploadimage` (firmware)**, así que el panel no puede
brickear el minero. Cada cambio de ajuste es leer-modificar-escribir sobre el propio objeto del
minero. La contraseña se lee de `secrets.env`, nunca del navegador ni del repo.

El panel no tiene login propio: déjalo en `127.0.0.1` o en tu LAN de confianza, nunca en Internet.

## Fases

| Fase | Qué | Riesgo | Estado |
| --- | --- | --- | --- |
| 1 | Lectura: hashrate, temperaturas por placa, ventiladores, errores, pools | ninguno | hecho |
| 2 | Encender el SSH **de serie** e inspeccionar (CPU, particiones, arranque de intminer); copia hacia fuera | bajo | pendiente, con OK y sin alquiler activo |
| 3 | Cambios reversibles en la partición de datos, con copia y vuelta atrás automática | medio | solo si la fase 2 lo justifica |

Nunca: subir firmware, reset de fábrica, tocar el cargador de arranque ni probar voltajes sin vuelta atrás.

Lo que sabemos del aparato está en [docs/recon.md](docs/recon.md).
