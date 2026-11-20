"""Cliente HTTP genérico y resiliente para consumir APIs externas (ES3).

Reglas que cumple (ver bitacora_ia.md):
  - Timeout explícito en TODAS las peticiones: (conexión, lectura).
  - 4xx no se reintentan (el error es de la petición, repetirla da lo mismo).
  - 429 respeta la cabecera Retry-After (si la espera es razonable).
  - 5xx, timeouts y errores de red sí se reintentan.
  - Máximo 3 intentos con espera creciente (backoff exponencial + jitter).
  - Nunca se usa verify=False: requests valida el certificado TLS por defecto.
  - Los mensajes al usuario no exponen URLs, claves ni trazas; el detalle va al log.
"""
import logging
import random
import time
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)

TIMEOUT_POR_DEFECTO = (3.05, 10)   # segundos: (establecer conexión, esperar respuesta)
MAX_INTENTOS_PERMITIDOS = 4        # la pauta exige entre 3 y 4 intentos como máximo


# --------------------------------------------------------------------------
# Jerarquía de excepciones: quien llama puede capturar ErrorAPI (todo) o una
# subclase concreta. Cada una trae un mensaje seguro para mostrar al usuario.
# --------------------------------------------------------------------------
class ErrorAPI(Exception):
    """Base de todos los errores al consumir un servicio externo."""

    def __init__(self, mensaje_usuario, codigo_http=None):
        super().__init__(mensaje_usuario)
        self.mensaje_usuario = mensaje_usuario
        self.codigo_http = codigo_http


class ErrorCliente(ErrorAPI):
    """4xx: la petición está mal (URL, parámetros o credenciales). No se reintenta."""


class ErrorServicioNoDisponible(ErrorAPI):
    """Red caída, timeout, 5xx o 429 persistentes tras agotar los reintentos."""


class ErrorRespuestaInvalida(ErrorAPI):
    """La API respondió 2xx pero el contenido no es JSON válido o no trae lo esperado."""


MENSAJES_4XX = {
    400: "El servicio rechazó la consulta por datos inválidos",
    401: "El servicio rechazó las credenciales de acceso",
    403: "El servicio denegó el acceso",
    404: "El servicio no encontró el recurso solicitado",
}


def _url_segura(url):
    """Devuelve la URL sin la query string, para no escribir claves ni parámetros en el log."""
    partes = urlsplit(url)
    return f"{partes.scheme}://{partes.netloc}{partes.path}"


