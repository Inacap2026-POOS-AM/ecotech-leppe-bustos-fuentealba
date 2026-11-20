import getpass
import logging
from abc import ABC, abstractmethod
from datetime import date, datetime

from dominio.departamento import Departamento
from dominio.empleado import Empleado
from dominio.excepciones import ErrorDeDominio
from dominio.proyecto import Proyecto
from dominio.registro_tiempo import RegistroTiempo
from dominio.validaciones import (validar_ciudad, validar_dias, validar_horas, validar_moneda,
                                  validar_rut, validar_sueldo)
from repositorio.conexion import ErrorDeConexion, inicializar_bd, probar_conexion
from repositorio.externos_repo import IndicadorRepositorio, LecturaClimaRepositorio
from repositorio.usuario_repo import UsuarioRepositorio
from repositorio.departamento_repo import DepartamentoRepositorio
from repositorio.empleado_repo import EmpleadoRepositorio
from repositorio.proyecto_repo import ProyectoRepositorio
from repositorio.registro_tiempo_repo import RegistroTiempoRepositorio
from servicios.autenticacion import (CredencialesInvalidas, CuentaBloqueada, ServicioAutenticacion,
                                     SesionNoValida)
from servicios.externos import ServicioClima, ServicioIndicadores, crear_clientes_desde_entorno

log = logging.getLogger(__name__)


def pedir(mensaje, convertir=str, actual=None, opcional=False):
    if actual is not None:
        if isinstance(actual, date):
            mensaje = f"{mensaje} [{actual.strftime('%d-%m-%Y')}]"
        else:
            mensaje = f"{mensaje} [{actual}]"
    while True:
        texto = input(f"{mensaje}: ").strip()
        if texto == "":
            if actual is not None:
                return actual
            if opcional:
                return None
            print("  ✘ Este dato es obligatorio.")
            continue
        try:
            return convertir(texto)
        except ValueError as e:
            print(f"  ✘ {e}")


def confirmar(mensaje):
    while True:
        respuesta = input(f"{mensaje} (s/n): ").strip().lower()
        if respuesta == "s":
            return True
        if respuesta == "n":
            return False
        print("  ✘ Responde s o n.")


def mostrar_lista(elementos):
    if len(elementos) == 0:
        print("  (sin resultados)")
    for elemento in elementos:
        print(f"  {elemento}")


def a_entero(texto):
    try:
        return int(texto.replace(".", ""))
    except ValueError:
        raise ValueError(f"'{texto}' no es un número entero")


def a_decimal(texto):
    try:
        return float(texto.replace(",", "."))
    except ValueError:
        raise ValueError(f"'{texto}' no es un número")


def a_fecha(texto):
    try:
        return datetime.strptime(texto, "%d-%m-%Y").date()
    except ValueError:
        raise ValueError(f"'{texto}' no es una fecha válida, usa el formato DD-MM-AAAA")


def a_sueldo(texto):
    return validar_sueldo(a_entero(texto))


def a_horas(texto):
    return validar_horas(a_decimal(texto))


def a_dias(texto):
    return validar_dias(a_entero(texto))


class Menu(ABC):
    titulo = "Menú"
    salida = "Volver"
    _sesion = None          # MenuPrincipal la asigna después del login

    @abstractmethod
    def opciones(self):
        pass

    def mostrar(self):
        opciones = self.opciones()
        while True:
            print(f"\n=== {self.titulo} ===")
            for numero, (texto, _) in enumerate(opciones, start=1):
                print(f"{numero}. {texto}")
            print(f"0. {self.salida}")
            eleccion = input("Opción: ").strip()
            if eleccion == "0":
                return
            if eleccion.isdigit() and 1 <= int(eleccion) <= len(opciones):
                self._ejecutar(opciones[int(eleccion) - 1][1])
            else:
                print(f"  ✘ Opción no válida: escribe un número del 0 al {len(opciones)}.")

    def _ejecutar(self, accion):
        try:
            if self._sesion is None:
                raise SesionNoValida("Debes iniciar sesión.")
            self._sesion.exigir()           # toda acción del sistema requiere sesión activa
            accion()
        except SesionNoValida:
            raise                           # sube hasta main(), que vuelve a pedir login
        except ErrorDeDominio as e:
            print(f"  ✘ {e}")
        except ErrorDeConexion as e:
            print(f"  ✘ {e}")
        except Exception:
            # Última barrera: el programa no se cae y el usuario no ve la traza técnica.
            log.exception("Error inesperado en el menú '%s'", self.titulo)
            print("  ✘ Ocurrió un error inesperado. El detalle quedó registrado en ecotech.log.")


