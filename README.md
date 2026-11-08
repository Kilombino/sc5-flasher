# sc5-flasher

Herramientas para investigar el **Goldshell SC5 Pro Ⅱ** sin brickearlo, en la línea de
[connorslab/paperclip-flasher](https://github.com/connorslab/paperclip-flasher) (que es para el KDBox,
placa MCB_V5_4; el SC5 Pro Ⅱ lleva otra placa, MCB_V3_3, así que no se puede usar tal cual).

> **Fase 1: solo lectura.** Nada de este código escribe en el minero. La API de cgminer
> solo acepta `version`, `summary`, `devs`, `pools` y `stats`, y la web solo hace `GET` a
> una lista cerrada de rutas. No hay login, ni reinicio, ni firmware, ni SSH. Los tests lo comprueban.

## Uso

Python 3.9+ sin dependencias.

```sh
python3 -m sc5 status 192.168.0.197          # informe de una vez
python3 -m sc5 status 192.168.0.197 --json   # lo mismo en JSON
python3 -m sc5 serve 192.168.0.197           # panel en http://127.0.0.1:8099
python3 -m unittest                          # tests
```

El panel no tiene contraseña: déjalo en `127.0.0.1` o en tu LAN, nunca expuesto a Internet.

## Fases

| Fase | Qué | Riesgo | Estado |
| --- | --- | --- | --- |
| 1 | Lectura: hashrate, temperaturas por placa, ventiladores, errores, pools | ninguno | hecho |
| 2 | Encender el SSH **de serie** e inspeccionar (CPU, particiones, arranque de intminer); copia hacia fuera | bajo | pendiente, con OK y sin alquiler activo |
| 3 | Cambios reversibles en la partición de datos, con copia y vuelta atrás automática | medio | solo si la fase 2 lo justifica |

Nunca: subir firmware, reset de fábrica, tocar el cargador de arranque ni probar voltajes sin vuelta atrás.

Lo que sabemos del aparato está en [docs/recon.md](docs/recon.md).
