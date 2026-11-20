# EcoTech Solutions · Sistema de Gestión de Empleados

Programa de consola en Python para registrar empleados, departamentos, proyectos y horas trabajadas.
Los datos se guardan en una base SQLite.

**Equipo:** Miguel Fuentealba (líder), Benjamín Leppe y Gonzalo Bustos · TI3021 · ES2
**ES3 (rama `e3/leppe`):** Benjamín Leppe · consumo seguro de APIs, autenticación y resiliencia

## Cómo ejecutarlo

1. Crear y activar el entorno virtual:
   ```
   python -m venv .venv
   .venv\Scripts\activate
   ```
   En Mac o Linux, el segundo comando es `source .venv/bin/activate`.
2. Instalar las dependencias: `pip install -r requirements.txt`
3. Copiar `.env.example` con el nombre `.env` (no hay que cambiarle nada).
4. Ejecutar: `python main.py`

Al abrirse, el programa prueba la conexión, crea las tablas si no existen y pide iniciar sesión.
La primera vez pide crear el usuario administrador.

## Carpetas

| Carpeta o archivo | Qué tiene |
|---|---|
| `dominio/` | Las clases del negocio, sus validaciones y sus excepciones |
| `repositorio/` | La conexión a la base y las consultas SQL |
| `servicios/` | Autenticación (bcrypt + sesión) y servicios de clima e indicadores con Plan B |
| `api_cliente.py` | Cliente HTTP: timeout, reintentos con backoff, manejo por código HTTP |
| `deserializador.py` | Valida el JSON de las APIs y lo convierte en objetos del dominio |
| `datos/schema.sql` | Las tablas de la base |
| `main.py` | El menú por consola |
| `pruebas/` | Pruebas automáticas de la ES3 (`python -m unittest -v pruebas.test_e3`) |
| `herramientas/auditoria_ia.py` | Busca las 5 señales de riesgo del código generado con IA |
| `bitacora_ia.md` | Auditoría y justificación del uso de IA |

## ES3: servicios externos

Menú **Servicios externos**:
- **Clima para planificar un proyecto** (Open-Meteo): temperatura, humedad, viento y estado, con una recomendación de riesgo para trabajos en terreno.
- **Tipo de cambio** (mindicador.cl): dólar y euro en pesos chilenos.
- **Pago internacional:** sueldo proporcional de un empleado convertido a USD o EUR.
- **Datos guardados:** lo último descargado, que es lo que usa el Plan B.

Si la API falla (sin red, timeout, 5xx, 429 o 404), se muestra el último dato guardado indicando su antigüedad (`obtenido_en`).

## Seguridad

- Todas las consultas usan `?`: si se busca `' OR '1'='1` en el menú, no aparece nadie.
- El archivo `.env` no se sube a GitHub.
- Si la base falla, el usuario ve un mensaje simple y el detalle queda en `ecotech.log`.
- Las contraseñas se guardan con bcrypt (hash con salt). Después de 5 fallos la cuenta se bloquea 5 minutos.
- Solo un usuario con sesión activa puede usar el sistema. La sesión expira tras 15 minutos sin uso.
- Las peticiones HTTP siempre llevan timeout, exigen HTTPS y nunca desactivan la verificación TLS.
- Las entradas (ciudad, moneda, usuario, contraseña) se validan con listas blancas y expresiones regulares antes de llegar a la API.