class ClienteAPI:
    """Hace GET a una API JSON con timeout, reintentos acotados y manejo por código HTTP."""

    def __init__(self, url_base, timeout=TIMEOUT_POR_DEFECTO, max_intentos=3,
                 espera_base=1.0, espera_maxima=8.0, parametros_fijos=None,
                 sesion_http=None, dormir=time.sleep):
        if not 1 <= max_intentos <= MAX_INTENTOS_PERMITIDOS:
            raise ValueError(f"max_intentos debe estar entre 1 y {MAX_INTENTOS_PERMITIDOS}")
        # Sin HTTPS los datos (y una eventual API key) viajarían en texto plano. Una URL mala
        # en el .env no bota el programa: cada consulta fallará de forma controlada (Plan B).
        self._url_valida = isinstance(url_base, str) and url_base.lower().startswith("https://")
        self._url_base = url_base.rstrip("/") if isinstance(url_base, str) else ""
        self._timeout = timeout
        self._max_intentos = max_intentos
        self._espera_base = espera_base
        self._espera_maxima = espera_maxima
        self._parametros_fijos = dict(parametros_fijos or {})   # ej: {"apikey": ...} desde .env
        self._http = sesion_http or requests.Session()          # reutiliza la conexión TCP/TLS
        self._http.headers.update({"Accept": "application/json",
                                   "User-Agent": "EcoTech-TI3021/1.0"})
        self._dormir = dormir                                    # inyectable para las pruebas

    def __repr__(self):
        # Nunca mostrar parametros_fijos: pueden contener la API key.
        return f"ClienteAPI({_url_segura(self._url_base)!r})"

    # ------------------------------------------------------------------ API
    def obtener_json(self, ruta, params=None):
        """GET {url_base}/{ruta}. Devuelve el JSON ya decodificado o lanza una ErrorAPI."""
        if not self._url_valida:
            log.error("URL de API inválida o sin HTTPS: %s", _url_segura(self._url_base))
            raise ErrorCliente("La dirección del servicio está mal configurada (se exige HTTPS)")
        url = f"{self._url_base}/{ruta.lstrip('/')}"
        parametros = {**(params or {}), **self._parametros_fijos}
        ultimo_error = None

        for intento in range(1, self._max_intentos + 1):
            try:
                respuesta = self._http.get(url, params=parametros, timeout=self._timeout)
            except requests.exceptions.Timeout:
                ultimo_error = ErrorServicioNoDisponible("El servicio tardó demasiado en responder")
                log.warning("Timeout en %s (intento %d/%d)", _url_segura(url),
                            intento, self._max_intentos)
            except requests.exceptions.SSLError:
                # Certificado inválido: posible ataque de intermediario. NO se reintenta
                # y NUNCA se "arregla" con verify=False.
                log.error("Certificado TLS inválido en %s", _url_segura(url))
                raise ErrorServicioNoDisponible("No se pudo verificar la identidad del servicio")
            except requests.exceptions.ConnectionError:
                ultimo_error = ErrorServicioNoDisponible("No hay conexión con el servicio")
                log.warning("Sin conexión con %s (intento %d/%d)", _url_segura(url),
                            intento, self._max_intentos)
            except requests.exceptions.RequestException as e:
                # URL mal formada, esquema inválido, etc.: error de programación/configuración.
                log.error("Petición inválida a %s: %s", _url_segura(url), type(e).__name__)
                raise ErrorCliente("La consulta al servicio está mal configurada")
            else:
                espera = self._procesar_estado(respuesta, url, intento)
                if espera is None:
                    return self._decodificar(respuesta, url)
                ultimo_error = ErrorServicioNoDisponible(
                    "El servicio no está disponible en este momento", respuesta.status_code)
                if intento < self._max_intentos:
                    self._dormir(espera)
                continue

            if intento < self._max_intentos:
                self._dormir(self._calcular_espera(intento))

        log.error("Se agotaron %d intentos contra %s", self._max_intentos, _url_segura(url))
        raise ultimo_error

    # ------------------------------------------------------------ internos
    def _procesar_estado(self, respuesta, url, intento):
        """None si la respuesta es exitosa; segundos a esperar si hay que reintentar.
        Lanza la excepción adecuada si el error no se debe reintentar."""
        codigo = respuesta.status_code
        if 200 <= codigo < 300:
            return None

        if codigo == 429:
            espera = self._leer_retry_after(respuesta.headers.get("Retry-After"), intento)
            if espera > self._espera_maxima:
                # Bloquear al usuario un minuto no es aceptable: se pasa al Plan B.
                log.warning("429 en %s con Retry-After=%.0fs (> %.0fs), no se espera",
                            _url_segura(url), espera, self._espera_maxima)
                raise ErrorServicioNoDisponible(
                    "El servicio limitó las consultas; intenta más tarde", codigo)
            log.warning("429 en %s, se respeta Retry-After=%.1fs", _url_segura(url), espera)
            return espera

        if 400 <= codigo < 500:
            log.error("HTTP %d en %s (no se reintenta)", codigo, _url_segura(url))
            mensaje = MENSAJES_4XX.get(codigo, "El servicio rechazó la consulta")
            raise ErrorCliente(f"{mensaje} (HTTP {codigo})", codigo)

        if codigo >= 500:
            log.warning("HTTP %d en %s (intento %d/%d)", codigo, _url_segura(url),
                        intento, self._max_intentos)
            return self._calcular_espera(intento)

        # 1xx/3xx que requests no resolvió: no es lo que esperamos de una API JSON.
        log.error("HTTP %d inesperado en %s", codigo, _url_segura(url))
        raise ErrorRespuestaInvalida("El servicio respondió de forma inesperada", codigo)

    def _calcular_espera(self, intento):
        """Backoff exponencial (1s, 2s, 4s...) + jitter aleatorio, con tope."""
        espera = self._espera_base * (2 ** (intento - 1)) + random.uniform(0, 0.5)
        return min(espera, self._espera_maxima)

    def _leer_retry_after(self, valor, intento):
        """Retry-After puede venir en segundos ('5') o como fecha HTTP."""
        if valor:
            valor = valor.strip()
            if valor.isdigit():
                return float(valor)
            try:
                fecha = parsedate_to_datetime(valor)
                return max(0.0, (fecha - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                log.warning("Retry-After con formato no reconocido; se usa backoff normal")
        return self._calcular_espera(intento)

    def _decodificar(self, respuesta, url):
        try:
            return respuesta.json()
        except ValueError:
            log.error("Respuesta no JSON desde %s", _url_segura(url))
            raise ErrorRespuestaInvalida("El servicio entregó datos con un formato inválido")
