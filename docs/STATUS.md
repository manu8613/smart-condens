# Estado

**Versión:** 0.1.0, en PR (sin fusionar).

## Comprobado
- 25 pruebas automáticas.
- El asistente propone entidades y estancias (`detect.py`); solo con nombres inventados.
- Home Assistant 2026.11.3 de pruebas, con MQTT real y caldera simulada: instalación, estancias, panel, gas y un cambio confirmado de principio a fin.

## Sin comprobar
- Escritura en una caldera real: ni que ebusd acepte `FlowsetHcMax` y `PumpPowerDesired` en el modelo concreto, ni que la caldera los aplique.
- Utilidad de los consejos con datos reales de varios días.
- Aciertos de la detección automática en una instalación real.

## Pendiente
- Primera lectura real con «Leer de la caldera» (sin escritura activada).
- Publicar versiones con etiqueta cuando la primera esté validada.
