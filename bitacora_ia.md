# Bitácora de IA · ES3 (TI3021)

**Estudiante:** Benjamín Leppe · **Rama:** `e3/leppe` · **Proyecto base:** EcoTech (E2, equipo Fuentealba–Bustos–Leppe)

> Este documento registra **qué generó la IA, qué se revisó y qué se decidió** (aceptar, modificar o descartar).
> Las secciones 1 a 6 describen el proceso real de esta entrega. La **sección 7 la completo yo con mis propias palabras**
> después de ejecutar y entender cada parte.

---

## 1. Herramienta usada y alcance

| Dato | Detalle |
|---|---|
| Herramienta | Claude (Anthropic), modelo Opus 5.5, en claude.ai |
| Fecha | 13-11-2026 |
| Instrucción que le di | *"Revisa la evaluación 5 de la página de INACAP, luego revisa el GitHub y modifícalo con lo que piden las instrucciones."* La IA leyó la guía `TI3021_U3_ES03_GUIA.docx`, la evaluación 5 del AAI (instrucciones y rúbrica) y el código de la rama `e3/leppe`. |
| Código generado por IA | `api_cliente.py`, `deserializador.py`, `dominio/externos.py`, `repositorio/externos_repo.py`, `repositorio/usuario_repo.py`, `servicios/autenticacion.py`, `servicios/externos.py`, `herramientas/auditoria_ia.py`, `pruebas/test_e3.py`, cambios en `main.py`, `dominio/validaciones.py`, `datos/schema.sql`, `.env.example`, `requirements.txt` |
| Código de la E2 que no se tocó | Clases de `dominio/` (excepto `validaciones.py`) y repositorios de empleados, departamentos, proyectos y registros |

**APIs elegidas:**
- **Clima:** Open-Meteo (`geocoding-api.open-meteo.com` para pasar de ciudad a coordenadas, `api.open-meteo.com` para el clima actual).
- **Tipo de cambio:** mindicador.cl (dólar y euro en pesos chilenos, del Banco Central).

Ninguna de las dos pide API key para uso no comercial, así que **no hay secretos que proteger en el repositorio**. Aun así, el código admite una clave opcional desde `.env`.

---

## 2. Cómo se auditó el código

1. **Auditoría automática:** `python herramientas/auditoria_ia.py` recorre todos los `.py` con el árbol sintáctico de Python (`ast`) y busca las 5 señales de riesgo. Se usa `ast` y no búsqueda de texto para no confundir comentarios con código. Para comprobar que detecta de verdad, se probó con un archivo malo a propósito (f-string en SQL, `verify=False`, `except: pass`, `get()` sin timeout y `import requestz`): marcó las 5 señales.
2. **Pruebas automáticas:** `python -m unittest -v pruebas.test_e3` ejecuta 23 pruebas que simulan las APIs (404, 429, 500, sin red, timeout, JSON roto), además de la base de datos, el login y el Plan B. No necesitan internet.
3. **Ejecución real sin internet:** se corrió `main.py` con la red bloqueada. Hizo los reintentos, activó el Plan B y no se cayó.
4. **Revisión manual** de lo que la herramienta marca como "revisar".

---

## 3. Las 5 señales de riesgo

| # | Señal | Resultado en la versión final | Evidencia |
|---|---|---|---|
| 1 | f-strings / concatenación en SQL | **0 hallazgos.** Todas las consultas usan `?` | `auditoria_ia.py` + revisión de `repositorio/*.py` |
| 2 | `verify=False` | **0.** Nunca se desactiva TLS; si el certificado falla (`SSLError`) se corta sin reintentar | `api_cliente.py`, prueba `test_exito_envia_timeout_y_no_desactiva_tls` |
| 3 | `except: pass` | **0.** Cada `except` captura un tipo concreto, informa al usuario y registra en `ecotech.log` | `auditoria_ia.py` |
| 4 | Llamadas sin timeout | **0.** La única llamada HTTP (`ClienteAPI.obtener_json`) usa `timeout=(3.05, 10)` | prueba que verifica el timeout en cada llamada |
| 5 | Librerías inexistentes en PyPI | **0.** Solo `requests`, `bcrypt` y `python-dotenv`, versiones fijadas en `requirements.txt` y descargadas con `pip download` para confirmar que existen | `requirements.txt`, `auditoria_ia.py` |

