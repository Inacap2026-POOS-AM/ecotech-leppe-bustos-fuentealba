"""Objetos de dominio con los datos que vienen de servicios externos (ES3).

Son inmutables (frozen): una lectura de clima o un tipo de cambio es un hecho
ocurrido; si cambia, se crea una lectura nueva.
"""
from dataclasses import dataclass
from datetime import date, datetime

# Códigos WMO que usa Open-Meteo -> descripción en español.
DESCRIPCION_WMO = {
    0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado", 3: "Nublado",
    45: "Niebla", 48: "Niebla con escarcha",
    51: "Llovizna débil", 53: "Llovizna", 55: "Llovizna intensa",
    56: "Llovizna helada", 57: "Llovizna helada intensa",
    61: "Lluvia débil", 63: "Lluvia", 65: "Lluvia intensa",
    66: "Lluvia helada", 67: "Lluvia helada intensa",
    71: "Nevada débil", 73: "Nevada", 75: "Nevada intensa", 77: "Granizo fino",
    80: "Chubascos débiles", 81: "Chubascos", 82: "Chubascos violentos",
    85: "Chubascos de nieve", 86: "Chubascos de nieve intensos",
    95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta con granizo intenso",
}
CODIGOS_PRECIPITACION = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77,
                         80, 81, 82, 85, 86, 95, 96, 99}


@dataclass(frozen=True)
class Ubicacion:
    nombre: str
    pais: str          # código ISO de 2 letras, ej: CL
    latitud: float
    longitud: float


@dataclass(frozen=True)
class LecturaClima:
    ubicacion: Ubicacion
    temperatura: float     # °C
    humedad: int           # %
    viento: float          # km/h
    codigo_clima: int      # código WMO
    medido_en: datetime    # hora local de la medición, según la API
    obtenido_en: datetime  # cuándo la descargamos

    @property
    def descripcion(self):
        return DESCRIPCION_WMO.get(self.codigo_clima, f"Código {self.codigo_clima}")

    def evaluar_riesgo(self):
        """Traduce el clima a una recomendación para planificar trabajo en terreno."""
        motivos = []
        if self.codigo_clima in CODIGOS_PRECIPITACION:
            motivos.append(self.descripcion.lower())
        if self.viento >= 40:
            motivos.append(f"viento fuerte ({self.viento:.0f} km/h)")
        if self.temperatura >= 32:
            motivos.append(f"calor extremo ({self.temperatura:.1f} °C)")
        if self.temperatura <= 0:
            motivos.append(f"temperatura bajo cero ({self.temperatura:.1f} °C)")
        if not motivos:
            return "BAJO", "Condiciones aptas para trabajos en terreno"
        nivel = "ALTO" if self.codigo_clima >= 61 or self.viento >= 60 else "MEDIO"
        return nivel, "Reprogramar o reforzar trabajos en terreno por " + ", ".join(motivos)

    def __str__(self):
        return (f"{self.ubicacion.nombre} ({self.ubicacion.pais}): {self.descripcion}, "
                f"{self.temperatura:.1f} °C, humedad {self.humedad}%, viento {self.viento:.0f} km/h "
                f"· medido {self.medido_en.strftime('%d-%m-%Y %H:%M')}")


@dataclass(frozen=True)
class IndicadorEconomico:
    codigo: str            # dolar, euro
    nombre: str
    unidad: str            # Pesos
    valor: float           # pesos chilenos por 1 unidad de la moneda
    fecha: date
    obtenido_en: datetime

    def convertir_desde_pesos(self, monto_clp):
        """Cuántas unidades de esta moneda equivalen a monto_clp pesos."""
        return round(monto_clp / self.valor, 2)

    def __str__(self):
        return (f"{self.nombre}: ${self.valor:,.2f} CLP "
                f"(valor del {self.fecha.strftime('%d-%m-%Y')})")