class MenuCatalogo(Menu):
    def __init__(self, titulo, clase, repositorio):
        self.titulo = titulo
        self._clase = clase
        self._repo = repositorio

    def opciones(self):
        return [("Registrar", self.registrar),
                ("Listar / buscar por nombre", self.listar),
                ("Cambiar nombre", self.actualizar),
                ("Eliminar", self.eliminar)]

    def registrar(self):
        nuevo = self._repo.guardar(self._clase(pedir("Nombre")))
        print(f"  ✔ Guardado: {nuevo}")

    def listar(self):
        filtro = pedir("Buscar (Enter para ver todos)", opcional=True)
        mostrar_lista(self._repo.listar(nombre_contiene=filtro))

    def actualizar(self):
        entidad = self._repo.obtener(pedir("Id", a_entero))
        if entidad is None:
            print("  ✘ No existe ese id.")
            return
        entidad.nombre = pedir("Nombre", actual=entidad.nombre)
        self._repo.actualizar(entidad)
        print(f"  ✔ Actualizado: {entidad}")

    def eliminar(self):
        id_ = pedir("Id", a_entero)
        if not confirmar(f"¿Eliminar el id {id_}?"):
            return
        print("  ✔ Eliminado." if self._repo.eliminar(id_) else "  ✘ No existe ese id.")


class MenuEmpleados(Menu):
    titulo = "Empleados"

    def __init__(self, repo_empleados, repo_departamentos):
        self._repo = repo_empleados
        self._repo_dep = repo_departamentos

    def opciones(self):
        return [("Registrar", self.registrar),
                ("Listar / buscar por nombre", self.listar),
                ("Actualizar", self.actualizar),
                ("Eliminar", self.eliminar),
                ("Calcular sueldo proporcional", self.calcular_sueldo)]

    def _mostrar_departamentos(self):
        print("Departamentos disponibles:")
        mostrar_lista(self._repo_dep.listar())

    def registrar(self):
        rut = pedir("RUT (12345678-5)", validar_rut)
        nombre = pedir("Nombre")
        fecha_ingreso = pedir("Fecha de ingreso (DD-MM-AAAA)", a_fecha)
        sueldo_base = pedir("Sueldo base", a_sueldo)
        self._mostrar_departamentos()
        departamento_id = pedir("Id del departamento (Enter si no tiene)", a_entero, opcional=True)
        empleado = Empleado(rut, nombre, fecha_ingreso, sueldo_base, departamento_id)
        self._repo.guardar(empleado)
        print(f"  ✔ Guardado: {empleado}")

    def listar(self):
        filtro = pedir("Buscar (Enter para ver todos)", opcional=True)
        mostrar_lista(self._repo.listar(nombre_contiene=filtro))

    def actualizar(self):
        empleado = self._repo.obtener(pedir("RUT", validar_rut))
        if empleado is None:
            print("  ✘ No hay un empleado con ese RUT.")
            return
        print("Enter conserva el valor entre corchetes.")
        empleado.nombre = pedir("Nombre", actual=empleado.nombre)
        empleado.fecha_ingreso = pedir("Fecha de ingreso", a_fecha, actual=empleado.fecha_ingreso)
        empleado.sueldo_base = pedir("Sueldo base", a_sueldo, actual=empleado.sueldo_base)
        self._mostrar_departamentos()
        empleado.departamento_id = pedir("Id del departamento", a_entero,
                                         actual=empleado.departamento_id, opcional=True)
        self._repo.actualizar(empleado)
        print(f"  ✔ Actualizado: {empleado}")

    def eliminar(self):
        rut = pedir("RUT", validar_rut)
        if not confirmar(f"¿Eliminar a {rut}? También se borran sus registros de horas"):
            return
        print("  ✔ Eliminado." if self._repo.eliminar(rut) else "  ✘ No hay un empleado con ese RUT.")

    def calcular_sueldo(self):
        empleado = self._repo.obtener(pedir("RUT", validar_rut))
        if empleado is None:
            print("  ✘ No hay un empleado con ese RUT.")
            return
        dias = pedir("Días trabajados en el mes (0 a 30)", a_dias)
        print(f"  Antigüedad: {empleado.antiguedad()} años")
        print(f"  Sueldo proporcional: ${empleado.calcular_sueldo_proporcional(dias)}")