---

## 4. Problemas que se encontraron en el código generado y cómo se corrigieron

Estos casos ocurrieron en esta entrega: la IA generó una versión, la revisión encontró el problema y se cambió.

| # | Dónde | Problema | Decisión | Justificación técnica |
|---|---|---|---|---|
| H1 | `pruebas/test_e3.py` | Limpieza de tablas con `conn.execute(f"DROP TABLE IF EXISTS {tabla}")`. **La detectó `auditoria_ia.py`.** | **Modificado:** tres sentencias literales | El nombre venía de una tupla fija (no era explotable), pero la regla es *cero* f-strings en SQL. Además, un f-string en SQL se copia fácilmente a un lugar donde sí entra texto del usuario. |
| H2 | `api_cliente.py`, lectura de `Retry-After` | `except (TypeError, ValueError): pass`. **La marcó `auditoria_ia.py`.** | **Modificado:** ahora registra una advertencia y usa el backoff normal | Un `pass` esconde el error. Con el log, si la API manda una cabecera rara queda evidencia para diagnosticar. |
| H3 | `repositorio/externos_repo.py` | Los `SELECT` se armaban con `"SELECT " + self._COLUMNAS + " FROM ..."` | **Modificado:** SQL literal completo | La constante no venía del usuario, pero era concatenación en SQL y la pauta exige cero. |
| H4 | `api_cliente.py`, constructor | Si en `.env` la URL estaba mal (ej. `htps://...`), lanzaba `ValueError` al crear el cliente y **el programa se caía al iniciar** | **Modificado:** la URL se valida en cada consulta y lanza `ErrorCliente`, lo que activa el Plan B | Una configuración errónea no debe botar todo el sistema (criterio 3.1.3, continuidad operativa). Sigue exigiéndose HTTPS. |
| H5 | `servicios/autenticacion.py` | `bcrypt` 5.x lanza `ValueError` con contraseñas de más de 72 bytes, lo que podía botar el login | **Modificado:** la política rechaza más de 72 bytes al registrar, y el login recorta a 72 bytes antes de comparar | Así una entrada larga o maliciosa no provoca una excepción no controlada. |
| H6 | `api_cliente.py`, manejo de 429 | Respetar a ciegas `Retry-After: 120` dejaría al usuario 2 minutos esperando | **Modificado:** se respeta si la espera es de 8 s o menos; si es mayor, se pasa al Plan B | Se cumple el contrato de la API sin bloquear la aplicación. |
| H7 | `main.py`, entrada de pagos | Los montos en pesos salían con coma (`1,200,000`) | **Modificado:** formato chileno `1.200.000` | Claridad para el usuario final. |

**Revisión manual de la E2.** La auditoría marca 5 consultas de la E2 que arman el SQL en una variable `sql` (`listar()` de cada repositorio). Las revisé: solo concatenan **textos fijos** (`" WHERE nombre LIKE ?"`, `" ORDER BY nombre"`) y los valores del usuario van siempre en `params` con `?`. **No son vulnerables y se dejaron igual** para no modificar código del equipo que está fuera del alcance de la E3.

---

## 5. Decisiones: qué se aceptó, qué se descartó y por qué

