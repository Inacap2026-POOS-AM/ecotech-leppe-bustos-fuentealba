"""Servicios que integran las APIs externas al sistema (ES3).

Flujo de cada consulta:
  1. Exigir sesión activa (solo usuarios autenticados consumen APIs).
  2. Validar la entrada del usuario (ciudad / moneda).
  3. Llamar a la API (ClienteAPI: timeout + reintentos) y deserializar.
  4. Guardar en la base (upsert idempotente).
  5. Si la API falla -> Plan B: devolver el último dato guardado indicando su antigüedad.
"""
import logging
import os
from dataclasses import dataclass
from datetime import datetime

from api_cliente import ClienteAPI, ErrorAPI
from deserializador import (CiudadNoEncontrada, DeserializadorClima, DeserializadorIndicador,
                            DeserializadorUbicacion)
from dominio.excepciones import ErrorDeDominio
from dominio.validaciones import MONEDAS_PERMITIDAS, validar_ciudad, validar_moneda

log = logging.getLogger(__name__)


class SinDatosDisponibles(ErrorDeDominio):
    """La API falló y tampoco hay datos guardados para mostrar."""


@dataclass
class Resultado:
    dato: object                 # LecturaClima o IndicadorEconomico
    desde_respaldo: bool         # True = viene de la base local (Plan B)
    motivo: str = ""             # por qué se usó el respaldo (mensaje seguro)

    def antiguedad(self):
        """'hace 2 h 5 min' a partir de obtenido_en."""
        segundos = int((datetime.now() - self.dato.obtenido_en).total_seconds())
        if segundos < 60:
            return "hace menos de 1 minuto"
        minutos, _ = divmod(segundos, 60)
        horas, minutos = divmod(minutos, 60)
        dias, horas = divmod(horas, 24)
        partes = [f"{dias} d" if dias else "", f"{horas} h" if horas else "",
                  f"{minutos} min" if minutos else ""]
        return "hace " + " ".join(p for p in partes if p)


def _registrar_falla(servicio, error):
    detalle = getattr(error, "detalle", "")
    log.warning("Plan B activado en %s: %s %s (HTTP %s)", servicio, type(error).__name__,
                detalle, error.codigo_http)


class ServicioClima:
    def __init__(self, sesion, cliente_geocoding, cliente_clima, repo_clima):
        self._sesion = sesion
        self._geo = cliente_geocoding
        self._clima = cliente_clima
        self._repo = repo_clima

    def consultar(self, ciudad_ingresada):
        self._sesion.exigir()
        ciudad = validar_ciudad(ciudad_ingresada)
        try:
            datos_geo = self._geo.obtener_json(
                "search", {"name": ciudad, "count": 1, "language": "es", "format": "json"})
            ubicacion = DeserializadorUbicacion().convertir(datos_geo, ciudad_buscada=ciudad)
            datos = self._clima.obtener_json("forecast", {
                "latitude": ubicacion.latitud,
                "longitude": ubicacion.longitud,
                "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
                "timezone": "auto",
            })
            lectura = DeserializadorClima().convertir(datos, ubicacion=ubicacion)
        except CiudadNoEncontrada as e:
            raise SinDatosDisponibles(str(e))
        except ErrorAPI as e:
            _registrar_falla("clima", e)
            respaldo = self._repo.ultima_por_ciudad(ciudad)
            if respaldo is None:
                raise SinDatosDisponibles(f"{e.mensaje_usuario} y no hay datos guardados "
                                          f"de '{ciudad}'. Intenta más tarde.")
            return Resultado(respaldo, desde_respaldo=True, motivo=e.mensaje_usuario)

        self._repo.guardar(lectura)
        return Resultado(lectura, desde_respaldo=False)


class ServicioIndicadores:
    def __init__(self, sesion, cliente_indicadores, repo_indicadores):
        self._sesion = sesion
        self._api = cliente_indicadores
        self._repo = repo_indicadores

    def consultar(self, moneda_ingresada):
        self._sesion.exigir()
        codigo = validar_moneda(moneda_ingresada)          # lista blanca: dolar / euro
        try:
            datos = self._api.obtener_json(codigo)
            indicador = DeserializadorIndicador().convertir(datos, codigo_esperado=codigo)
        except ErrorAPI as e:
            _registrar_falla("indicadores", e)
            respaldo = self._repo.ultimo(codigo)
            if respaldo is None:
                raise SinDatosDisponibles(f"{e.mensaje_usuario} y no hay un valor guardado "
                                          f"del {codigo}. Intenta más tarde.")
            return Resultado(respaldo, desde_respaldo=True, motivo=e.mensaje_usuario)

        self._repo.guardar(indicador)
        return Resultado(indicador, desde_respaldo=False)

    @staticmethod
    def monedas():
        return dict(MONEDAS_PERMITIDAS)


def _leer_float(nombre, por_defecto):
    try:
        return float(os.getenv(nombre, por_defecto))
    except ValueError:
        log.error("Valor inválido para %s en .env; se usa %s", nombre, por_defecto)
        return float(por_defecto)


def crear_clientes_desde_entorno():
    """Lee las URLs y parámetros desde .env (nada sensible queda escrito en el código)."""
    timeout = (_leer_float("API_TIMEOUT_CONEXION", "3.05"), _leer_float("API_TIMEOUT_LECTURA", "10"))
    intentos = min(max(int(_leer_float("API_MAX_INTENTOS", "3")), 1), 4)   # la pauta: 3 a 4
    clave_clima = os.getenv("OPEN_METEO_API_KEY", "").strip()
    fijos_clima = {"apikey": clave_clima} if clave_clima else None
    return {
        "geocoding": ClienteAPI(os.getenv("API_GEOCODING_URL",
                                          "https://geocoding-api.open-meteo.com/v1"),
                                timeout=timeout, max_intentos=intentos),
        "clima": ClienteAPI(os.getenv("API_CLIMA_URL", "https://api.open-meteo.com/v1"),
                            timeout=timeout, max_intentos=intentos,
                            parametros_fijos=fijos_clima),
        "indicadores": ClienteAPI(os.getenv("API_INDICADORES_URL", "https://mindicador.cl/api"),
                                  timeout=timeout, max_intentos=intentos),
    }
