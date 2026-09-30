# Caso Expreso · Puente LogiSur → Expreso Andino

Hoy, en LogiSur, alguien carga a mano en el portal de Expreso Andino los remitos del día. Este programa hace ese trabajo:

1. Lee el export diario de remitos de LogiSur.
2. Se queda con los que viajan por Expreso Andino, los limpia y los transforma al formato de su API.
3. Los carga en la API, maneja los errores y deja un **resumen para operaciones**: qué se cargó, qué no y qué hacer con cada uno.

Se puede correr todas las veces que haga falta **sin duplicar envíos**.

**Opcional (incluido):** consulta el estado de los envíos y lista los **atrasados**.

---

## Índice

- [Cómo correrlo](#cómo-correrlo)
- [Qué encontré en los datos](#qué-encontré-en-los-datos)
- [Cómo funciona](#cómo-funciona)
- [Decisiones de diseño](#decisiones-de-diseño)
- [Supuestos](#supuestos)
- [Resultados de la corrida](#resultados-de-la-corrida)
- [Qué cambiaría para usarlo en producción](#qué-cambiaría-para-usarlo-en-producción)

---

## Cómo correrlo

**Requisitos:** Python 3.9 o superior, igual que la API de prueba (probado en 3.10, 3.11, 3.12 y 3.13). **No hay que instalar nada**: usa solo la librería estándar.

### 1. Levantar la API de prueba (en una terminal aparte)

```bash
python3 kit/expreso_api.py
```

Queda escuchando en `http://localhost:8000`. Los datos viven en memoria: si se reinicia, arranca de cero.

### 2. Configurar la API key

La key se lee de una variable de entorno y no está escrita en el código.

```bash
# Linux / Mac
export EXPRESO_API_KEY=andino-test-7f3a91
```

```powershell
# Windows (PowerShell)
$env:EXPRESO_API_KEY = "andino-test-7f3a91"
```

### 3. Cargar los envíos del día

```bash
python3 -m expreso_bridge data/remitos_2026-09-30.json
```

En Windows puede ser `python` o `py` en lugar de `python3`.

Salida esperada en la primera corrida:

```
Remitos de Expreso Andino: 23 (de 51 en el export)
  Cargados:        19
  Ya existían:     1
  No cargados:     3
Resumen: resultados/resumen_remitos_2026-09-30_<fecha-hora>.md
Detalle: resultados/resumen_remitos_2026-09-30_<fecha-hora>.csv
```

Si se vuelve a correr, los 20 envíos válidos aparecen como **"ya existían"** y no se duplica ninguno.

### 4. (Opcional) Listar los envíos atrasados

```bash
python3 -m expreso_bridge.atrasados data/remitos_2026-09-30.json --hoy 2026-10-03
```

`--hoy` es opcional: si no se pasa, se usa la fecha real del día.

### Opciones

| Opción | Default | Para qué |
| --- | --- | --- |
| `--api-url` | `$EXPRESO_API_URL` o `http://localhost:8000` | Apuntar a otro entorno |
| `--salida` | `resultados` | Carpeta donde se guardan los resúmenes |
| `--max-intentos` | `4` | Intentos por envío ante errores de la API (solo carga) |

### Códigos de salida

Pensados para cuando el proceso se automatice y algo tenga que decidir si alertar:

| Código | Significado |
| --- | --- |
| `0` | Corrida completa. Puede haber remitos rechazados por datos: eso lo resuelve operaciones, el proceso hizo su trabajo. |
| `1` | Quedaron envíos pendientes porque la API siguió fallando. Conviene volver a correr más tarde (no duplica). |
| `2` | Error de configuración o de entrada: falta la API key, la key es inválida, no existe el archivo o la API no responde al inicio. |

### Tests

```bash
python3 -m unittest -v
```

29 tests. Incluyen un test de **punta a punta** que levanta la API de prueba del kit dentro del test, corre el proceso completo dos veces y verifica que cada envío exista una sola vez.

---

## Qué encontré en los datos

El export tiene **51 remitos**. Antes de escribir código los revisé uno por uno y encontré esto:

| Problema | Ejemplo | Qué hace el programa |
| --- | --- | --- |
| El transportista está escrito de 5 formas | `Expreso Andino`, `EXPRESO ANDINO `, `expreso andino`, `Exp. Andino` | Normaliza (minúsculas, sin puntuación ni espacios de más, `exp` → `expreso`) y compara |
| Remito duplicado | `R-10000507` aparece 2 veces con datos idénticos | Se envía una sola vez y se deja una nota en el resumen |
| Peso como texto con coma decimal | `"145,1"` | Se convierte a `145.1` |
| Provincias que no coinciden con las de la API | `BA`, `Bs. As.`, `CABA`, `Capital Federal`, `Cba`, `Tucuman`, `Neuquen` | Tabla de alias más comparación sin acentos contra la lista oficial de la API |
| Servicio con otros nombres | `NORMAL` / `URGENTE` | Se traduce a `standard` / `express` |
| Falta el código postal | `R-10000477` ("Cliente no informó CP") | **No se envía.** Se informa para corregir |
| Dirección en blanco | `R-10000516` (`"  "`) | **No se envía.** Se informa para corregir |
| 0 bultos | `R-10000541` | **No se envía.** Se informa para corregir |

Resultado: de 51 remitos, **24 son de Expreso Andino → 23 únicos → 20 válidos y 3 con datos a corregir.**

---

## Cómo funciona

```
export.json ──► extract ──► transform ──► load ──► report
               filtrar      validar y      API con    CSV + Markdown
               Andino y     convertir al   reintentos para operaciones
               deduplicar   formato API
```

| Archivo | Responsabilidad |
| --- | --- |
| `expreso_bridge/extract.py` | Leer el export, filtrar Expreso Andino y resolver duplicados |
| `expreso_bridge/transform.py` | Convertir cada remito al formato de la API y validarlo. Si algo no se puede interpretar con seguridad, se rechaza con un motivo claro |
| `expreso_bridge/api_client.py` | Hablar HTTP con la API (solo `urllib`). Los `GET` se reintentan acá mismo |
| `expreso_bridge/load.py` | Cargar un envío y decidir qué pasó según la respuesta (el corazón de la solución) |
| `expreso_bridge/pipeline.py` | Orquestar la corrida completa |
| `expreso_bridge/report.py` | Generar el resumen en CSV y en Markdown |
| `expreso_bridge/__main__.py` | Punto de entrada por línea de comandos |
| `expreso_bridge/atrasados.py` | Opcional: estado de los envíos y listado de atrasados |
| `tests/` | Tests unitarios y de punta a punta |
| `kit/` | API de prueba y su documentación (provistos por Geno, sin modificar) |
| `data/` | Export del día, tal como vino (no se modifica: la limpieza la hace el código) |

---

## Decisiones de diseño

### 1. Qué hacer con cada respuesta de la API

| Respuesta | Qué significa | Qué hace el programa |
| --- | --- | --- |
| `201` | Creado | ✅ **Cargado**, se guarda el `tracking_id` |
| `409` | Ya existe ese `external_ref` | ♻️ **Ya existía**. No es un error |
| `409` después de un `5xx` o un timeout | El envío se había creado aunque la API respondió con error | ✅ **Cargado (confirmado al reintentar)** |
| `422` | Datos inválidos | ❌ **Rechazado**, con el detalle de la API. No se reintenta: mandar lo mismo daría el mismo error |
| `500` / `503` / `429` / timeout / sin conexión | Falla del lado del expreso | 🔁 Se reintenta con espera creciente: 1 s, 2 s, 4 s (hasta 4 intentos) |
| `401` | API key inválida | 🛑 Se corta la corrida: si falla uno, van a fallar todos |
| Cualquier otro | Inesperado | ⚠️ Se informa como error, sin reintentar |

### 2. Cómo se evita duplicar envíos (idempotencia)

La API garantiza que `external_ref` es único y responde `409` si ya existe. Uso el número de remito como `external_ref`, así que **la propia API es la fuente de verdad**. Por eso el programa **no guarda estado local**: un archivo local puede quedar desactualizado (por ejemplo, si alguien corre el proceso desde otra máquina) y suma complejidad sin aportar seguridad.

### 3. Un error del servidor no significa que el envío no se creó

Un `500` o un timeout no garantizan que el envío **no** se haya creado: el servidor pudo haberlo guardado y fallar después. Si reintentamos y la API responde `409`, ese envío es el nuestro, no un duplicado de otra corrida. Por eso se marca como "cargado (confirmado al reintentar)" y no como error ni como "ya existía".

### 4. Validar antes de enviar, y no adivinar

Los remitos con datos incompletos o que no se pueden interpretar con seguridad (provincia desconocida, servicio desconocido, valor declarado inválido) **no se envían**. Se informan con un motivo en castellano y la acción a tomar. Mandar un envío con datos equivocados a un transporte real es peor que no mandarlo. Igual se maneja el `422` de la API como red de seguridad.

Si un remito tiene varios problemas, se informan **todos juntos**, así operaciones lo corrige de una sola vez.

### 5. Duplicados en el export

- **Mismos datos** → se envía una sola vez.
- **Mismo número de remito con datos distintos** (no pasa en este export, pero puede pasar) → **no se envía ninguno** y se marca como conflicto. No hay forma de saber cuál es el correcto.

### 6. Provincias

La lista de provincias válidas **se pide a la API** en cada corrida, en vez de escribirla en el código: si Expreso Andino la cambia, el programa sigue funcionando. Las abreviaturas (`BA`, `Cba`, `CABA`…) están en una tabla aparte (`ALIAS_PROVINCIAS`), fácil de ampliar.

### 7. El resumen para operaciones

- **CSV** separado por `;` y con BOM UTF-8. En Excel configurado en español la coma es el separador decimal, así que un CSV con comas se abre todo en una sola columna. El BOM hace que Excel muestre bien los acentos.
- **Markdown**: totales arriba, después solo lo que requiere atención con **qué hacer**, y al final la lista de cargados con su tracking. Sirve para leer rápido o pegar en un mail o chat.
- Estados en castellano para operaciones, con el código técnico en una columna aparte del CSV (`estado_codigo`) por si otro sistema lo quiere procesar.

### 8. Sin dependencias externas

Todo usa la librería estándar de Python, igual que la API de prueba: se clona el repo y se corre, sin instalar nada. Para un proceso de este tamaño, `requests` o `pytest` no aportan lo suficiente como para justificar la instalación.

---

## Supuestos

Los tomé como razonables. En un proyecto real los confirmaría con LogiSur o con Expreso Andino:

- **`nro_remito` es el identificador del envío** (`external_ref`). Un remito equivale a un envío.
- **`BA` y `Bs. As.` significan provincia de Buenos Aires**, y **`CABA` y `Capital Federal`** significan Ciudad Autónoma de Buenos Aires. Coincide con las localidades de cada remito (Pilar, Mar del Plata → provincia; Palermo, Caballito → CABA).
- **Los números con coma están en formato argentino**: la coma es decimal y el punto separa miles (`"1.234,5"` → `1234.5`). Un texto con solo punto (`"12.5"`) se toma como decimal.
- **`NORMAL` → `standard` y `URGENTE` → `express`.** Cualquier otro valor se rechaza en vez de asumir uno.
- **El teléfono es opcional**: si falta, el envío se carga igual. **El valor declarado también es opcional**, pero si viene con un valor inválido se rechaza el remito: descartarlo en silencio dejaría el envío sin seguro.
- **Campos del export sin equivalente en la API** (`cliente`, `volumen_m3`, `fecha_remito`, `observaciones`): no se envían. El cliente sí aparece en el resumen para operaciones.
- **Atrasado** = no está `DELIVERED` y su fecha estimada es **anterior** a hoy. Si vence hoy, todavía puede llegar en el día, así que no se marca. Los envíos en `EXCEPTION` que todavía están dentro de fecha se listan aparte como **"con incidencia"**: no son atrasados por definición, pero es lo primero que operaciones querría revisar.

### Limitación conocida

Si un remito se modifica en LogiSur **después** de haberse cargado (por ejemplo, cambia la dirección), al volver a correr la API responde `409` y el programa lo informa como "ya existía". **Los datos viejos siguen en Expreso Andino**, y la API no tiene un endpoint para actualizar un envío. Hoy eso requiere intervención manual. Ver el punto 6 de producción.

---

## Resultados de la corrida

En [`resultados/`](resultados/) están los archivos que generó el programa contra la API de prueba:

| Archivo | Qué muestra |
| --- | --- |
| `resumen_remitos_2026-09-30_20260930-160354.md` / `.csv` | **Primera corrida:** 19 cargados, 1 ya existía, 3 no cargados por datos |
| `resumen_remitos_2026-09-30_20260930-160402.md` / `.csv` | **Segunda corrida** (simula que alguien lo vuelve a correr por error): 0 cargados, 20 ya existían, **ningún duplicado** |
| `atrasados_2026-10-03_20260930-160403.md` / `.csv` | Envíos al 03/10/2026: 2 atrasados, 2 con incidencia, 9 en tiempo, 7 entregados |

Casos destacados de la primera corrida:

- **R-10000554** y **R-10000582**: la API respondió `503` dos veces y se cargaron al **tercer intento**.
- **R-10000612**: la API respondió `500`, pero el envío se había creado. El reintento devolvió `409` → **cargado (confirmado al reintentar)**, sin duplicado.
- **R-10000527**: ya existía en Expreso Andino desde una corrida anterior → **ya existía**.
- **R-10000477**, **R-10000516** y **R-10000541**: no enviados por falta de código postal, dirección en blanco y 0 bultos.

---

## Qué cambiaría para usarlo en producción

1. **Correrlo automáticamente** con una tarea programada (cron o Programador de tareas de Windows) apenas se genera el export, y **alertar según el código de salida**: si da `1`, reintentar más tarde; si da `2`, avisar a sistemas.
2. **Enviar el resumen a operaciones** por mail o chat al terminar cada corrida, en vez de que tengan que ir a buscar el archivo.
3. **Guardar la API key en un gestor de secretos** (o en las variables de entorno del servidor), nunca en el repositorio.
4. **Logs estructurados** de cada llamada a la API (remito, código de respuesta, intento, duración), para poder auditar y diagnosticar sin depender del resumen.
5. **Historial de corridas** en una base de datos: qué se cargó, cuándo y con qué tracking. Útil para auditoría y reportes, aunque la idempotencia siga dependiendo de la API.
6. **Detectar remitos modificados después de cargados**: guardar un hash de los datos enviados y, si un remito vuelve con datos distintos y la API responde `409`, avisar a operaciones en vez de marcarlo como "ya existía". Y hablar con Expreso Andino para ver si ofrecen una forma de actualizar o anular envíos.
7. **Mover `ALIAS_PROVINCIAS` a un archivo de configuración**, para que operaciones pueda agregar variantes nuevas sin tocar el código. Mejor aún: pedirle a LogiSur que su sistema use listas cerradas de transportistas y provincias, así el problema se corrige en el origen.
8. **Validaciones extra**: que el código postal sea coherente con la provincia, rangos razonables de peso y bultos.
9. **Si el volumen crece mucho**: cargar envíos en paralelo con un límite de concurrencia, y respetar el header `Retry-After` si la API lo envía.
10. **CI con GitHub Actions** que corra los tests en cada push.
11. **Correr el listado de atrasados todos los días** y avisar solo cuando aparece un atraso nuevo.