class MenuRegistros(Menu):
    titulo = "Registro de horas"

    def __init__(self, repo_registros, repo_proyectos):
        self._repo = repo_registros
        self._repo_pro = repo_proyectos

    def opciones(self):
        return [("Registrar horas", self.registrar),
                ("Listar (por empleado y/o fechas)", self.listar),
                ("Actualizar", self.actualizar),
                ("Eliminar", self.eliminar)]

    def _mostrar_proyectos(self):
        print("Proyectos disponibles:")
        mostrar_lista(self._repo_pro.listar())

    def registrar(self):
        rut = pedir("RUT del empleado", validar_rut)
        self._mostrar_proyectos()
        proyecto_id = pedir("Id del proyecto", a_entero)
        horas = pedir("Horas", a_horas)
        fecha = pedir("Fecha (DD-MM-AAAA)", a_fecha)
        nuevo = self._repo.guardar(RegistroTiempo(rut, proyecto_id, horas, fecha))
        print(f"  ✔ Guardado: {nuevo}")

    def listar(self):
        print("Enter deja el filtro vacío.")
        rut = pedir("RUT del empleado", validar_rut, opcional=True)
        desde = pedir("Desde (DD-MM-AAAA)", a_fecha, opcional=True)
        hasta = pedir("Hasta (DD-MM-AAAA)", a_fecha, opcional=True)
        mostrar_lista(self._repo.listar(empleado_rut=rut, desde=desde, hasta=hasta))

    def actualizar(self):
        registro = self._repo.obtener(pedir("Id del registro", a_entero))
        if registro is None:
            print("  ✘ No existe ese registro.")
            return
        print("Enter conserva el valor entre corchetes.")
        self._mostrar_proyectos()
        registro.proyecto_id = pedir("Id del proyecto", a_entero, actual=registro.proyecto_id)
        registro.horas = pedir("Horas", a_horas, actual=registro.horas)
        registro.fecha = pedir("Fecha", a_fecha, actual=registro.fecha)
        self._repo.actualizar(registro)
        print(f"  ✔ Actualizado: {registro}")

    def eliminar(self):
        id_ = pedir("Id del registro", a_entero)
        if not confirmar(f"¿Eliminar el registro {id_}?"):
            return
        print("  ✔ Eliminado." if self._repo.eliminar(id_) else "  ✘ No existe ese registro.")


def mostrar_resultado(resultado):
    """Muestra un dato externo; si viene del Plan B lo dice claramente, con su antigüedad."""
    if resultado.desde_respaldo:
        obtenido = resultado.dato.obtenido_en.strftime("%d-%m-%Y %H:%M")
        print(f"  ⚠ {resultado.motivo}.")
        print(f"  ⚠ Mostrando el último dato guardado (obtenido_en {obtenido}, "
              f"{resultado.antiguedad()}).")
    print(f"  {resultado.dato}")


class MenuServiciosExternos(Menu):
    titulo = "Servicios externos (clima e indicadores)"

    def __init__(self, servicio_clima, servicio_indicadores, repo_empleados, repo_proyectos,
                 repo_clima, repo_indicadores):
        self._clima = servicio_clima
        self._indicadores = servicio_indicadores
        self._repo_emp = repo_empleados
        self._repo_pro = repo_proyectos
        self._repo_clima = repo_clima
        self._repo_ind = repo_indicadores

    def opciones(self):
        return [("Clima para planificar un proyecto", self.clima_proyecto),
                ("Tipo de cambio (dólar / euro)", self.tipo_cambio),
                ("Calcular pago internacional de un empleado", self.pago_internacional),
                ("Ver datos guardados (respaldo local)", self.datos_guardados)]

    def clima_proyecto(self):
        print("Proyectos:")
        mostrar_lista(self._repo_pro.listar())
        id_proyecto = pedir("Id del proyecto (Enter para omitir)", a_entero, opcional=True)
        proyecto = self._repo_pro.obtener(id_proyecto) if id_proyecto else None
        if id_proyecto and proyecto is None:
            print("  ✘ No existe ese proyecto; se consulta solo el clima.")
        ciudad = pedir("Ciudad donde se ejecuta", validar_ciudad)
        print("  Consultando el servicio de clima...")
        resultado = self._clima.consultar(ciudad)
        mostrar_resultado(resultado)
        nivel, recomendacion = resultado.dato.evaluar_riesgo()
        destino = f"Proyecto {proyecto.nombre}" if proyecto else "Recomendación"
        print(f"  {destino} · riesgo {nivel}: {recomendacion}.")

    def tipo_cambio(self):
        moneda = pedir(f"Moneda ({' / '.join(ServicioIndicadores.monedas())})", validar_moneda)
        print("  Consultando indicadores económicos...")
        mostrar_resultado(self._indicadores.consultar(moneda))

    def pago_internacional(self):
        empleado = self._repo_emp.obtener(pedir("RUT del empleado", validar_rut))
        if empleado is None:
            print("  ✘ No hay un empleado con ese RUT.")
            return
        dias = pedir("Días trabajados en el mes (0 a 30)", a_dias)
        moneda = pedir(f"Moneda de pago ({' / '.join(ServicioIndicadores.monedas())})",
                       validar_moneda)
        print("  Consultando tipo de cambio...")
        resultado = self._indicadores.consultar(moneda)
        mostrar_resultado(resultado)
        sueldo_clp = empleado.calcular_sueldo_proporcional(dias)
        monto = resultado.dato.convertir_desde_pesos(sueldo_clp)
        sigla = ServicioIndicadores.monedas()[resultado.dato.codigo]
        clp = f"{sueldo_clp:,}".replace(",", ".")           # formato chileno: 1.200.000
        print(f"  {empleado.nombre}: ${clp} CLP ({dias} días) = {monto:,.2f} {sigla}")
        if resultado.desde_respaldo:
            print("  ⚠ Monto referencial: el tipo de cambio no está actualizado.")

    def datos_guardados(self):
        print(f"Lecturas de clima guardadas: {self._repo_clima.contar()}")
        mostrar_lista(self._repo_clima.listar_recientes(5))
        print(f"Valores de moneda guardados: {self._repo_ind.contar()}")
        mostrar_lista(self._repo_ind.listar_recientes(5))


