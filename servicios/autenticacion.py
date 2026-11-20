"""Autenticación con bcrypt y control de sesión (ES3, criterio 3.1.2).

- La contraseña se transforma con bcrypt (hash lento + salt aleatorio por usuario).
  En la base solo queda algo como $2b$12$..., imposible de revertir.
- El mensaje de error es siempre el mismo ("usuario o contraseña incorrectos") para no
  revelar qué usuarios existen; además se gasta el mismo tiempo exista o no el usuario.
- Tras 5 fallos seguidos la cuenta se bloquea 5 minutos (freno a la fuerza bruta).
- La Sesion expira tras N minutos sin uso; los servicios externos exigen una sesión activa.
"""
import logging
import os
from datetime import datetime, timedelta

import bcrypt

from dominio.excepciones import ErrorDeDominio
from dominio.validaciones import validar_nombre_usuario, validar_password_nueva

log = logging.getLogger(__name__)

MAX_FALLOS = 5
MINUTOS_BLOQUEO = 5
COSTO_BCRYPT = 12   # 2^12 rondas: ~0,2 s por intento, caro para un atacante, invisible para el usuario


class CredencialesInvalidas(ErrorDeDominio):
    pass


class CuentaBloqueada(ErrorDeDominio):
    pass


class SesionNoValida(ErrorDeDominio):
    """No hay sesión iniciada o ya expiró."""


def _hash_falso():
    # Hash de referencia para comparar cuando el usuario no existe (mismo costo de tiempo).
    return bcrypt.hashpw(b"usuario-inexistente", bcrypt.gensalt(COSTO_BCRYPT))


class Sesion:
    def __init__(self, nombre_usuario, minutos_inactividad):
        self._usuario = nombre_usuario
        self._duracion = timedelta(minutes=minutos_inactividad)
        self._ultimo_uso = datetime.now()
        self._cerrada = False

    @property
    def usuario(self):
        return self._usuario

    def esta_activa(self):
        return not self._cerrada and datetime.now() - self._ultimo_uso <= self._duracion

    def exigir(self):
        """Llamar antes de cualquier acción protegida. Renueva el tiempo si está activa."""
        if not self.esta_activa():
            self._cerrada = True
            raise SesionNoValida("Tu sesión expiró o no está iniciada. Vuelve a ingresar.")
        self._ultimo_uso = datetime.now()

    def cerrar(self):
        self._cerrada = True


class ServicioAutenticacion:
    def __init__(self, repo_usuarios):
        self._repo = repo_usuarios
        self._hash_falso = _hash_falso()
        self._minutos_sesion = int(os.getenv("SESION_MINUTOS", "15"))

    def hay_usuarios(self):
        return self._repo.hay_usuarios()

    def registrar(self, nombre_usuario, password):
        nombre = validar_nombre_usuario(nombre_usuario)
        clave = validar_password_nueva(password)
        hash_password = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt(COSTO_BCRYPT))
        self._repo.crear(nombre, hash_password.decode("ascii"))
        log.info("Usuario creado: %s", nombre)          # jamás se registra la contraseña
        return nombre

    def iniciar_sesion(self, nombre_usuario, password):
        if not isinstance(password, str) or password == "" or not str(nombre_usuario).strip():
            raise CredencialesInvalidas("Debes ingresar usuario y contraseña")
        nombre = str(nombre_usuario).strip().lower()
        clave = password.encode("utf-8")[:72]            # bcrypt solo usa 72 bytes
        registro = self._repo.obtener(nombre) if len(nombre) <= 30 else None

        if registro is None:
            bcrypt.checkpw(clave, self._hash_falso)      # mismo tiempo que un usuario real
            log.warning("Login fallido (usuario inexistente)")
            raise CredencialesInvalidas("Usuario o contraseña incorrectos")

        id_usuario, nombre, hash_guardado, fallos, bloqueado_hasta = registro
        ahora = datetime.now()
        if bloqueado_hasta and bloqueado_hasta > ahora:
            minutos = int((bloqueado_hasta - ahora).total_seconds() // 60) + 1
            raise CuentaBloqueada(f"Cuenta bloqueada por intentos fallidos. "
                                  f"Intenta en {minutos} minuto(s).")

        if not bcrypt.checkpw(clave, hash_guardado.encode("ascii")):
            fallos += 1
            bloqueo = ahora + timedelta(minutes=MINUTOS_BLOQUEO) if fallos >= MAX_FALLOS else None
            self._repo.registrar_fallo(id_usuario, 0 if bloqueo else fallos, bloqueo)
            log.warning("Login fallido para %s (%d/%d)", nombre, fallos, MAX_FALLOS)
            raise CredencialesInvalidas("Usuario o contraseña incorrectos")

        self._repo.registrar_exito(id_usuario)
        log.info("Inicio de sesión: %s", nombre)
        return Sesion(nombre, self._minutos_sesion)
