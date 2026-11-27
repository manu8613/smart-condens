# Smart Condens

Integración de Home Assistant para ver si la temperatura de ida de una caldera de condensación es la adecuada, estancia por estancia, y cuánto cambia el gasto de gas.

## Qué muestra

- **Hoy:** consejo (subir, mantener o bajar), ida y retorno, temperatura exterior y estado de cada estancia: temperatura, válvula, desfase entre válvula y sonda, calor estimado del radiador.
- **Ondas:** gráficas de ida, retorno, calle y de cada estancia.
- **Gas:** kWh por grado-día antes y después de un cambio, coste diario y cuánto sube o baja.
- **Ajustar caldera** (opcional): tope de ida (d.71) y potencia de la bomba (d.14) por ebusd, siempre con confirmación.

Solo usa tarjetas propias de Home Assistant. Los textos de los indicadores están en español.

## Instalación

Requiere Home Assistant 2026.10 o posterior, con el registro histórico activo.

1. **Ajustes → Marketplace → Añadir desde enlace**, pega `https://github.com/manu8613/smart-condens` y descarga.
2. Reinicia Home Assistant.
3. **Ajustes → Dispositivos y servicios → Añadir integración → Smart Condens** y elige tus entidades: exterior, ida, retorno y, si quieres, quemador, arranques, contador de gas, precio y fecha del cambio.
4. En la misma pantalla de la integración, **Añadir estancia** por cada una: válvula o termostato, sonda de la estancia (si se deja vacía se usa la de la válvula), demanda, elementos del radiador y posición en el anillo monotubo.
5. Abre **Smart Condens** en la barra lateral.

Haz una copia de seguridad antes de instalar.

## Qué esperar

| Dato | Cuándo aparece |
|---|---|
| Estado de las válvulas | Al momento («Abierta, esperando» la primera hora) |
| Subida y bajada en °C/h | Tras dos muestras horarias |
| Consejo de ida | Tras 12 horas, y 3 días después de un cambio |
| Inercia térmica | Tras 6 horas de enfriamiento |
| Gas antes y después | Con 3 días fríos en cada periodo; fiable a partir de 14 |

Son **estimaciones**. Los vatios del radiador suponen un reparto lineal de temperatura a lo largo del anillo y necesitan los elementos de cada radiador. Una estancia con sonda configurada que deje de responder aparece «Sin datos»: no se sustituye en silencio por la de la válvula.

## Cambiar ajustes de la caldera

Desactivado por defecto. **Escribe en ajustes de instalador de la caldera**: hazlo bajo tu responsabilidad y, si dudas, que lo haga un técnico.

Cómo se protege:

1. Se elige el valor nuevo (no envía nada).
2. **Preparar** lee el valor actual y muestra qué se va a cambiar y a qué afecta. Caduca a los 2 minutos.
3. **Confirmar** pide una segunda confirmación, vuelve a leer, escribe una sola vez y relee para comprobar.

Preparar y confirmar solo funcionan pulsados por un administrador (no desde automatizaciones), hay 60 segundos entre cambios y los rangos están limitados (ida 45–70 °C).

### Qué hace falta

- ebusd con MQTT y la caldera en el circuito `bai`.
- Que ebusd permita escribir: añadir `--accesslevel=install` a sus opciones.

Con esa opción, **cualquier cliente de tu MQTT** (o del puerto TCP de ebusd) puede escribir ajustes de instalador. Mitigación: usuario y contraseña en el broker, sin exponer los puertos de ebusd, y quitar la opción cuando termines.

Límites conocidos:

- d.71 es un **tope**: bajarlo limita la ida; subirlo puede no subirla si el mando de la caldera está más bajo.
- No todas las calderas lo admiten. En algunos perfiles de ebusd la escritura está marcada como no confirmada y se rechaza, y hay calderas que la ignoran. En ambos casos se avisa «NO aplicado».
- No es un control automático: nunca cambia nada por sí sola.

## Licencia

MIT. Creado por [manu8613](https://github.com/manu8613).