| Propuesta / alternativa | Decisión | Por qué |
|---|---|---|
| `requests` como librería HTTP | **Aceptado** | Es la librería que recomienda la guía, valida TLS por defecto y `Session` reutiliza la conexión. |
| Reintentos con `HTTPAdapter(max_retries=Retry(...))` de urllib3 | **Descartado** | Oculta la lógica: no permite decidir el Plan B por tipo de error ni probar las esperas. Se programaron los reintentos a mano, de forma explícita y probada. |
| Librería `tenacity` para reintentos | **Descartado** | Agrega una dependencia más por algo que son 30 líneas claras. |
| `hashlib.sha256(password)` para contraseñas | **Descartado** | SHA-256 es rápido (millones de intentos por segundo en GPU) y sin salt, vulnerable a tablas precalculadas. |
| `bcrypt` con costo 12 | **Aceptado** | Es lento a propósito (unos 0,2 s), incluye un salt aleatorio por usuario dentro del hash y lo pide la pauta. `argon2` también era válido; se eligió bcrypt por simplicidad. |
| Mensaje "usuario no existe" distinto de "contraseña incorrecta" | **Descartado** | Revelaría qué usuarios existen. Se muestra siempre "Usuario o contraseña incorrectos" y se gasta el mismo tiempo (comparación contra un hash falso). |
| Bloqueo tras 5 intentos fallidos durante 5 minutos | **Aceptado** | Frena la fuerza bruta sin bloquear para siempre. |
| Guardar la serie completa de mindicador (unos 30 días) | **Descartado** | Solo se usa el valor más reciente (criterio 3.1.1.I.3: extraer únicamente lo relevante). |
| `INSERT` simple al guardar datos de las APIs | **Descartado** | Duplicaría registros al correr dos veces. Se usa `UNIQUE` + `ON CONFLICT DO UPDATE` (upsert): la segunda vez actualiza `obtenido_en`. |
| Mostrar `str(e)` de la excepción al usuario | **Descartado** | Puede incluir URLs, rutas o detalles internos. Cada `ErrorAPI` trae un `mensaje_usuario` seguro, y el detalle va a `ecotech.log` sin query string (donde iría una API key). |
| `except Exception` en `Menu._ejecutar` | **Aceptado con condiciones** | Es la última barrera de la interfaz: registra con `log.exception` (traza completa en el log) y muestra un mensaje genérico. No es un `except: pass`, porque el error queda registrado y el programa sigue. |

---

## 6. Cómo comprobar las 4 pruebas en vivo del docente

| Prueba | Qué hacer | Qué debe pasar |
|---|---|---|
| **Ejecución consecutiva** | Ejecutar `python main.py` dos veces y consultar la misma ciudad o moneda. Luego, en *Servicios externos → Ver datos guardados*, mirar el total. | El total **no aumenta** por repetir la consulta (upsert sobre `UNIQUE`). Ojo: Open-Meteo publica una medición nueva cada 15 minutos; si pasan más de 15 minutos entre una consulta y otra, se agrega una fila porque es una medición distinta, no un duplicado. |
| **Corte de red** | Desconectar el WiFi y consultar el clima o el dólar. | 3 intentos con espera creciente (unos 4 s) y luego: *"⚠ No hay conexión con el servicio. Mostrando el último dato guardado (obtenido_en …, hace …)"*. Sin trazas de error. |
| **URL inválida** | En `.env` poner `API_INDICADORES_URL=https://mindicador.cl/api/no-existe` y consultar el dólar. | HTTP 404, **sin reintentos** (es un error 4xx) y Plan B con el motivo *"El servicio no encontró el recurso solicitado (HTTP 404)"*. |
| **Tabla de usuarios** | `python -c "import sqlite3; print(sqlite3.connect('ecotech.db').execute('SELECT nombre_usuario, hash_password FROM usuario').fetchall())"` (o abrir `ecotech.db` con DB Browser for SQLite) | Solo hashes `$2b$12$...`, ninguna contraseña legible. |

---

## 7. Validación personal (completar yo, con mis palabras)

- [ ] Ejecuté `python -m unittest -v pruebas.test_e3` y pasaron las 23 pruebas.
- [ ] Ejecuté `python herramientas/auditoria_ia.py` y las 5 señales dieron OK.
- [ ] Probé las 4 pruebas en vivo de la sección 6 en mi computador.
- [ ] Puedo explicar sin mirar: qué hace el backoff exponencial, por qué un 404 no se reintenta y un 503 sí, qué es el salt de bcrypt y qué es un upsert.

**Mi análisis** (qué entendí, qué cambiaría yo, qué me costó):

_…escribir aquí…_
