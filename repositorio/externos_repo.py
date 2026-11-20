"""Persistencia de los datos externos (ES3).

- Todas las consultas son parametrizadas (?): cero concatenación ni f-strings en SQL.
- Las inserciones son idempotentes: INSERT ... ON CONFLICT DO UPDATE (upsert) sobre una
  clave UNIQUE. Ejecutar la misma consulta dos veces actualiza obtenido_en, no duplica.
"""
from datetime import date, datetime

from dominio.externos import IndicadorEconomico, LecturaClima, Ubicacion
from dominio.validaciones import normalizar_texto
from repositorio.conexion import obtener_conexion


class LecturaClimaRepositorio:

    def guardar(self, lectura):
        with obtener_conexion() as conn:
            conn.execute(
                """INSERT INTO lectura_clima
                       (ciudad, ciudad_normalizada, pais, latitud, longitud, temperatura,
                        humedad, viento, codigo_clima, descripcion, medido_en, obtenido_en)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT (ciudad_normalizada, pais, medido_en) DO UPDATE SET
                       temperatura = excluded.temperatura,
                       humedad     = excluded.humedad,
                       viento      = excluded.viento,
                       codigo_clima = excluded.codigo_clima,
                       descripcion = excluded.descripcion,
                       obtenido_en = excluded.obtenido_en""",
                (lectura.ubicacion.nombre, normalizar_texto(lectura.ubicacion.nombre),
                 lectura.ubicacion.pais, lectura.ubicacion.latitud, lectura.ubicacion.longitud,
                 lectura.temperatura, lectura.humedad, lectura.viento, lectura.codigo_clima,
                 lectura.descripcion, lectura.medido_en.isoformat(),
                 lectura.obtenido_en.isoformat()),
            )

    def ultima_por_ciudad(self, ciudad):
        """Plan B: la lectura más reciente guardada para esa ciudad (ignora tildes y mayúsculas)."""
        with obtener_conexion() as conn:
            fila = conn.execute(
                """SELECT ciudad, pais, latitud, longitud, temperatura, humedad, viento,
                          codigo_clima, medido_en, obtenido_en
                   FROM lectura_clima
                   WHERE ciudad_normalizada = ?
                   ORDER BY obtenido_en DESC LIMIT 1""",
                (normalizar_texto(ciudad),),
            ).fetchone()
        return None if fila is None else self._fila_a_lectura(fila)

    def listar_recientes(self, limite=10):
        with obtener_conexion() as conn:
            filas = conn.execute(
                """SELECT ciudad, pais, latitud, longitud, temperatura, humedad, viento,
                          codigo_clima, medido_en, obtenido_en
                   FROM lectura_clima ORDER BY obtenido_en DESC LIMIT ?""",
                (limite,),
            ).fetchall()
        return [self._fila_a_lectura(fila) for fila in filas]

    def contar(self):
        with obtener_conexion() as conn:
            return conn.execute("SELECT COUNT(*) FROM lectura_clima").fetchone()[0]

    def _fila_a_lectura(self, fila):
        return LecturaClima(
            ubicacion=Ubicacion(nombre=fila[0], pais=fila[1], latitud=fila[2], longitud=fila[3]),
            temperatura=fila[4], humedad=fila[5], viento=fila[6], codigo_clima=fila[7],
            medido_en=datetime.fromisoformat(fila[8]),
            obtenido_en=datetime.fromisoformat(fila[9]),
        )


class IndicadorRepositorio:

    def guardar(self, indicador):
        with obtener_conexion() as conn:
            conn.execute(
                """INSERT INTO indicador_economico (codigo, nombre, unidad, valor, fecha, obtenido_en)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT (codigo, fecha) DO UPDATE SET
                       valor = excluded.valor,
                       obtenido_en = excluded.obtenido_en""",
                (indicador.codigo, indicador.nombre, indicador.unidad, indicador.valor,
                 indicador.fecha.isoformat(), indicador.obtenido_en.isoformat()),
            )

    def ultimo(self, codigo):
        """Plan B: el valor más reciente guardado para esa moneda."""
        with obtener_conexion() as conn:
            fila = conn.execute(
                """SELECT codigo, nombre, unidad, valor, fecha, obtenido_en
                   FROM indicador_economico
                   WHERE codigo = ? ORDER BY fecha DESC, obtenido_en DESC LIMIT 1""",
                (codigo,),
            ).fetchone()
        return None if fila is None else self._fila_a_indicador(fila)

    def listar_recientes(self, limite=10):
        with obtener_conexion() as conn:
            filas = conn.execute(
                """SELECT codigo, nombre, unidad, valor, fecha, obtenido_en
                   FROM indicador_economico ORDER BY obtenido_en DESC LIMIT ?""",
                (limite,),
            ).fetchall()
        return [self._fila_a_indicador(fila) for fila in filas]

    def contar(self):
        with obtener_conexion() as conn:
            return conn.execute("SELECT COUNT(*) FROM indicador_economico").fetchone()[0]

    def _fila_a_indicador(self, fila):
        return IndicadorEconomico(
            codigo=fila[0], nombre=fila[1], unidad=fila[2], valor=fila[3],
            fecha=date.fromisoformat(fila[4]), obtenido_en=datetime.fromisoformat(fila[5]),
        )
