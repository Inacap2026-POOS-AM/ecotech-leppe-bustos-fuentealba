-- datos/schema.sql  (SQLite)
-- Repetible: corre sobre una base vacía y también dos veces seguidas (IF NOT EXISTS).
-- Orden: primero las tablas a las que otras apuntan.

CREATE TABLE IF NOT EXISTS departamento (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS proyecto (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre  TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS persona (
    rut     TEXT PRIMARY KEY,                 -- texto, no número (dígito verificador y ceros)
    nombre  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS empleado (
    rut             TEXT PRIMARY KEY,
    fecha_ingreso   DATE NOT NULL,            -- fecha, no texto
    sueldo_base     INTEGER NOT NULL CHECK (sueldo_base >= 0),
    departamento_id INTEGER,
    -- Empleado ES una persona: si se borra la persona, se borra el empleado.
    FOREIGN KEY (rut) REFERENCES persona(rut) ON DELETE CASCADE,
    -- No se puede borrar un departamento que todavía tiene empleados.
    FOREIGN KEY (departamento_id) REFERENCES departamento(id) ON DELETE RESTRICT
);

-- Tabla intermedia de la relación N:M empleado <-> proyecto.
CREATE TABLE IF NOT EXISTS registro_tiempo (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    empleado_rut  TEXT NOT NULL,
    proyecto_id   INTEGER NOT NULL,
    horas         REAL NOT NULL CHECK (horas > 0 AND horas <= 24),
    fecha         DATE NOT NULL,
    -- Composición ◆: los registros mueren con su empleado.
    FOREIGN KEY (empleado_rut) REFERENCES empleado(rut) ON DELETE CASCADE,
    FOREIGN KEY (proyecto_id)  REFERENCES proyecto(id)  ON DELETE RESTRICT
);

-- ===================== Unidad 3 (ES3) =====================

-- Usuarios del sistema. La contraseña NUNCA se guarda: solo su hash bcrypt,
-- que ya incluye el salt y el costo (ej: $2b$12$<salt><hash>).
CREATE TABLE IF NOT EXISTS usuario (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre_usuario     TEXT NOT NULL UNIQUE,
    hash_password      TEXT NOT NULL CHECK (hash_password LIKE '$2%'),
    intentos_fallidos  INTEGER NOT NULL DEFAULT 0,
    bloqueado_hasta    TEXT,                  -- ISO 8601; NULL = no bloqueado
    creado_en          TEXT NOT NULL
);

-- Lecturas de clima (API Open-Meteo).
-- UNIQUE evita duplicados: la misma ciudad en la misma medición se actualiza, no se repite.
CREATE TABLE IF NOT EXISTS lectura_clima (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ciudad              TEXT NOT NULL,
    ciudad_normalizada  TEXT NOT NULL,        -- sin tildes ni mayúsculas, para el Plan B
    pais                TEXT NOT NULL,
    latitud             REAL NOT NULL,
    longitud            REAL NOT NULL,
    temperatura         REAL NOT NULL,
    humedad             INTEGER NOT NULL CHECK (humedad BETWEEN 0 AND 100),
    viento              REAL NOT NULL CHECK (viento >= 0),
    codigo_clima        INTEGER NOT NULL,
    descripcion         TEXT NOT NULL,
    medido_en           TEXT NOT NULL,        -- hora de la medición según la API
    obtenido_en         TEXT NOT NULL,        -- cuándo lo descargamos (antigüedad del Plan B)
    UNIQUE (ciudad_normalizada, pais, medido_en)
);

-- Indicadores económicos (API mindicador.cl): tipo de cambio en pesos chilenos.
CREATE TABLE IF NOT EXISTS indicador_economico (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo        TEXT NOT NULL,              -- dolar, euro
    nombre        TEXT NOT NULL,
    unidad        TEXT NOT NULL,
    valor         REAL NOT NULL CHECK (valor > 0),
    fecha         DATE NOT NULL,              -- día al que corresponde el valor
    obtenido_en   TEXT NOT NULL,
    UNIQUE (codigo, fecha)
);
