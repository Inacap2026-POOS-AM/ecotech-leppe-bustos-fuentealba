"""Deserializadores propios: validan el JSON de las APIs y lo convierten en objetos de dominio.

Nunca se confía en la forma del JSON externo: cada campo se busca, se valida su tipo
y su rango. Si algo no cuadra se lanza ErrorRespuestaInvalida (nunca KeyError/TypeError
sueltos que botarían el programa). Solo se extraen los campos que el sistema usa.
"""
import math
from abc import ABC, abstractmethod
from datetime import datetime

from api_cliente import ErrorRespuestaInvalida
from dominio.externos import DESCRIPCION_WMO, IndicadorEconomico, LecturaClima, Ubicacion


class CiudadNoEncontrada(Exception):
    """La API respondió bien, pero no conoce la ciudad buscada."""


class DeserializadorJSON(ABC):
    """Base con las validaciones comunes. Cada subclase implementa convertir()."""

    @abstractmethod
    def convertir(self, datos, **contexto):
        pass

    # --- helpers -----------------------------------------------------------
    def _objeto(self, datos, ruta):
        if not isinstance(datos, dict):
            self._invalido(f"se esperaba un objeto en '{ruta}'")
        return datos

    def _campo(self, objeto, clave, ruta):
        if clave not in objeto or objeto[clave] is None:
            self._invalido(f"falta el campo '{ruta}.{clave}'")
        return objeto[clave]

    def _texto(self, objeto, clave, ruta, max_largo=100):
        valor = self._campo(objeto, clave, ruta)
        if not isinstance(valor, str) or not valor.strip() or len(valor) > max_largo:
            self._invalido(f"'{ruta}.{clave}' no es un texto válido")
        return valor.strip()

    def _numero(self, objeto, clave, ruta, minimo, maximo):
        valor = self._campo(objeto, clave, ruta)
        # bool es subclase de int en Python: se excluye a propósito.
        if isinstance(valor, bool) or not isinstance(valor, (int, float)) or not math.isfinite(valor):
            self._invalido(f"'{ruta}.{clave}' no es numérico")
        if not minimo <= valor <= maximo:
            self._invalido(f"'{ruta}.{clave}'={valor} fuera de rango [{minimo}, {maximo}]")
        return valor

    def _fecha_iso(self, objeto, clave, ruta):
        texto = self._texto(objeto, clave, ruta, max_largo=40)
        try:
            return datetime.fromisoformat(texto.replace("Z", "+00:00"))
        except ValueError:
            self._invalido(f"'{ruta}.{clave}' no es una fecha ISO 8601")

    def _invalido(self, detalle):
        # El detalle técnico queda en la excepción (para el log); el usuario ve un mensaje simple.
        error = ErrorRespuestaInvalida("El servicio entregó datos incompletos o con formato inválido")
        error.detalle = f"{type(self).__name__}: {detalle}"
        raise error


class DeserializadorUbicacion(DeserializadorJSON):
    """Geocoding de Open-Meteo: {"results": [{"name", "country_code", "latitude", "longitude"}]}"""

    def convertir(self, datos, ciudad_buscada=""):
        raiz = self._objeto(datos, "$")
        resultados = raiz.get("results")
        if not resultados:                      # la API omite "results" si no encuentra nada
            raise CiudadNoEncontrada(f"No se encontró la ciudad '{ciudad_buscada}'")
        if not isinstance(resultados, list):
            self._invalido("'results' no es una lista")
        primero = self._objeto(resultados[0], "results[0]")
        return Ubicacion(
            nombre=self._texto(primero, "name", "results[0]", max_largo=100),
            pais=self._texto(primero, "country_code", "results[0]", max_largo=2).upper(),
            latitud=float(self._numero(primero, "latitude", "results[0]", -90, 90)),
            longitud=float(self._numero(primero, "longitude", "results[0]", -180, 180)),
        )


class DeserializadorClima(DeserializadorJSON):
    """Forecast de Open-Meteo con current=temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m"""

    def convertir(self, datos, ubicacion=None, obtenido_en=None):
        raiz = self._objeto(datos, "$")
        actual = self._objeto(self._campo(raiz, "current", "$"), "current")
        codigo = int(self._numero(actual, "weather_code", "current", 0, 99))
        if codigo not in DESCRIPCION_WMO:
            self._invalido(f"código WMO desconocido: {codigo}")
        return LecturaClima(
            ubicacion=ubicacion,
            temperatura=float(self._numero(actual, "temperature_2m", "current", -90, 60)),
            humedad=int(self._numero(actual, "relative_humidity_2m", "current", 0, 100)),
            viento=float(self._numero(actual, "wind_speed_10m", "current", 0, 500)),
            codigo_clima=codigo,
            medido_en=self._fecha_iso(actual, "time", "current"),
            obtenido_en=obtenido_en or datetime.now().replace(microsecond=0),
        )


class DeserializadorIndicador(DeserializadorJSON):
    """mindicador.cl /api/{codigo}: {"codigo","nombre","unidad_medida","serie":[{"fecha","valor"}]}"""

    def convertir(self, datos, codigo_esperado=None, obtenido_en=None):
        raiz = self._objeto(datos, "$")
        codigo = self._texto(raiz, "codigo", "$", max_largo=20)
        if codigo_esperado and codigo != codigo_esperado:
            self._invalido(f"se pidió '{codigo_esperado}' y llegó '{codigo}'")
        serie = self._campo(raiz, "serie", "$")
        if not isinstance(serie, list) or not serie:
            self._invalido("'serie' vacía: no hay valores publicados")
        ultimo = self._objeto(serie[0], "serie[0]")    # la API ordena del más reciente al más antiguo
        return IndicadorEconomico(
            codigo=codigo,
            nombre=self._texto(raiz, "nombre", "$"),
            unidad=self._texto(raiz, "unidad_medida", "$", max_largo=30),
            valor=float(self._numero(ultimo, "valor", "serie[0]", 0.0001, 10_000_000)),
            fecha=self._fecha_iso(ultimo, "fecha", "serie[0]").date(),
            obtenido_en=obtenido_en or datetime.now().replace(microsecond=0),
        )
