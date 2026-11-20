import re
import unicodedata
from datetime import date

from dominio.excepciones import DatoInvalido


def validar_texto(valor, campo):
    if not isinstance(valor, str) or valor.strip() == "":
        raise DatoInvalido(f"El {campo} no puede estar vacío")
    return valor.strip()


def validar_fecha(valor, campo):
    if not isinstance(valor, date):
        raise DatoInvalido(f"La {campo} debe ser una fecha")
    return valor


def validar_id(valor, campo):
    if not isinstance(valor, int) or valor <= 0:
        raise DatoInvalido(f"El {campo} debe ser un número mayor que 0")
    return valor


def validar_sueldo(valor):
    if not isinstance(valor, int) or valor < 0:
        raise DatoInvalido("El sueldo debe ser un número entero mayor o igual a 0")
    return valor


def validar_dias(valor):
    if not isinstance(valor, int) or valor < 0 or valor > 30:
        raise DatoInvalido("Los días trabajados deben estar entre 0 y 30")
    return valor


def validar_horas(valor):
    if not isinstance(valor, (int, float)) or valor <= 0 or valor > 24:
        raise DatoInvalido("Las horas deben ser mayores que 0 y como máximo 24")
    return valor


def calcular_dv(numero):
    suma = 0
    factor = 2
    for digito in reversed(numero):
        suma = suma + int(digito) * factor
        factor = factor + 1
        if factor > 7:
            factor = 2
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def validar_rut(rut):
    if not isinstance(rut, str):
        raise DatoInvalido("El RUT debe ser texto")
    rut = rut.strip().replace(".", "").upper()
    if rut.count("-") != 1:
        raise DatoInvalido("El RUT debe tener el formato 12345678-5")
    numero, dv = rut.split("-")
    if not numero.isdigit() or len(numero) < 7 or len(numero) > 8 or len(dv) != 1:
        raise DatoInvalido("El RUT debe tener el formato 12345678-5")
    if calcular_dv(numero) != dv:
        raise DatoInvalido("El dígito verificador del RUT no es correcto")
    return rut


# ===================== Unidad 3 (ES3) =====================
# Letras (con tildes y ñ), espacios, guion, apóstrofo y punto. Nada de <>;"%&/=\.
_PATRON_CIUDAD = re.compile(r"^[A-Za-zÁÉÍÓÚÜÑáéíóúüñ][A-Za-zÁÉÍÓÚÜÑáéíóúüñ .'\-]{1,59}$")
_PATRON_USUARIO = re.compile(r"^[a-z0-9_.]{3,30}$")
MONEDAS_PERMITIDAS = {"dolar": "USD", "euro": "EUR"}   # lista blanca de indicadores


def normalizar_texto(texto):
    """'  Concepción ' -> 'concepcion': sin tildes, minúsculas y espacios simples."""
    sin_tildes = unicodedata.normalize("NFKD", texto)
    sin_tildes = "".join(c for c in sin_tildes if not unicodedata.combining(c))
    return " ".join(sin_tildes.lower().split())


def validar_ciudad(valor):
    if not isinstance(valor, str):
        raise DatoInvalido("La ciudad debe ser texto")
    ciudad = " ".join(valor.split())
    if not _PATRON_CIUDAD.fullmatch(ciudad):
        raise DatoInvalido("La ciudad debe tener entre 2 y 60 letras (se permiten espacios, "
                           "guiones y tildes, sin números ni símbolos)")
    return ciudad


def validar_moneda(valor):
    if not isinstance(valor, str):
        raise DatoInvalido("La moneda debe ser texto")
    codigo = normalizar_texto(valor)
    if codigo not in MONEDAS_PERMITIDAS:
        raise DatoInvalido(f"Moneda no soportada. Opciones: {', '.join(MONEDAS_PERMITIDAS)}")
    return codigo


def validar_nombre_usuario(valor):
    if not isinstance(valor, str):
        raise DatoInvalido("El usuario debe ser texto")
    usuario = valor.strip().lower()
    if not _PATRON_USUARIO.fullmatch(usuario):
        raise DatoInvalido("El usuario debe tener de 3 a 30 caracteres: letras sin tilde, "
                           "números, punto o guion bajo")
    return usuario


def validar_password_nueva(valor):
    """Política mínima. bcrypt solo considera 72 bytes: se rechaza lo que exceda."""
    if not isinstance(valor, str) or valor == "":
        raise DatoInvalido("La contraseña no puede estar vacía")
    if valor != valor.strip():
        raise DatoInvalido("La contraseña no puede empezar ni terminar con espacios")
    if len(valor) < 8:
        raise DatoInvalido("La contraseña debe tener al menos 8 caracteres")
    if len(valor.encode("utf-8")) > 72:
        raise DatoInvalido("La contraseña es demasiado larga (máximo 72 bytes)")
    if not re.search(r"[A-Za-z]", valor) or not re.search(r"\d", valor):
        raise DatoInvalido("La contraseña debe combinar letras y números")
    return valor
