import sqlite3
from datetime import datetime

from dominio.excepciones import NombreDuplicado
from repositorio.conexion import obtener_conexion


class UsuarioRepositorio:
    """Solo maneja hashes: este repositorio nunca recibe ni guarda contraseñas en texto plano."""

    def crear(self, nombre_usuario, hash_password):
        try:
            with obtener_conexion() as conn:
                conn.execute(
                    """INSERT INTO usuario (nombre_usuario, hash_password, creado_en)
                       VALUES (?, ?, ?)""",
                    (nombre_usuario, hash_password,
                     datetime.now().replace(microsecond=0).isoformat()),
                )
        except sqlite3.IntegrityError:
            raise NombreDuplicado(f"El usuario '{nombre_usuario}' ya existe")

    def obtener(self, nombre_usuario):
        """Devuelve (id, nombre, hash, intentos_fallidos, bloqueado_hasta) o None."""
        with obtener_conexion() as conn:
            fila = conn.execute(
                """SELECT id, nombre_usuario, hash_password, intentos_fallidos, bloqueado_hasta
                   FROM usuario WHERE nombre_usuario = ?""",
                (nombre_usuario,),
            ).fetchone()
        if fila is None:
            return None
        bloqueado = datetime.fromisoformat(fila[4]) if fila[4] else None
        return fila[0], fila[1], fila[2], fila[3], bloqueado

    def hay_usuarios(self):
        with obtener_conexion() as conn:
            return conn.execute("SELECT COUNT(*) FROM usuario").fetchone()[0] > 0

    def registrar_fallo(self, id_usuario, intentos, bloqueado_hasta):
        with obtener_conexion() as conn:
            conn.execute(
                "UPDATE usuario SET intentos_fallidos = ?, bloqueado_hasta = ? WHERE id = ?",
                (intentos, bloqueado_hasta.isoformat() if bloqueado_hasta else None, id_usuario),
            )

    def registrar_exito(self, id_usuario):
        with obtener_conexion() as conn:
            conn.execute(
                "UPDATE usuario SET intentos_fallidos = 0, bloqueado_hasta = NULL WHERE id = ?",
                (id_usuario,),
            )