class MenuPrincipal(Menu):
    titulo = "EcoTech Solutions · Gestión interna"
    salida = "Salir"

    def __init__(self, sesion, autenticacion, clientes_api):
        self._sesion = sesion
        self._auth = autenticacion
        repo_dep = DepartamentoRepositorio()
        repo_pro = ProyectoRepositorio()
        repo_emp = EmpleadoRepositorio()
        repo_clima = LecturaClimaRepositorio()
        repo_ind = IndicadorRepositorio()
        self._submenus = [
            MenuEmpleados(repo_emp, repo_dep),
            MenuCatalogo("Departamentos", Departamento, repo_dep),
            MenuCatalogo("Proyectos", Proyecto, repo_pro),
            MenuRegistros(RegistroTiempoRepositorio(), repo_pro),
            MenuServiciosExternos(
                ServicioClima(sesion, clientes_api["geocoding"], clientes_api["clima"], repo_clima),
                ServicioIndicadores(sesion, clientes_api["indicadores"], repo_ind),
                repo_emp, repo_pro, repo_clima, repo_ind),
        ]
        for submenu in self._submenus:
            submenu._sesion = sesion

    def opciones(self):
        opciones = [(submenu.titulo, submenu.mostrar) for submenu in self._submenus]
        opciones.append(("Crear otro usuario del sistema", self.crear_usuario))
        return opciones

    def crear_usuario(self):
        crear_usuario_interactivo(self._auth)


def crear_usuario_interactivo(autenticacion):
    print("La contraseña debe tener al menos 8 caracteres y combinar letras y números.")
    while True:
        usuario = input("Nuevo usuario: ").strip()
        clave = getpass.getpass("Contraseña (no se muestra al escribir): ")
        if clave != getpass.getpass("Repite la contraseña: "):
            print("  ✘ Las contraseñas no coinciden.")
            continue
        try:
            nombre = autenticacion.registrar(usuario, clave)
        except ErrorDeDominio as e:
            print(f"  ✘ {e}")
            continue
        print(f"  ✔ Usuario '{nombre}' creado.")
        return


def pantalla_acceso(autenticacion, max_intentos=3):
    """Devuelve una Sesion si el login es correcto, o None tras agotar los intentos."""
    if not autenticacion.hay_usuarios():
        print("\nPrimera ejecución: crea el usuario administrador.")
        crear_usuario_interactivo(autenticacion)
    print("\n=== Inicio de sesión ===")
    for _ in range(max_intentos):
        usuario = input("Usuario: ").strip()
        clave = getpass.getpass("Contraseña: ")
        try:
            sesion = autenticacion.iniciar_sesion(usuario, clave)
        except (CredencialesInvalidas, CuentaBloqueada) as e:
            print(f"  ✘ {e}")
            continue
        print(f"  ✔ Bienvenido/a, {sesion.usuario}.")
        return sesion
    print("Demasiados intentos fallidos.")
    return None


def main():
    logging.basicConfig(filename="ecotech.log", level=logging.WARNING,
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    try:
        version, _ = probar_conexion()
        inicializar_bd()
    except ErrorDeConexion as e:
        print(f"No se pudo iniciar la aplicación: {e}")
        return
    print(f"Conectado a SQLite {version}")
    autenticacion = ServicioAutenticacion(UsuarioRepositorio())
    clientes_api = crear_clientes_desde_entorno()
    try:
        while True:
            sesion = pantalla_acceso(autenticacion)
            if sesion is None:
                break
            try:
                MenuPrincipal(sesion, autenticacion, clientes_api).mostrar()
                sesion.cerrar()
                break
            except SesionNoValida as e:
                print(f"\n  ✘ {e}")
    except ErrorDeConexion as e:
        print(f"  ✘ {e}")
    except (KeyboardInterrupt, EOFError):
        print()
    print("Hasta luego.")


if __name__ == "__main__":
    main()
