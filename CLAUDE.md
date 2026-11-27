# CLAUDE.md — Smart Condens

## Qué es
Integración pública de Home Assistant (`custom_components/smart_condens`): análisis de calefacción por estancia, gas antes/después y dos ajustes de caldera por ebusd con confirmación.

## Por dónde empezar
1. `docs/STATUS.md`.
2. Solo el módulo afectado: `calc.py` (cálculos puros), `manager.py` (lecturas y estadísticas), `boiler.py` (escritura segura), `detect.py` (asistente), `gastur.py` (precios de Gas TUR), `panel.py` (panel).

## Reglas
- Público y anónimo; autor manu8613. Ni entidades, ni IPs, ni nombres reales.
- Cambios en rama y por PR. Nada de merge sin autorización.
- `boiler.py`: nunca escribir sin preparar + confirmar de un administrador; releer siempre. No añadir parámetros sin comprobar su definición en ebusd-configuration.
- Pruebas: `pip install -r requirements_test.txt && pytest -q`.
- Al terminar: bloque CIERRE y actualizar `docs/STATUS.md`.
