"""Pruebas automáticas de la ES3. No usan internet: simulan las respuestas de las APIs.

Ejecutar desde la carpeta del proyecto:   python -m unittest -v pruebas.test_e3
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

# Base temporal: las pruebas nunca tocan ecotech.db
_BD = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_BD.close()
os.environ["DB_NOMBRE"] = _BD.name
os.environ["DB_MOTOR"] = "sqlite"

import logging  # noqa: E402

import requests  # noqa: E402

logging.disable(logging.CRITICAL)   # el log de las pruebas no ensucia la salida

from api_cliente import (ClienteAPI, ErrorCliente, ErrorRespuestaInvalida,  # noqa: E402
                         ErrorServicioNoDisponible)
from deserializador import DeserializadorClima, DeserializadorIndicador  # noqa: E402
from dominio.excepciones import DatoInvalido  # noqa: E402
from repositorio.conexion import inicializar_bd  # noqa: E402
from repositorio.externos_repo import IndicadorRepositorio, LecturaClimaRepositorio  # noqa: E402
from repositorio.usuario_repo import UsuarioRepositorio  # noqa: E402
from servicios.autenticacion import (CredencialesInvalidas, CuentaBloqueada,  # noqa: E402
                                     ServicioAutenticacion, SesionNoValida)
from servicios.externos import ServicioClima, ServicioIndicadores  # noqa: E402

GEO_OK = {"results": [{"name": "Concepción", "country_code": "CL",
                       "latitude": -36.82, "longitude": -73.05}]}
CLIMA_OK = {"current": {"time": "2026-11-13T12:30", "temperature_2m": 25.0,
                        "relative_humidity_2m": 45, "weather_code": 63, "wind_speed_10m": 7.0}}
DOLAR_OK = {"codigo": "dolar", "nombre": "Dólar observado", "unidad_medida": "Pesos",
            "serie": [{"fecha": "2026-11-13T03:00:00.000Z", "valor": 950.5}]}


class RespuestaFalsa:
    def __init__(self, codigo=200, json_data=None, headers=None, texto_invalido=False):
        self.status_code = codigo
        self._json = json_data
        self.headers = headers or {}
        self._invalido = texto_invalido

    def json(self):
        if self._invalido:
            raise ValueError("no es JSON")
        return self._json


class SesionHTTPFalsa:
    """Imita requests.Session: devuelve (o lanza) lo que se le programe, en orden."""

    def __init__(self, *respuestas):
        self._respuestas = list(respuestas)
        self.llamadas = []
        self.headers = {}

    def get(self, url, params=None, timeout=None, **kwargs):
        self.llamadas.append({"url": url, "params": params, "timeout": timeout, **kwargs})
        siguiente = self._respuestas.pop(0)
        if isinstance(siguiente, Exception):
            raise siguiente
        return siguiente


def cliente(*respuestas, intentos=3):
    http = SesionHTTPFalsa(*respuestas)
    esperas = []
    return ClienteAPI("https://api.ejemplo.cl", sesion_http=http, max_intentos=intentos,
                      dormir=esperas.append), http, esperas


class TestClienteAPI(unittest.TestCase):

    def test_exito_envia_timeout_y_no_desactiva_tls(self):
        api, http, _ = cliente(RespuestaFalsa(200, {"ok": True}))
        self.assertEqual(api.obtener_json("x"), {"ok": True})
        self.assertIsNotNone(http.llamadas[0]["timeout"])
        self.assertNotIn("verify", http.llamadas[0])

    def test_404_no_se_reintenta(self):
        api, http, _ = cliente(RespuestaFalsa(404))
        with self.assertRaises(ErrorCliente) as ctx:
            api.obtener_json("no-existe")
        self.assertEqual(len(http.llamadas), 1)
        self.assertEqual(ctx.exception.codigo_http, 404)

    def test_500_se_reintenta_con_backoff_creciente_y_se_rinde(self):
        api, http, esperas = cliente(RespuestaFalsa(500), RespuestaFalsa(502), RespuestaFalsa(503))
        with self.assertRaises(ErrorServicioNoDisponible):
            api.obtener_json("x")
        self.assertEqual(len(http.llamadas), 3)       # máximo 3 intentos
        self.assertEqual(len(esperas), 2)             # no espera después del último
        self.assertLess(esperas[0], esperas[1])       # espera creciente

    def test_500_y_luego_exito(self):
        api, http, _ = cliente(RespuestaFalsa(503), RespuestaFalsa(200, {"ok": 1}))
        self.assertEqual(api.obtener_json("x"), {"ok": 1})
        self.assertEqual(len(http.llamadas), 2)

    def test_429_respeta_retry_after(self):
        api, _, esperas = cliente(RespuestaFalsa(429, headers={"Retry-After": "2"}),
                                  RespuestaFalsa(200, {"ok": 1}))
        api.obtener_json("x")
        self.assertEqual(esperas, [2.0])

    def test_429_con_espera_excesiva_no_bloquea(self):
        api, http, esperas = cliente(RespuestaFalsa(429, headers={"Retry-After": "120"}))
        with self.assertRaises(ErrorServicioNoDisponible):
            api.obtener_json("x")
        self.assertEqual((len(http.llamadas), esperas), (1, []))

    def test_sin_red_y_timeout_se_reintentan(self):
        api, http, _ = cliente(requests.exceptions.ConnectionError("dns"),
                               requests.exceptions.ReadTimeout("lento"),
                               requests.exceptions.ConnectionError("dns"))
        with self.assertRaises(ErrorServicioNoDisponible) as ctx:
            api.obtener_json("x")
        self.assertEqual(len(http.llamadas), 3)
        self.assertNotIn("dns", ctx.exception.mensaje_usuario)   # sin detalles técnicos

    def test_json_invalido(self):
        api, _, _ = cliente(RespuestaFalsa(200, texto_invalido=True))
        with self.assertRaises(ErrorRespuestaInvalida):
            api.obtener_json("x")

    def test_url_sin_https_falla_controladamente(self):
        api = ClienteAPI("http://inseguro.cl", sesion_http=SesionHTTPFalsa())
        with self.assertRaises(ErrorCliente):
            api.obtener_json("x")

    def test_api_key_no_aparece_en_repr(self):
        api = ClienteAPI("https://api.ejemplo.cl", parametros_fijos={"apikey": "SECRETO"},
                         sesion_http=SesionHTTPFalsa())
        self.assertNotIn("SECRETO", repr(api))


class TestDeserializadores(unittest.TestCase):

    def test_clima_valido(self):
        lectura = DeserializadorClima().convertir(CLIMA_OK)
        self.assertEqual((lectura.temperatura, lectura.humedad, lectura.descripcion),
                         (25.0, 45, "Lluvia"))

    def test_clima_rechaza_campos_faltantes_o_fuera_de_rango(self):
        for malo in [{}, {"current": {}}, {"current": {**CLIMA_OK["current"], "relative_humidity_2m": 150}},
                     {"current": {**CLIMA_OK["current"], "temperature_2m": "25"}},
                     {"current": {**CLIMA_OK["current"], "weather_code": True}}, []]:
            with self.assertRaises(ErrorRespuestaInvalida):
                DeserializadorClima().convertir(malo)

    def test_indicador_valido_y_serie_vacia(self):
        dolar = DeserializadorIndicador().convertir(DOLAR_OK, codigo_esperado="dolar")
        self.assertEqual((dolar.valor, str(dolar.fecha)), (950.5, "2026-11-13"))
        with self.assertRaises(ErrorRespuestaInvalida):
            DeserializadorIndicador().convertir({**DOLAR_OK, "serie": []})
        with self.assertRaises(ErrorRespuestaInvalida):
            DeserializadorIndicador().convertir(DOLAR_OK, codigo_esperado="euro")


class ConBase(unittest.TestCase):
    def setUp(self):
        with sqlite3.connect(_BD.name) as conn:
            conn.execute("DROP TABLE IF EXISTS usuario")
            conn.execute("DROP TABLE IF EXISTS lectura_clima")
            conn.execute("DROP TABLE IF EXISTS indicador_economico")
        inicializar_bd()


class TestAutenticacion(ConBase):

    def setUp(self):
        super().setUp()
        self.auth = ServicioAutenticacion(UsuarioRepositorio())
        self.auth.registrar("bleppe", "Clave2026")

    def test_password_guardada_como_hash_bcrypt(self):
        with sqlite3.connect(_BD.name) as conn:
            hash_guardado = conn.execute("SELECT hash_password FROM usuario").fetchone()[0]
        self.assertTrue(hash_guardado.startswith("$2b$12$"))
        self.assertNotIn("Clave2026", hash_guardado)

    def test_login_correcto_e_incorrecto(self):
        self.assertTrue(self.auth.iniciar_sesion("BLeppe", "Clave2026").esta_activa())
        for usuario, clave in [("bleppe", "otra"), ("noexiste", "Clave2026"), ("bleppe", ""), ("", "x")]:
            with self.assertRaises(CredencialesInvalidas):
                self.auth.iniciar_sesion(usuario, clave)

    def test_bloqueo_tras_5_fallos(self):
        for _ in range(5):
            with self.assertRaises(CredencialesInvalidas):
                self.auth.iniciar_sesion("bleppe", "mala1234")
        with self.assertRaises(CuentaBloqueada):
            self.auth.iniciar_sesion("bleppe", "Clave2026")

    def test_politica_de_password(self):
        for mala in ["corta1", "sololetras", "12345678", " Clave2026", "a1" * 40]:
            with self.assertRaises(DatoInvalido):
                self.auth.registrar("otro", mala)

    def test_sesion_expirada_bloquea_servicios(self):
        sesion = self.auth.iniciar_sesion("bleppe", "Clave2026")
        sesion._ultimo_uso = datetime.now() - timedelta(hours=1)
        servicio = ServicioIndicadores(sesion, None, IndicadorRepositorio())
        with self.assertRaises(SesionNoValida):
            servicio.consultar("dolar")


class TestServiciosYPlanB(ConBase):

    def setUp(self):
        super().setUp()
        auth = ServicioAutenticacion(UsuarioRepositorio())
        auth.registrar("bleppe", "Clave2026")
        self.sesion = auth.iniciar_sesion("bleppe", "Clave2026")
        self.repo_clima = LecturaClimaRepositorio()
        self.repo_ind = IndicadorRepositorio()

    def _clima(self, geo, clima):
        return ServicioClima(self.sesion, cliente(*geo)[0], cliente(*clima)[0], self.repo_clima)

    def test_idempotencia_clima(self):
        for _ in range(2):   # "correr el script dos veces"
            self._clima([RespuestaFalsa(200, GEO_OK)], [RespuestaFalsa(200, CLIMA_OK)]).consultar("Concepcion")
        self.assertEqual(self.repo_clima.contar(), 1)

    def test_idempotencia_indicadores(self):
        for _ in range(2):
            ServicioIndicadores(self.sesion, cliente(RespuestaFalsa(200, DOLAR_OK))[0],
                                self.repo_ind).consultar("dolar")
        self.assertEqual(self.repo_ind.contar(), 1)

    def test_plan_b_sin_red_usa_datos_guardados(self):
        self._clima([RespuestaFalsa(200, GEO_OK)], [RespuestaFalsa(200, CLIMA_OK)]).consultar("Concepción")
        sin_red = [requests.exceptions.ConnectionError()] * 3
        resultado = self._clima(sin_red, []).consultar("concepcion")   # sin tilde: igual lo encuentra
        self.assertTrue(resultado.desde_respaldo)
        self.assertIn("conexión", resultado.motivo)
        self.assertTrue(resultado.antiguedad().startswith("hace"))

    def test_plan_b_url_invalida_404(self):
        ServicioIndicadores(self.sesion, cliente(RespuestaFalsa(200, DOLAR_OK))[0],
                            self.repo_ind).consultar("dolar")
        resultado = ServicioIndicadores(self.sesion, cliente(RespuestaFalsa(404))[0],
                                        self.repo_ind).consultar("dolar")
        self.assertTrue(resultado.desde_respaldo)
        self.assertIn("404", resultado.motivo)

    def test_entradas_maliciosas_no_llegan_a_la_api(self):
        servicio = self._clima([], [])
        for malo in ["'; DROP TABLE usuario;--", "<script>", "", "Ciudad123"]:
            with self.assertRaises(DatoInvalido):
                servicio.consultar(malo)
        with self.assertRaises(DatoInvalido):
            ServicioIndicadores(self.sesion, None, self.repo_ind).consultar("bitcoin")


if __name__ == "__main__":
    unittest.main()
