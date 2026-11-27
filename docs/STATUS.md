# Estado

**Versión:** 0.3.0, en PR (sin fusionar). La 0.2.0 está en `main`.

## Comprobado
- 34 pruebas automáticas.
- Gas TUR (`gastur.py`): depende de los atributos de su sensor de precio (`historial`, `iva`, `impuesto_hidrocarburos`, `alquiler_contador_dia`, `factor_conversion`).
- El asistente propone entidades y estancias (`detect.py`); solo con nombres inventados.
- Home Assistant 2026.11.3 de pruebas, con MQTT real y caldera simulada: instalación, estancias, panel, gas y un cambio confirmado de principio a fin.

## Sin comprobar
- Escritura en una caldera real: ni que ebusd acepte `FlowsetHcMax` y `PumpPowerDesired` en el modelo concreto, ni que la caldera los aplique.
- Utilidad de los consejos con datos reales de varios días.
- Aciertos de la detección automática en una instalación real.

## Pendiente
- Primera lectura real con «Leer de la caldera» (sin escritura activada).
- Publicar versiones con etiqueta cuando la primera esté validada.
