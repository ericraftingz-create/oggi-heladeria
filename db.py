import sqlite3
import os
from werkzeug.security import generate_password_hash

_default = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'heladeria.db')
DB_PATH = os.environ.get('DATABASE_PATH', _default)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

get_conn = get_db

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            unidad TEXT NOT NULL DEFAULT 'kg',
            proveedor TEXT DEFAULT '',
            precio_unitario REAL DEFAULT 0,
            stock_actual REAL DEFAULT 0,
            stock_seguridad REAL DEFAULT 2
        );
        CREATE TABLE IF NOT EXISTS sabores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            disponibilidad TEXT DEFAULT 'bajo_pedido',
            disponibilidad_manual INTEGER DEFAULT 0,
            notas TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS receta_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sabor_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            cantidad REAL NOT NULL DEFAULT 0,
            no_escalar INTEGER DEFAULT 0,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id) ON DELETE CASCADE,
            FOREIGN KEY (insumo_id) REFERENCES insumos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS proceso_pasos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sabor_id INTEGER NOT NULL,
            orden INTEGER NOT NULL DEFAULT 1,
            descripcion TEXT NOT NULL DEFAULT '',
            tiempo_minutos INTEGER,
            temperatura_c REAL,
            notas TEXT DEFAULT '',
            FOREIGN KEY (sabor_id) REFERENCES sabores(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS inventario_reservas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sabor_id INTEGER NOT NULL UNIQUE,
            cantidad REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id)
        );
        CREATE TABLE IF NOT EXISTS produccion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE NOT NULL,
            sabor_id INTEGER NOT NULL,
            cantidad REAL NOT NULL,
            notas TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id)
        );
        CREATE TABLE IF NOT EXISTS heladerias (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            activo INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS pedidos_internos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            heladeria_id INTEGER NOT NULL,
            estado TEXT DEFAULT 'pendiente',
            notas TEXT DEFAULT '',
            responsable TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (heladeria_id) REFERENCES heladerias(id)
        );
        CREATE TABLE IF NOT EXISTS pedido_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_id INTEGER NOT NULL,
            sabor_id INTEGER NOT NULL,
            cantidad REAL NOT NULL,
            tipo_entrega TEXT DEFAULT 'stock',
            FOREIGN KEY (pedido_id) REFERENCES pedidos_internos(id) ON DELETE CASCADE,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id)
        );
        CREATE TABLE IF NOT EXISTS pedidos_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mes INTEGER NOT NULL,
            anio INTEGER NOT NULL,
            estado TEXT DEFAULT 'borrador',
            costo_total REAL DEFAULT 0,
            notas TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS pedido_insumos_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pedido_insumos_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            cantidad_necesaria REAL DEFAULT 0,
            stock_actual REAL DEFAULT 0,
            stock_seguridad REAL DEFAULT 0,
            cantidad_pedir REAL DEFAULT 0,
            precio_unitario REAL DEFAULT 0,
            subtotal REAL DEFAULT 0,
            FOREIGN KEY (pedido_insumos_id) REFERENCES pedidos_insumos(id) ON DELETE CASCADE,
            FOREIGN KEY (insumo_id) REFERENCES insumos(id)
        );
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            nombre TEXT DEFAULT '',
            rol TEXT NOT NULL DEFAULT 'admin' CHECK(rol IN ('superadmin','admin','cliente')),
            heladeria_id INTEGER REFERENCES heladerias(id),
            activo INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            rendimiento_kg REAL DEFAULT 1,
            notas TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS base_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            cantidad REAL NOT NULL DEFAULT 0,
            no_escalar INTEGER DEFAULT 0,
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
            FOREIGN KEY (insumo_id) REFERENCES insumos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS base_pasos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL,
            orden INTEGER NOT NULL DEFAULT 1,
            descripcion TEXT NOT NULL DEFAULT '',
            tiempo_minutos INTEGER,
            temperatura_c REAL,
            notas TEXT DEFAULT '',
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS inventario_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL UNIQUE,
            stock_kg REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (base_id) REFERENCES bases(id)
        );
        CREATE TABLE IF NOT EXISTS produccion_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE NOT NULL,
            base_id INTEGER NOT NULL,
            cantidad_kg REAL NOT NULL,
            notas TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (base_id) REFERENCES bases(id)
        );
        CREATE TABLE IF NOT EXISTS receta_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sabor_id INTEGER NOT NULL,
            base_id INTEGER NOT NULL,
            cantidad_kg REAL NOT NULL DEFAULT 0,
            no_escalar INTEGER DEFAULT 0,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id) ON DELETE CASCADE,
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            heladeria_id INTEGER NOT NULL,
            contenido TEXT NOT NULL,
            completado INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completado_at TIMESTAMP,
            FOREIGN KEY (heladeria_id) REFERENCES heladerias(id)
        );
    """)
    cur = conn.execute("SELECT COUNT(*) FROM heladerias")
    if cur.fetchone()[0] == 0:
        conn.execute("INSERT INTO heladerias (nombre) VALUES ('Heladeria Principal')")
    cur = conn.execute("SELECT COUNT(*) FROM usuarios")
    if cur.fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES ('admin', ?, 'Administrador General', 'superadmin')",
            (generate_password_hash('oggi2024'),)
        )
    conn.commit()
    conn.close()

def migrate_db():
    """Run incremental migrations for columns/tables added after initial schema."""
    conn = get_db()
    try:
        conn.execute("ALTER TABLE pedidos_internos ADD COLUMN responsable TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE base_insumos ADD COLUMN unidad TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE receta_insumos ADD COLUMN unidad TEXT DEFAULT NULL")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE insumos ADD COLUMN mostrar_en_alertas INTEGER DEFAULT 1")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE insumos ADD COLUMN pedido_semanal INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE insumos ADD COLUMN excluir_de_pedido INTEGER DEFAULT 0")
        conn.commit()
    except Exception:
        pass
    try:
        conn.execute("ALTER TABLE sabores ADD COLUMN vida_util_dias INTEGER DEFAULT 7")
        conn.commit()
    except Exception:
        pass
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS movimientos_stock (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tipo TEXT NOT NULL CHECK(tipo IN ('entrada','merma','retiro')),
            target TEXT NOT NULL DEFAULT 'insumo',
            insumo_id INTEGER REFERENCES insumos(id),
            base_id INTEGER REFERENCES bases(id),
            cantidad REAL NOT NULL,
            motivo TEXT DEFAULT '',
            fecha DATE NOT NULL,
            fecha_vencimiento DATE,
            usuario TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS produccion_etiquetas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            produccion_id INTEGER NOT NULL,
            fecha_vencimiento DATE,
            FOREIGN KEY (produccion_id) REFERENCES produccion(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE,
            rendimiento_kg REAL DEFAULT 1,
            notas TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS base_insumos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL,
            insumo_id INTEGER NOT NULL,
            cantidad REAL NOT NULL DEFAULT 0,
            no_escalar INTEGER DEFAULT 0,
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE,
            FOREIGN KEY (insumo_id) REFERENCES insumos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS base_pasos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL,
            orden INTEGER NOT NULL DEFAULT 1,
            descripcion TEXT NOT NULL DEFAULT '',
            tiempo_minutos INTEGER,
            temperatura_c REAL,
            notas TEXT DEFAULT '',
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS inventario_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            base_id INTEGER NOT NULL UNIQUE,
            stock_kg REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (base_id) REFERENCES bases(id)
        );
        CREATE TABLE IF NOT EXISTS produccion_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha DATE NOT NULL,
            base_id INTEGER NOT NULL,
            cantidad_kg REAL NOT NULL,
            notas TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (base_id) REFERENCES bases(id)
        );
        CREATE TABLE IF NOT EXISTS receta_bases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sabor_id INTEGER NOT NULL,
            base_id INTEGER NOT NULL,
            cantidad_kg REAL NOT NULL DEFAULT 0,
            no_escalar INTEGER DEFAULT 0,
            FOREIGN KEY (sabor_id) REFERENCES sabores(id) ON DELETE CASCADE,
            FOREIGN KEY (base_id) REFERENCES bases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS mensajes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            heladeria_id INTEGER NOT NULL,
            contenido TEXT NOT NULL,
            completado INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completado_at TIMESTAMP,
            FOREIGN KEY (heladeria_id) REFERENCES heladerias(id)
        );
    """)
    conn.commit()
    # --- nuevas migraciones ---
    for sql in [
        "ALTER TABLE bases ADD COLUMN pedible INTEGER DEFAULT 0",
        "ALTER TABLE mensajes ADD COLUMN desde TEXT DEFAULT 'admin'",
    ]:
        try:
            conn.execute(sql); conn.commit()
        except Exception:
            pass
    # Recrear pedido_items para permitir sabor_id NULL (soporte bases en pedidos)
    schema_row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='pedido_items'"
    ).fetchone()
    if schema_row and 'sabor_id INTEGER NOT NULL' in schema_row[0]:
        conn.executescript("""
            ALTER TABLE pedido_items RENAME TO pedido_items_old;
            CREATE TABLE pedido_items (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                pedido_id   INTEGER NOT NULL,
                sabor_id    INTEGER,
                base_id     INTEGER REFERENCES bases(id),
                cantidad    REAL NOT NULL DEFAULT 1,
                unidad      TEXT DEFAULT 'tarro',
                tipo_entrega TEXT DEFAULT 'stock',
                FOREIGN KEY (pedido_id) REFERENCES pedidos_internos(id) ON DELETE CASCADE,
                FOREIGN KEY (sabor_id)  REFERENCES sabores(id)
            );
            INSERT INTO pedido_items (id, pedido_id, sabor_id, cantidad, tipo_entrega)
                SELECT id, pedido_id, sabor_id, cantidad, tipo_entrega FROM pedido_items_old;
            DROP TABLE pedido_items_old;
        """)
        conn.commit()
    conn.close()
