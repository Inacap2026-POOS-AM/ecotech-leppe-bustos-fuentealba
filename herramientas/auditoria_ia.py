"""Auditoría automática de las 5 señales de riesgo del código generado con IA.

Uso (desde la carpeta del proyecto):   python herramientas/auditoria_ia.py

Revisa todos los .py del proyecto con el árbol sintáctico de Python (ast), no con
búsquedas de texto, para no confundir comentarios o strings con código real:
  1. f-strings / concatenación / .format / % dentro de execute() en SQL
  2. verify=False en peticiones HTTP
  3. except: pass (o except vacío que silencia errores)
  4. llamadas HTTP sin timeout
  5. imports que no son de la biblioteca estándar ni están en requirements.txt
     (posibles paquetes inexistentes o "alucinados" por la IA)
Termina con código 1 si encuentra hallazgos, para poder usarlo antes de cada commit.
"""
import ast
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CARPETAS_IGNORADAS = {".venv", "venv", "__pycache__", ".git"}
METODOS_SQL = {"execute", "executemany", "executescript"}
METODOS_HTTP = {"get", "post", "put", "patch", "delete", "head", "options", "request"}
OBJETOS_HTTP = {"requests", "session", "sesion", "_http", "http", "httpx"}
# nombre con el que se importa -> nombre del paquete en PyPI
PAQUETES_PYPI = {"dotenv": "python-dotenv", "bcrypt": "bcrypt", "requests": "requests"}


def archivos_python():
    for ruta in sorted(RAIZ.rglob("*.py")):
        if not CARPETAS_IGNORADAS.intersection(ruta.relative_to(RAIZ).parts):
            yield ruta


def paquetes_en_requirements():
    archivo = RAIZ / "requirements.txt"
    if not archivo.exists():
        return set()
    nombres = set()
    for linea in archivo.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#")[0].strip()
        if linea:
            nombres.add(re.split(r"[=<>!~\[ ]", linea)[0].lower())
    return nombres


def modulos_locales():
    locales = {p.stem for p in RAIZ.glob("*.py")}
    locales |= {p.name for p in RAIZ.iterdir() if p.is_dir() and (p / "__init__.py").exists()}
    return locales


def nombre_objeto(nodo):
    """'requests' en requests.get(...), '_http' en self._http.get(...)."""
    if isinstance(nodo, ast.Name):
        return nodo.id
    if isinstance(nodo, ast.Attribute):
        return nodo.attr
    return ""


def es_sql_dinamico(arg):
    if isinstance(arg, ast.JoinedStr):                                      # f"..."
        return "f-string"
    if isinstance(arg, ast.BinOp) and isinstance(arg.op, (ast.Add, ast.Mod)):  # "..." + x / "..." % x
        return "concatenación" if isinstance(arg.op, ast.Add) else "formato %"
    if (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "format"):                                 # "...".format(x)
        return ".format()"
    return None


def auditar(ruta, requisitos, locales):
    hallazgos, revisar = [], []
    arbol = ast.parse(ruta.read_text(encoding="utf-8"), filename=str(ruta))
    rel = ruta.relative_to(RAIZ).as_posix()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute):
            metodo = nodo.func.attr
            # 1. SQL dinámico
            if metodo in METODOS_SQL and nodo.args:
                tipo = es_sql_dinamico(nodo.args[0])
                if tipo:
                    hallazgos.append((1, rel, nodo.lineno, f"SQL armado con {tipo}"))
                elif isinstance(nodo.args[0], ast.Name):
                    revisar.append((1, rel, nodo.lineno,
                                    f"SQL en variable '{nodo.args[0].id}': confirmar que solo "
                                    "une textos fijos y que los valores van con ?"))
            # 2 y 4. Peticiones HTTP
            if metodo in METODOS_HTTP and nombre_objeto(nodo.func.value) in OBJETOS_HTTP:
                claves = {kw.arg: kw.value for kw in nodo.keywords}
                verify = claves.get("verify")
                if isinstance(verify, ast.Constant) and verify.value is False:
                    hallazgos.append((2, rel, nodo.lineno, "verify=False desactiva la validación TLS"))
                if "timeout" not in claves:
                    hallazgos.append((4, rel, nodo.lineno, f"llamada .{metodo}() sin timeout"))
        # 3. except que silencia errores
        if isinstance(nodo, ast.ExceptHandler):
            solo_pass = all(isinstance(s, (ast.Pass, ast.Expr)) and
                            (isinstance(s, ast.Pass) or isinstance(getattr(s, "value", None), ast.Constant))
                            for s in nodo.body)
            if nodo.type is None:
                hallazgos.append((3, rel, nodo.lineno, "except: sin tipo (captura hasta Ctrl+C)"))
            elif solo_pass:
                revisar.append((3, rel, nodo.lineno,
                                "except con solo 'pass': confirmar que ignorar el error es intencional"))
        # 5. Librerías
        modulos = []
        if isinstance(nodo, ast.Import):
            modulos = [a.name.split(".")[0] for a in nodo.names]
        elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0 and nodo.module:
            modulos = [nodo.module.split(".")[0]]
        for modulo in modulos:
            if modulo in sys.stdlib_module_names or modulo in locales:
                continue
            paquete = PAQUETES_PYPI.get(modulo, modulo).lower()
            if paquete not in requisitos:
                hallazgos.append((5, rel, nodo.lineno,
                                  f"'{modulo}' no es estándar ni está en requirements.txt "
                                  "(verificar que exista en pypi.org)"))
    return hallazgos, revisar


SENALES = {1: "SQL con f-strings/concatenación", 2: "verify=False", 3: "except: pass",
           4: "HTTP sin timeout", 5: "Librería inexistente / no declarada"}


def main():
    requisitos, locales = paquetes_en_requirements(), modulos_locales()
    todos, por_revisar, total = [], [], 0
    for ruta in archivos_python():
        h, r = auditar(ruta, requisitos, locales)
        todos += h
        por_revisar += r
        total += 1
    print(f"Auditoría de {total} archivos .py en {RAIZ.name}\n")
    for numero, nombre in SENALES.items():
        propios = [h for h in todos if h[0] == numero]
        print(f"[{'FALLA' if propios else ' OK  '}] {numero}. {nombre}: {len(propios)} hallazgo(s)")
        for _, archivo, linea, detalle in propios:
            print(f"         {archivo}:{linea}  {detalle}")
    if por_revisar:
        print("\nRevisión manual (no son fallas automáticamente):")
        for numero, archivo, linea, detalle in por_revisar:
            print(f"  señal {numero} · {archivo}:{linea}  {detalle}")
    return 1 if todos else 0


if __name__ == "__main__":
    sys.exit(main())
