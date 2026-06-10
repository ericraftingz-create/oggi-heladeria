from flask import (Flask, render_template, request, redirect, url_for,
                   jsonify, send_file, flash, session)
from functools import wraps
from werkzeug.security import generate_password_hash, check_password_hash
import os, json
from datetime import date, timedelta
import webbrowser, threading

from db import get_db, init_db, migrate_db

app = Flask(__name__)
app.secret_key = 'oggi_officina_gelato_2024_secret'

# Inicializar DB y migraciones al arrancar (funciona tanto en WSGI como local)
init_db()
migrate_db()

# ─────────────────────────────────────────────
# AUTH DECORATORS
# ─────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.path))
        if session.get('rol') == 'cliente':
            return redirect(url_for('heladeria_portal', hid=session.get('heladeria_id', 1)))
        return f(*args, **kwargs)
    return decorated

def superadmin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        if session.get('rol') != 'superadmin':
            flash('Acceso denegado: se requiere rol de superadmin.', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated

@app.context_processor
def inject_user():
    return dict(cu={
        'id': session.get('user_id'),
        'username': session.get('username'),
        'nombre': session.get('nombre'),
        'rol': session.get('rol'),
        'heladeria_id': session.get('heladeria_id'),
        'is_superadmin': session.get('rol') == 'superadmin',
        'is_admin': session.get('rol') in ('superadmin', 'admin'),
    })

# ─────────────────────────────────────────────
# LOGIN / LOGOUT
# ─────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    if 'user_id' in session:
        if session.get('rol') == 'cliente':
            return redirect(url_for('heladeria_portal', hid=session.get('heladeria_id', 1)))
        return redirect(url_for('index'))
    db = get_db()
    heladerias = db.execute(
        "SELECT id, nombre FROM heladerias WHERE activo=1 ORDER BY nombre"
    ).fetchall()
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        heladeria_id = request.form.get('heladeria_id', '').strip()
        user = db.execute(
            "SELECT * FROM usuarios WHERE username=? AND activo=1", (username,)
        ).fetchone()
        db.close()
        if user and check_password_hash(user['password_hash'], password):
            if heladeria_id and str(user['heladeria_id']) != heladeria_id:
                flash('Este usuario no pertenece a la heladería seleccionada.', 'danger')
                return render_template('login.html', heladerias=heladerias)
            session.permanent = True
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['nombre'] = user['nombre'] or user['username']
            session['rol'] = user['rol']
            session['heladeria_id'] = user['heladeria_id']
            if user['rol'] == 'cliente':
                return redirect(url_for('heladeria_portal', hid=user['heladeria_id']))
            next_url = request.args.get('next')
            return redirect(next_url or url_for('index'))
        else:
            db.close()
        flash('Usuario o contraseña incorrectos.', 'danger')
    else:
        db.close()
    return render_template('login.html', heladerias=heladerias)

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for('login'))

# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def actualizar_disponibilidad(sabor_id):
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (sabor_id,)).fetchone()
    if not sabor or sabor['disponibilidad_manual']:
        db.close()
        return
    inv = db.execute("SELECT cantidad FROM inventario_reservas WHERE sabor_id=?", (sabor_id,)).fetchone()
    stock_reservas = inv['cantidad'] if inv else 0
    nueva = 'disponible' if stock_reservas > 0 else 'bajo_pedido'
    db.execute("UPDATE sabores SET disponibilidad=? WHERE id=?", (nueva, sabor_id))
    db.commit()
    db.close()

# ─────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────

@app.route('/')
@admin_required
def index():
    db = get_db()
    hoy = date.today().isoformat()
    stats = {
        'sabores': db.execute("SELECT COUNT(*) FROM sabores").fetchone()[0],
        'insumos': db.execute("SELECT COUNT(*) FROM insumos").fetchone()[0],
        'pedidos_pendientes': db.execute(
            "SELECT COUNT(*) FROM pedidos_internos WHERE estado='pendiente'"
        ).fetchone()[0],
        'prod_hoy': db.execute(
            "SELECT COALESCE(SUM(cantidad),0) FROM produccion WHERE fecha=?", (hoy,)
        ).fetchone()[0],
    }
    prod_hoy = db.execute("""
        SELECT p.*, s.nombre as sabor_nombre
        FROM produccion p JOIN sabores s ON s.id=p.sabor_id
        WHERE p.fecha=? ORDER BY p.created_at DESC
    """, (hoy,)).fetchall()
    stock_bajo = db.execute(
        "SELECT * FROM insumos WHERE stock_actual <= stock_seguridad ORDER BY nombre"
    ).fetchall()
    inventario = db.execute("""
        SELECT s.nombre, ir.cantidad, s.disponibilidad
        FROM inventario_reservas ir JOIN sabores s ON s.id=ir.sabor_id
        WHERE ir.cantidad > 0 ORDER BY ir.cantidad DESC
    """).fetchall()
    pedidos_recientes = db.execute("""
        SELECT pi.*, h.nombre as heladeria_nombre
        FROM pedidos_internos pi JOIN heladerias h ON h.id=pi.heladeria_id
        WHERE pi.estado != 'entregado' ORDER BY pi.created_at DESC LIMIT 5
    """).fetchall()
    db.close()
    return render_template('index.html',
        stats=stats, prod_hoy=prod_hoy, stock_bajo=stock_bajo,
        inventario=inventario, pedidos_recientes=pedidos_recientes, hoy=hoy)

# ─────────────────────────────────────────────
# INSUMOS
# ─────────────────────────────────────────────

@app.route('/insumos')
@admin_required
def insumos():
    db = get_db()
    items = db.execute("SELECT * FROM insumos ORDER BY nombre").fetchall()
    db.close()
    return render_template('insumos.html', insumos=items)

@app.route('/insumos/nuevo', methods=['GET', 'POST'])
@superadmin_required
def insumo_nuevo():
    if request.method == 'POST':
        db = get_db()
        db.execute("""
            INSERT INTO insumos (nombre, unidad, proveedor, precio_unitario, stock_actual, stock_seguridad)
            VALUES (?,?,?,?,?,?)
        """, (
            request.form['nombre'], request.form['unidad'],
            request.form.get('proveedor', ''),
            float(request.form.get('precio_unitario', 0) or 0),
            float(request.form.get('stock_actual', 0) or 0),
            float(request.form.get('stock_seguridad', 2) or 2),
        ))
        db.commit(); db.close()
        flash('Insumo creado', 'success')
        return redirect(url_for('insumos'))
    return render_template('insumo_form.html', insumo=None, titulo='Nuevo Insumo')

@app.route('/insumos/<int:id>/editar', methods=['GET', 'POST'])
@superadmin_required
def insumo_editar(id):
    db = get_db()
    insumo = db.execute("SELECT * FROM insumos WHERE id=?", (id,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE insumos SET nombre=?, unidad=?, proveedor=?,
            precio_unitario=?, stock_actual=?, stock_seguridad=? WHERE id=?
        """, (
            request.form['nombre'], request.form['unidad'],
            request.form.get('proveedor', ''),
            float(request.form.get('precio_unitario', 0) or 0),
            float(request.form.get('stock_actual', 0) or 0),
            float(request.form.get('stock_seguridad', 2) or 2),
            id
        ))
        db.commit(); db.close()
        flash('Insumo actualizado', 'success')
        return redirect(url_for('insumos'))
    db.close()
    return render_template('insumo_form.html', insumo=insumo, titulo='Editar Insumo')

@app.route('/insumos/<int:id>/eliminar', methods=['POST'])
@superadmin_required
def insumo_eliminar(id):
    db = get_db()
    try:
        db.execute("DELETE FROM insumos WHERE id=?", (id,))
        db.commit()
        flash('Insumo eliminado', 'warning')
    except Exception:
        flash('No se puede eliminar: este insumo está en uso en una o más recetas. Primero quitalo de las recetas.', 'danger')
    db.close()
    return redirect(url_for('insumos'))

@app.route('/insumos/<int:id>/entrada', methods=['POST'])
@admin_required
def insumo_entrada(id):
    """Suma stock cuando llega mercadería."""
    cantidad = float(request.form.get('cantidad', 0) or 0)
    if cantidad <= 0:
        flash('La cantidad debe ser mayor a 0.', 'warning')
        return redirect(url_for('insumos'))
    db = get_db()
    db.execute("UPDATE insumos SET stock_actual = stock_actual + ? WHERE id=?", (cantidad, id))
    db.commit(); db.close()
    flash(f'Stock actualizado (+{cantidad})', 'success')
    return redirect(url_for('insumos'))

# ─────────────────────────────────────────────
# SABORES
# ─────────────────────────────────────────────

@app.route('/sabores')
@admin_required
def sabores():
    db = get_db()
    items = db.execute("""
        SELECT s.*,
               COALESCE(ir.cantidad, 0) as stock_reservas,
               (SELECT COUNT(*) FROM receta_insumos WHERE sabor_id=s.id) as n_ingredientes,
               (SELECT COUNT(*) FROM proceso_pasos WHERE sabor_id=s.id) as n_pasos
        FROM sabores s LEFT JOIN inventario_reservas ir ON ir.sabor_id=s.id
        ORDER BY s.nombre
    """).fetchall()
    db.close()
    return render_template('sabores.html', sabores=items)

@app.route('/sabores/nuevo', methods=['GET', 'POST'])
@superadmin_required
def sabor_nuevo():
    if request.method == 'POST':
        db = get_db()
        cur = db.execute("""
            INSERT INTO sabores (nombre, disponibilidad, disponibilidad_manual, notas)
            VALUES (?,?,1,?)
        """, (request.form['nombre'], request.form.get('disponibilidad', 'bajo_pedido'), request.form.get('notas', '')))
        sid = cur.lastrowid
        db.execute("INSERT INTO inventario_reservas (sabor_id, cantidad) VALUES (?,0)", (sid,))
        db.commit(); db.close()
        flash('Sabor creado', 'success')
        return redirect(url_for('sabores'))
    return render_template('sabor_form.html', sabor=None, titulo='Nuevo Sabor')

@app.route('/sabores/<int:id>/editar', methods=['GET', 'POST'])
@superadmin_required
def sabor_editar(id):
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (id,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE sabores SET nombre=?, disponibilidad=?, disponibilidad_manual=1, notas=? WHERE id=?
        """, (request.form['nombre'], request.form.get('disponibilidad', 'bajo_pedido'),
              request.form.get('notas', ''), id))
        db.commit(); db.close()
        flash('Sabor actualizado', 'success')
        return redirect(url_for('sabores'))
    db.close()
    return render_template('sabor_form.html', sabor=sabor, titulo='Editar Sabor')

@app.route('/sabores/<int:id>/eliminar', methods=['POST'])
@superadmin_required
def sabor_eliminar(id):
    db = get_db()
    db.execute("DELETE FROM sabores WHERE id=?", (id,))
    db.commit(); db.close()
    flash('Sabor eliminado', 'warning')
    return redirect(url_for('sabores'))

@app.route('/sabores/<int:id>/disponibilidad', methods=['POST'])
@admin_required
def sabor_disponibilidad(id):
    db = get_db()
    db.execute("UPDATE sabores SET disponibilidad=?, disponibilidad_manual=1 WHERE id=?",
               (request.form['disponibilidad'], id))
    db.commit(); db.close()
    return redirect(url_for('sabores'))

# ─────────────────────────────────────────────
# RECETA
# ─────────────────────────────────────────────

@app.route('/sabores/<int:id>/receta', methods=['GET', 'POST'])
@admin_required
def receta(id):
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (id,)).fetchone()

    if request.method == 'POST':
        if session.get('rol') != 'superadmin':
            flash('Solo el superadmin puede modificar recetas.', 'danger')
            return redirect(url_for('receta', id=id))
        action = request.form.get('action')
        # Raw insumos
        if action == 'add':
            iid = request.form['insumo_id']
            cant = float(request.form.get('cantidad', 0) or 0)
            no_esc = 1 if request.form.get('no_escalar') else 0
            existe = db.execute("SELECT id FROM receta_insumos WHERE sabor_id=? AND insumo_id=?", (id, iid)).fetchone()
            if existe:
                db.execute("UPDATE receta_insumos SET cantidad=?, no_escalar=? WHERE id=?", (cant, no_esc, existe['id']))
            else:
                db.execute("INSERT INTO receta_insumos (sabor_id, insumo_id, cantidad, no_escalar) VALUES (?,?,?,?)",
                           (id, iid, cant, no_esc))
            db.commit()
        elif action == 'remove':
            db.execute("DELETE FROM receta_insumos WHERE id=?", (request.form['ri_id'],))
            db.commit()
        elif action == 'update':
            db.execute("UPDATE receta_insumos SET cantidad=?, no_escalar=? WHERE id=?",
                       (float(request.form.get('cantidad', 0) or 0),
                        1 if request.form.get('no_escalar') else 0,
                        request.form['ri_id']))
            db.commit()
        # Bases en receta
        elif action == 'add_base':
            bid = request.form['base_id']
            cant = float(request.form.get('cantidad_kg', 0) or 0)
            no_esc = 1 if request.form.get('no_escalar') else 0
            existe = db.execute("SELECT id FROM receta_bases WHERE sabor_id=? AND base_id=?", (id, bid)).fetchone()
            if existe:
                db.execute("UPDATE receta_bases SET cantidad_kg=?, no_escalar=? WHERE id=?", (cant, no_esc, existe['id']))
            else:
                db.execute("INSERT INTO receta_bases (sabor_id, base_id, cantidad_kg, no_escalar) VALUES (?,?,?,?)",
                           (id, bid, cant, no_esc))
            db.commit()
        elif action == 'remove_base':
            db.execute("DELETE FROM receta_bases WHERE id=?", (request.form['rb_id'],))
            db.commit()
        elif action == 'update_base':
            db.execute("UPDATE receta_bases SET cantidad_kg=?, no_escalar=? WHERE id=?",
                       (float(request.form.get('cantidad_kg', 0) or 0),
                        1 if request.form.get('no_escalar') else 0,
                        request.form['rb_id']))
            db.commit()
        return redirect(url_for('receta', id=id))

    ingredientes = db.execute("""
        SELECT ri.*, i.nombre as insumo_nombre, i.unidad
        FROM receta_insumos ri JOIN insumos i ON i.id=ri.insumo_id
        WHERE ri.sabor_id=? ORDER BY i.nombre
    """, (id,)).fetchall()
    todos_insumos = db.execute("SELECT id, nombre, unidad FROM insumos ORDER BY nombre").fetchall()
    bases_receta = db.execute("""
        SELECT rb.*, b.nombre as base_nombre, COALESCE(ib.stock_kg,0) as stock_kg
        FROM receta_bases rb JOIN bases b ON b.id=rb.base_id
        LEFT JOIN inventario_bases ib ON ib.base_id=rb.base_id
        WHERE rb.sabor_id=? ORDER BY b.nombre
    """, (id,)).fetchall()
    todas_bases = db.execute("SELECT id, nombre, rendimiento_kg FROM bases ORDER BY nombre").fetchall()
    db.close()
    return render_template('receta.html', sabor=sabor, ingredientes=ingredientes,
                           todos_insumos=todos_insumos, bases_receta=bases_receta, todas_bases=todas_bases)

# ─────────────────────────────────────────────
# PROCESO
# ─────────────────────────────────────────────

@app.route('/sabores/<int:id>/proceso', methods=['GET', 'POST'])
@admin_required
def proceso(id):
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (id,)).fetchone()

    if request.method == 'POST':
        if session.get('rol') != 'superadmin':
            flash('Solo el superadmin puede modificar el proceso.', 'danger')
            return redirect(url_for('proceso', id=id))
        action = request.form.get('action')
        if action == 'add':
            orden = db.execute(
                "SELECT COALESCE(MAX(orden),0)+1 FROM proceso_pasos WHERE sabor_id=?", (id,)
            ).fetchone()[0]
            db.execute("""
                INSERT INTO proceso_pasos (sabor_id, orden, descripcion, tiempo_minutos, temperatura_c, notas)
                VALUES (?,?,?,?,?,?)
            """, (id, orden, request.form.get('descripcion', ''),
                  request.form.get('tiempo_minutos') or None,
                  request.form.get('temperatura_c') or None,
                  request.form.get('notas', '')))
            db.commit()
        elif action == 'delete':
            db.execute("DELETE FROM proceso_pasos WHERE id=?", (request.form['paso_id'],))
            db.commit()
        elif action == 'update':
            db.execute("""
                UPDATE proceso_pasos SET descripcion=?, tiempo_minutos=?, temperatura_c=?, notas=? WHERE id=?
            """, (request.form.get('descripcion', ''),
                  request.form.get('tiempo_minutos') or None,
                  request.form.get('temperatura_c') or None,
                  request.form.get('notas', ''),
                  request.form['paso_id']))
            db.commit()
        return redirect(url_for('proceso', id=id))

    pasos = db.execute("SELECT * FROM proceso_pasos WHERE sabor_id=? ORDER BY orden", (id,)).fetchall()
    db.close()
    return render_template('proceso.html', sabor=sabor, pasos=pasos)

# ─────────────────────────────────────────────
# COCINA
# ─────────────────────────────────────────────

@app.route('/sabores/<int:id>/cocina')
@admin_required
def cocina(id):
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (id,)).fetchone()
    ingredientes = db.execute("""
        SELECT ri.*, i.nombre as insumo_nombre, i.unidad, i.stock_actual
        FROM receta_insumos ri JOIN insumos i ON i.id=ri.insumo_id
        WHERE ri.sabor_id=? ORDER BY i.nombre
    """, (id,)).fetchall()
    bases_receta = db.execute("""
        SELECT rb.*, b.nombre as base_nombre, COALESCE(ib.stock_kg,0) as stock_kg
        FROM receta_bases rb JOIN bases b ON b.id=rb.base_id
        LEFT JOIN inventario_bases ib ON ib.base_id=rb.base_id
        WHERE rb.sabor_id=? ORDER BY b.nombre
    """, (id,)).fetchall()
    pasos = db.execute("SELECT * FROM proceso_pasos WHERE sabor_id=? ORDER BY orden", (id,)).fetchall()
    db.close()
    return render_template('cocina.html', sabor=sabor, ingredientes=ingredientes,
                           bases_receta=bases_receta, pasos=pasos)

@app.route('/api/receta/<int:id>/escalar')
@admin_required
def api_escalar(id):
    mult = float(request.args.get('mult', 1))
    db = get_db()
    ingredientes = db.execute("""
        SELECT ri.*, i.nombre, i.unidad, i.stock_actual
        FROM receta_insumos ri JOIN insumos i ON i.id=ri.insumo_id WHERE ri.sabor_id=?
    """, (id,)).fetchall()
    result = []
    for r in ingredientes:
        cantidad = r['cantidad'] if r['no_escalar'] else round(r['cantidad'] * mult, 4)
        result.append({'nombre': r['nombre'], 'unidad': r['unidad'], 'cantidad': cantidad,
                       'no_escalar': bool(r['no_escalar']), 'stock': r['stock_actual'],
                       'ok': r['stock_actual'] >= cantidad})
    db.close()
    return jsonify(result)

# ─────────────────────────────────────────────
# BASES (productos intermedios)
# ─────────────────────────────────────────────

@app.route('/bases')
@admin_required
def bases():
    db = get_db()
    items = db.execute("""
        SELECT b.*,
               COALESCE(ib.stock_kg, 0) as stock_kg,
               (SELECT COUNT(*) FROM base_insumos WHERE base_id=b.id) as n_ingredientes,
               (SELECT COUNT(*) FROM base_pasos WHERE base_id=b.id) as n_pasos
        FROM bases b LEFT JOIN inventario_bases ib ON ib.base_id=b.id
        ORDER BY b.nombre
    """).fetchall()
    prod_hoy = db.execute("""
        SELECT pb.*, b.nombre as base_nombre
        FROM produccion_bases pb JOIN bases b ON b.id=pb.base_id
        WHERE pb.fecha=? ORDER BY pb.created_at DESC
    """, (date.today().isoformat(),)).fetchall()
    db.close()
    return render_template('bases.html', bases=items, prod_hoy=prod_hoy,
                           hoy=date.today().isoformat())

@app.route('/bases/nueva', methods=['GET', 'POST'])
@superadmin_required
def base_nueva():
    if request.method == 'POST':
        db = get_db()
        try:
            cur = db.execute("""
                INSERT INTO bases (nombre, rendimiento_kg, notas) VALUES (?,?,?)
            """, (request.form['nombre'].strip(),
                  float(request.form.get('rendimiento_kg', 1) or 1),
                  request.form.get('notas', '')))
            bid = cur.lastrowid
            db.execute("INSERT INTO inventario_bases (base_id, stock_kg) VALUES (?,0)", (bid,))
            db.commit()
            flash('Base creada', 'success')
        except Exception as e:
            flash('Ya existe una base con ese nombre.', 'danger')
        db.close()
        return redirect(url_for('bases'))
    return render_template('base_form.html', base=None, titulo='Nueva Base')

@app.route('/bases/<int:id>/editar', methods=['GET', 'POST'])
@superadmin_required
def base_editar(id):
    db = get_db()
    base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
    if request.method == 'POST':
        db.execute("""
            UPDATE bases SET nombre=?, rendimiento_kg=?, notas=? WHERE id=?
        """, (request.form['nombre'].strip(),
              float(request.form.get('rendimiento_kg', 1) or 1),
              request.form.get('notas', ''), id))
        db.commit(); db.close()
        flash('Base actualizada', 'success')
        return redirect(url_for('bases'))
    db.close()
    return render_template('base_form.html', base=base, titulo='Editar Base')

@app.route('/bases/<int:id>/eliminar', methods=['POST'])
@superadmin_required
def base_eliminar(id):
    db = get_db()
    db.execute("DELETE FROM bases WHERE id=?", (id,))
    db.commit(); db.close()
    flash('Base eliminada', 'warning')
    return redirect(url_for('bases'))

@app.route('/bases/<int:id>/receta', methods=['GET', 'POST'])
@admin_required
def base_receta(id):
    db = get_db()
    base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
    if request.method == 'POST':
        if session.get('rol') != 'superadmin':
            flash('Solo el superadmin puede modificar recetas.', 'danger')
            return redirect(url_for('base_receta', id=id))
        action = request.form.get('action')
        if action == 'add':
            iid = request.form['insumo_id']
            cant = float(request.form.get('cantidad', 0) or 0)
            no_esc = 1 if request.form.get('no_escalar') else 0
            existe = db.execute("SELECT id FROM base_insumos WHERE base_id=? AND insumo_id=?", (id, iid)).fetchone()
            if existe:
                db.execute("UPDATE base_insumos SET cantidad=?, no_escalar=? WHERE id=?", (cant, no_esc, existe['id']))
            else:
                db.execute("INSERT INTO base_insumos (base_id, insumo_id, cantidad, no_escalar) VALUES (?,?,?,?)",
                           (id, iid, cant, no_esc))
            db.commit()
        elif action == 'remove':
            db.execute("DELETE FROM base_insumos WHERE id=?", (request.form['bi_id'],))
            db.commit()
        elif action == 'update':
            db.execute("UPDATE base_insumos SET cantidad=?, no_escalar=? WHERE id=?",
                       (float(request.form.get('cantidad', 0) or 0),
                        1 if request.form.get('no_escalar') else 0,
                        request.form['bi_id']))
            db.commit()
        return redirect(url_for('base_receta', id=id))
    ingredientes = db.execute("""
        SELECT bi.*, i.nombre as insumo_nombre, i.unidad
        FROM base_insumos bi JOIN insumos i ON i.id=bi.insumo_id
        WHERE bi.base_id=? ORDER BY i.nombre
    """, (id,)).fetchall()
    todos_insumos = db.execute("SELECT id, nombre, unidad FROM insumos ORDER BY nombre").fetchall()
    db.close()
    return render_template('base_receta.html', base=base, ingredientes=ingredientes,
                           todos_insumos=todos_insumos)

@app.route('/bases/<int:id>/proceso', methods=['GET', 'POST'])
@admin_required
def base_proceso(id):
    db = get_db()
    base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
    if request.method == 'POST':
        if session.get('rol') != 'superadmin':
            flash('Solo el superadmin puede modificar el proceso.', 'danger')
            return redirect(url_for('base_proceso', id=id))
        action = request.form.get('action')
        if action == 'add':
            orden = db.execute(
                "SELECT COALESCE(MAX(orden),0)+1 FROM base_pasos WHERE base_id=?", (id,)
            ).fetchone()[0]
            db.execute("""
                INSERT INTO base_pasos (base_id, orden, descripcion, tiempo_minutos, temperatura_c, notas)
                VALUES (?,?,?,?,?,?)
            """, (id, orden, request.form.get('descripcion', ''),
                  request.form.get('tiempo_minutos') or None,
                  request.form.get('temperatura_c') or None,
                  request.form.get('notas', '')))
            db.commit()
        elif action == 'delete':
            db.execute("DELETE FROM base_pasos WHERE id=?", (request.form['paso_id'],))
            db.commit()
        elif action == 'update':
            db.execute("""
                UPDATE base_pasos SET descripcion=?, tiempo_minutos=?, temperatura_c=?, notas=? WHERE id=?
            """, (request.form.get('descripcion', ''),
                  request.form.get('tiempo_minutos') or None,
                  request.form.get('temperatura_c') or None,
                  request.form.get('notas', ''),
                  request.form['paso_id']))
            db.commit()
        return redirect(url_for('base_proceso', id=id))
    pasos = db.execute("SELECT * FROM base_pasos WHERE base_id=? ORDER BY orden", (id,)).fetchall()
    db.close()
    return render_template('base_proceso.html', base=base, pasos=pasos)

@app.route('/bases/<int:id>/cocina')
@admin_required
def base_cocina(id):
    db = get_db()
    base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
    ingredientes = db.execute("""
        SELECT bi.*, i.nombre as insumo_nombre, i.unidad, i.stock_actual
        FROM base_insumos bi JOIN insumos i ON i.id=bi.insumo_id
        WHERE bi.base_id=? ORDER BY i.nombre
    """, (id,)).fetchall()
    pasos = db.execute("SELECT * FROM base_pasos WHERE base_id=? ORDER BY orden", (id,)).fetchall()
    prod_reciente = db.execute("""
        SELECT * FROM produccion_bases WHERE base_id=? ORDER BY created_at DESC LIMIT 5
    """, (id,)).fetchall()
    stock = db.execute("SELECT stock_kg FROM inventario_bases WHERE base_id=?", (id,)).fetchone()
    stock_kg = stock['stock_kg'] if stock else 0
    db.close()
    return render_template('base_cocina.html', base=base, ingredientes=ingredientes,
                           pasos=pasos, prod_reciente=prod_reciente, stock_kg=stock_kg)

@app.route('/bases/<int:id>/produccion', methods=['POST'])
@admin_required
def base_produccion(id):
    db = get_db()
    base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
    cantidad_kg = float(request.form.get('cantidad_kg', 0) or 0)
    fecha = request.form.get('fecha', date.today().isoformat())
    notas = request.form.get('notas', '')
    if cantidad_kg <= 0:
        flash('La cantidad debe ser mayor a 0.', 'warning')
        db.close()
        return redirect(url_for('base_cocina', id=id))
    db.execute("INSERT INTO produccion_bases (fecha, base_id, cantidad_kg, notas) VALUES (?,?,?,?)",
               (fecha, id, cantidad_kg, notas))
    db.execute("""
        INSERT INTO inventario_bases (base_id, stock_kg) VALUES (?,?)
        ON CONFLICT(base_id) DO UPDATE SET stock_kg = stock_kg + excluded.stock_kg
    """, (id, cantidad_kg))
    rendimiento = (base['rendimiento_kg'] or 1)
    mult = cantidad_kg / rendimiento
    receta = db.execute("SELECT * FROM base_insumos WHERE base_id=?", (id,)).fetchall()
    for r in receta:
        consumo = r['cantidad'] if r['no_escalar'] else r['cantidad'] * mult
        db.execute("UPDATE insumos SET stock_actual = MAX(0, stock_actual - ?) WHERE id=?",
                   (consumo, r['insumo_id']))
    db.commit(); db.close()
    flash(f'Producción registrada: {cantidad_kg} kg de {base["nombre"]}', 'success')
    return redirect(url_for('base_cocina', id=id))

@app.route('/bases/<int:id>/produccion/<int:pid>/eliminar', methods=['POST'])
@admin_required
def base_produccion_eliminar(id, pid):
    db = get_db()
    prod = db.execute("SELECT * FROM produccion_bases WHERE id=? AND base_id=?", (pid, id)).fetchone()
    if prod:
        base = db.execute("SELECT * FROM bases WHERE id=?", (id,)).fetchone()
        db.execute("UPDATE inventario_bases SET stock_kg = MAX(0, stock_kg - ?) WHERE base_id=?",
                   (prod['cantidad_kg'], id))
        rendimiento = (base['rendimiento_kg'] or 1)
        mult = prod['cantidad_kg'] / rendimiento
        receta = db.execute("SELECT * FROM base_insumos WHERE base_id=?", (id,)).fetchall()
        for r in receta:
            consumo = r['cantidad'] if r['no_escalar'] else r['cantidad'] * mult
            db.execute("UPDATE insumos SET stock_actual = stock_actual + ? WHERE id=?",
                       (consumo, r['insumo_id']))
        db.execute("DELETE FROM produccion_bases WHERE id=?", (pid,))
        db.commit()
        flash('Registro de base eliminado y stocks revertidos.', 'warning')
    db.close()
    return redirect(url_for('base_cocina', id=id))

@app.route('/api/base-receta/<int:id>/escalar')
@admin_required
def api_base_escalar(id):
    kg = float(request.args.get('kg', 1))
    db = get_db()
    base = db.execute("SELECT rendimiento_kg FROM bases WHERE id=?", (id,)).fetchone()
    rendimiento = (base['rendimiento_kg'] or 1) if base else 1
    mult = kg / rendimiento
    ingredientes = db.execute("""
        SELECT bi.*, i.nombre, i.unidad, i.stock_actual
        FROM base_insumos bi JOIN insumos i ON i.id=bi.insumo_id WHERE bi.base_id=?
    """, (id,)).fetchall()
    result = []
    for r in ingredientes:
        cantidad = r['cantidad'] if r['no_escalar'] else round(r['cantidad'] * mult, 4)
        result.append({'nombre': r['nombre'], 'unidad': r['unidad'], 'cantidad': cantidad,
                       'no_escalar': bool(r['no_escalar']), 'stock': r['stock_actual'],
                       'ok': r['stock_actual'] >= cantidad})
    db.close()
    return jsonify(result)

# ─────────────────────────────────────────────
# PRODUCCIÓN
# ─────────────────────────────────────────────

@app.route('/produccion', methods=['GET', 'POST'])
@admin_required
def produccion():
    db = get_db()
    if request.method == 'POST':
        sabor_id = int(request.form['sabor_id'])
        cantidad = float(request.form['cantidad'])
        fecha = request.form.get('fecha', date.today().isoformat())
        notas = request.form.get('notas', '')
        db.execute("INSERT INTO produccion (fecha, sabor_id, cantidad, notas) VALUES (?,?,?,?)",
                   (fecha, sabor_id, cantidad, notas))
        db.execute("""
            INSERT INTO inventario_reservas (sabor_id, cantidad) VALUES (?,?)
            ON CONFLICT(sabor_id) DO UPDATE SET cantidad = cantidad + excluded.cantidad
        """, (sabor_id, cantidad))
        # Descontar insumos crudos
        receta_ins = db.execute("SELECT * FROM receta_insumos WHERE sabor_id=?", (sabor_id,)).fetchall()
        for r in receta_ins:
            consumo = r['cantidad'] if r['no_escalar'] else r['cantidad'] * cantidad
            db.execute("UPDATE insumos SET stock_actual = MAX(0, stock_actual - ?) WHERE id=?",
                       (consumo, r['insumo_id']))
        # Descontar bases usadas en la receta
        receta_b = db.execute("SELECT * FROM receta_bases WHERE sabor_id=?", (sabor_id,)).fetchall()
        for r in receta_b:
            consumo_kg = r['cantidad_kg'] if r['no_escalar'] else r['cantidad_kg'] * cantidad
            db.execute("UPDATE inventario_bases SET stock_kg = MAX(0, stock_kg - ?) WHERE base_id=?",
                       (consumo_kg, r['base_id']))
        db.commit()
        actualizar_disponibilidad(sabor_id)
        flash(f'Producción registrada: {cantidad} reserva(s) = {round(cantidad*4,2)} L', 'success')
        return redirect(url_for('produccion'))

    hoy = date.today().isoformat()
    mes_actual = date.today().strftime('%Y-%m')
    sabores_activos = db.execute(
        "SELECT * FROM sabores WHERE disponibilidad != 'no_disponible' ORDER BY nombre"
    ).fetchall()
    registros_hoy = db.execute("""
        SELECT p.*, s.nombre as sabor_nombre
        FROM produccion p JOIN sabores s ON s.id=p.sabor_id
        WHERE p.fecha=? ORDER BY p.created_at DESC
    """, (hoy,)).fetchall()
    resumen_mes = db.execute("""
        SELECT s.nombre, SUM(p.cantidad) as reservas, SUM(p.cantidad)*4 as litros
        FROM produccion p JOIN sabores s ON s.id=p.sabor_id
        WHERE strftime('%Y-%m', p.fecha)=?
        GROUP BY p.sabor_id ORDER BY reservas DESC
    """, (mes_actual,)).fetchall()
    db.close()
    return render_template('produccion.html', sabores=sabores_activos, registros_hoy=registros_hoy,
                           resumen_mes=resumen_mes, hoy=hoy, mes_actual=mes_actual)

@app.route('/produccion/<int:id>/eliminar', methods=['POST'])
@admin_required
def produccion_eliminar(id):
    db = get_db()
    prod = db.execute("SELECT * FROM produccion WHERE id=?", (id,)).fetchone()
    if prod:
        db.execute("UPDATE inventario_reservas SET cantidad = MAX(0, cantidad - ?) WHERE sabor_id=?",
                   (prod['cantidad'], prod['sabor_id']))
        receta_ins = db.execute("SELECT * FROM receta_insumos WHERE sabor_id=?", (prod['sabor_id'],)).fetchall()
        for r in receta_ins:
            db.execute("UPDATE insumos SET stock_actual = stock_actual + ? WHERE id=?",
                       (r['cantidad'] if r['no_escalar'] else r['cantidad'] * prod['cantidad'], r['insumo_id']))
        receta_b = db.execute("SELECT * FROM receta_bases WHERE sabor_id=?", (prod['sabor_id'],)).fetchall()
        for r in receta_b:
            consumo_kg = r['cantidad_kg'] if r['no_escalar'] else r['cantidad_kg'] * prod['cantidad']
            db.execute("UPDATE inventario_bases SET stock_kg = stock_kg + ? WHERE base_id=?",
                       (consumo_kg, r['base_id']))
        db.execute("DELETE FROM produccion WHERE id=?", (id,))
        db.commit()
        flash('Registro eliminado y stocks revertidos', 'warning')
    db.close()
    return redirect(url_for('produccion'))

# ─────────────────────────────────────────────
# INVENTARIO
# ─────────────────────────────────────────────

@app.route('/inventario')
@admin_required
def inventario():
    db = get_db()
    reservas = db.execute("""
        SELECT s.id, s.nombre, s.disponibilidad, COALESCE(ir.cantidad, 0) as cantidad
        FROM sabores s LEFT JOIN inventario_reservas ir ON ir.sabor_id=s.id ORDER BY s.nombre
    """).fetchall()
    insumos = db.execute("""
        SELECT *, CASE WHEN stock_actual <= stock_seguridad THEN 1 ELSE 0 END as alerta
        FROM insumos ORDER BY nombre
    """).fetchall()
    bases_stock = db.execute("""
        SELECT b.id, b.nombre, b.rendimiento_kg, COALESCE(ib.stock_kg,0) as stock_kg
        FROM bases b LEFT JOIN inventario_bases ib ON ib.base_id=b.id ORDER BY b.nombre
    """).fetchall()
    db.close()
    return render_template('inventario.html', reservas=reservas, insumos=insumos, bases_stock=bases_stock)

@app.route('/inventario/ajustar', methods=['POST'])
@admin_required
def inventario_ajustar():
    sabor_id = int(request.form['sabor_id'])
    cantidad = float(request.form['cantidad'])
    db = get_db()
    db.execute("""
        INSERT INTO inventario_reservas (sabor_id, cantidad) VALUES (?,?)
        ON CONFLICT(sabor_id) DO UPDATE SET cantidad=excluded.cantidad
    """, (sabor_id, cantidad))
    db.commit(); db.close()
    actualizar_disponibilidad(sabor_id)
    flash('Inventario ajustado', 'success')
    return redirect(url_for('inventario'))

@app.route('/inventario/ajustar-insumo', methods=['POST'])
@admin_required
def inventario_ajustar_insumo():
    iid = int(request.form['insumo_id'])
    stock = float(request.form.get('stock_actual', 0) or 0)
    db = get_db()
    db.execute("UPDATE insumos SET stock_actual=? WHERE id=?", (stock, iid))
    db.commit(); db.close()
    flash('Stock actualizado', 'success')
    return redirect(url_for('inventario'))

@app.route('/inventario/ajustar-base', methods=['POST'])
@admin_required
def inventario_ajustar_base():
    bid = int(request.form['base_id'])
    stock = float(request.form.get('stock_kg', 0) or 0)
    db = get_db()
    db.execute("""
        INSERT INTO inventario_bases (base_id, stock_kg) VALUES (?,?)
        ON CONFLICT(base_id) DO UPDATE SET stock_kg=excluded.stock_kg
    """, (bid, stock))
    db.commit(); db.close()
    flash('Stock de base actualizado', 'success')
    return redirect(url_for('inventario'))

# ─────────────────────────────────────────────
# PEDIDOS (admin)
# ─────────────────────────────────────────────

@app.route('/pedidos')
@admin_required
def pedidos():
    db = get_db()
    items = db.execute("""
        SELECT pi.*, h.nombre as heladeria_nombre,
               (SELECT GROUP_CONCAT(s.nombre || ' x' || pit.cantidad, ', ')
                FROM pedido_items pit JOIN sabores s ON s.id=pit.sabor_id
                WHERE pit.pedido_id=pi.id) as resumen
        FROM pedidos_internos pi JOIN heladerias h ON h.id=pi.heladeria_id
        ORDER BY CASE pi.estado WHEN 'pendiente' THEN 0 WHEN 'en_produccion' THEN 1 ELSE 2 END,
                 pi.created_at DESC
    """).fetchall()
    heladerias = db.execute("SELECT id, nombre FROM heladerias WHERE activo=1 ORDER BY nombre").fetchall()
    db.close()
    return render_template('pedidos.html', pedidos=items, heladerias=heladerias)

@app.route('/pedidos/<int:id>')
@admin_required
def pedido_detalle(id):
    db = get_db()
    pedido = db.execute("""
        SELECT pi.*, h.nombre as heladeria_nombre
        FROM pedidos_internos pi JOIN heladerias h ON h.id=pi.heladeria_id WHERE pi.id=?
    """, (id,)).fetchone()
    items = db.execute("""
        SELECT pit.*, s.nombre as sabor_nombre, COALESCE(ir.cantidad, 0) as stock_disponible
        FROM pedido_items pit JOIN sabores s ON s.id=pit.sabor_id
        LEFT JOIN inventario_reservas ir ON ir.sabor_id=pit.sabor_id
        WHERE pit.pedido_id=?
    """, (id,)).fetchall()
    db.close()
    return render_template('pedido_detalle.html', pedido=pedido, items=items)

@app.route('/pedidos/<int:id>/estado', methods=['POST'])
@admin_required
def pedido_estado(id):
    nuevo = request.form['estado']
    db = get_db()
    if nuevo == 'entregado':
        items = db.execute("SELECT * FROM pedido_items WHERE pedido_id=?", (id,)).fetchall()
        for item in items:
            db.execute("UPDATE inventario_reservas SET cantidad = MAX(0, cantidad - ?) WHERE sabor_id=?",
                       (item['cantidad'], item['sabor_id']))
        for item in items:
            actualizar_disponibilidad(item['sabor_id'])
    db.execute("UPDATE pedidos_internos SET estado=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (nuevo, id))
    db.commit(); db.close()
    flash(f'Pedido #{id} → {nuevo.upper()}', 'success')
    return redirect(url_for('pedidos'))

@app.route('/pedidos/<int:id>/eliminar', methods=['POST'])
@admin_required
def pedido_eliminar(id):
    db = get_db()
    db.execute("DELETE FROM pedido_items WHERE pedido_id=?", (id,))
    db.execute("DELETE FROM pedidos_internos WHERE id=?", (id,))
    db.commit(); db.close()
    flash(f'Pedido #{id} eliminado.', 'warning')
    return redirect(url_for('pedidos'))

# ─────────────────────────────────────────────
# MENSAJES
# ─────────────────────────────────────────────

@app.route('/mensajes/nuevo', methods=['POST'])
@admin_required
def mensaje_nuevo():
    heladeria_id = request.form.get('heladeria_id')
    contenido = request.form.get('contenido', '').strip()
    if contenido and heladeria_id:
        db = get_db()
        db.execute("INSERT INTO mensajes (heladeria_id, contenido) VALUES (?,?)",
                   (heladeria_id, contenido))
        db.commit(); db.close()
        flash('Mensaje enviado a la heladería.', 'success')
    else:
        flash('El mensaje no puede estar vacío.', 'warning')
    return redirect(url_for('pedidos'))

@app.route('/mensajes/<int:id>/completar', methods=['POST'])
@login_required
def mensaje_completar(id):
    db = get_db()
    db.execute("UPDATE mensajes SET completado=1, completado_at=CURRENT_TIMESTAMP WHERE id=?", (id,))
    db.commit(); db.close()
    hid = session.get('heladeria_id', 1)
    return redirect(url_for('heladeria_portal', hid=hid))

# ─────────────────────────────────────────────
# VISTA HELADERÍA (cliente)
# ─────────────────────────────────────────────

@app.route('/heladeria')
@login_required
def heladeria_select():
    if session.get('rol') == 'cliente':
        return redirect(url_for('heladeria_portal', hid=session['heladeria_id']))
    db = get_db()
    heladerias = db.execute("SELECT * FROM heladerias WHERE activo=1 ORDER BY nombre").fetchall()
    db.close()
    return render_template('heladeria_select.html', heladerias=heladerias)

@app.route('/heladeria/<int:hid>')
@login_required
def heladeria_portal(hid):
    if session.get('rol') == 'cliente' and session.get('heladeria_id') != hid:
        return redirect(url_for('heladeria_portal', hid=session['heladeria_id']))
    db = get_db()
    heladeria = db.execute("SELECT * FROM heladerias WHERE id=?", (hid,)).fetchone()
    sabores = db.execute("""
        SELECT s.*, COALESCE(ir.cantidad, 0) as stock_reservas
        FROM sabores s LEFT JOIN inventario_reservas ir ON ir.sabor_id=s.id
        WHERE s.disponibilidad != 'no_disponible' ORDER BY s.nombre
    """).fetchall()
    mis_pedidos = db.execute("""
        SELECT pi.*,
               (SELECT GROUP_CONCAT(s.nombre || ' x' || pit.cantidad, ', ')
                FROM pedido_items pit JOIN sabores s ON s.id=pit.sabor_id
                WHERE pit.pedido_id=pi.id) as resumen
        FROM pedidos_internos pi WHERE pi.heladeria_id=?
        ORDER BY pi.created_at DESC LIMIT 10
    """, (hid,)).fetchall()
    mensajes = db.execute("""
        SELECT * FROM mensajes WHERE heladeria_id=? AND completado=0 ORDER BY created_at DESC
    """, (hid,)).fetchall()
    db.close()
    return render_template('heladeria_portal.html',
                           heladeria=heladeria, sabores=sabores,
                           mis_pedidos=mis_pedidos, mensajes=mensajes)

@app.route('/heladeria/<int:hid>/pedir', methods=['GET', 'POST'])
@login_required
def heladeria_pedido(hid):
    if session.get('rol') == 'cliente' and session.get('heladeria_id') != hid:
        return redirect(url_for('heladeria_portal', hid=session['heladeria_id']))
    db = get_db()
    heladeria = db.execute("SELECT * FROM heladerias WHERE id=?", (hid,)).fetchone()
    if request.method == 'POST':
        notas = request.form.get('notas', '')
        responsable = session.get('nombre') or session.get('username', '')
        sabor_ids = request.form.getlist('sabor_id[]')
        cantidades = request.form.getlist('cantidad[]')
        items_validos = [(sid, float(c)) for sid, c in zip(sabor_ids, cantidades) if c and float(c) > 0]
        if not items_validos:
            flash('Seleccioná al menos un sabor con cantidad mayor a 0.', 'warning')
            return redirect(url_for('heladeria_pedido', hid=hid))
        cur = db.execute("INSERT INTO pedidos_internos (heladeria_id, notas, responsable) VALUES (?,?,?)",
                         (hid, notas, responsable))
        pedido_id = cur.lastrowid
        for sid, cant in items_validos:
            inv = db.execute("SELECT cantidad FROM inventario_reservas WHERE sabor_id=?", (sid,)).fetchone()
            stock = inv['cantidad'] if inv else 0
            tipo = 'stock' if stock >= cant else 'bajo_pedido'
            db.execute("INSERT INTO pedido_items (pedido_id, sabor_id, cantidad, tipo_entrega) VALUES (?,?,?,?)",
                       (pedido_id, sid, cant, tipo))
        db.commit(); db.close()
        flash('Pedido enviado correctamente', 'success')
        return redirect(url_for('heladeria_portal', hid=hid))
    sabores = db.execute("""
        SELECT s.*, COALESCE(ir.cantidad, 0) as stock_reservas
        FROM sabores s LEFT JOIN inventario_reservas ir ON ir.sabor_id=s.id
        WHERE s.disponibilidad != 'no_disponible' ORDER BY s.nombre
    """).fetchall()
    db.close()
    return render_template('pedido_nuevo.html', heladeria=heladeria, sabores=sabores)

# ─────────────────────────────────────────────
# PEDIDO DE INSUMOS
# ─────────────────────────────────────────────

@app.route('/pedido-insumos', methods=['GET'])
@admin_required
def pedido_insumos():
    from itertools import groupby as igrp
    db = get_db()
    hoy = date.today()
    MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
             'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

    modo = request.args.get('modo', 'semana')
    if modo == 'mes':
        mes  = int(request.args.get('mes',  hoy.month))
        anio = int(request.args.get('anio', hoy.year))
        desde = f"{anio}-{mes:02d}-01"
        hasta = f"{anio}-{mes:02d}-31"
        periodo_label = f"{MESES[mes]} {anio}"
    else:
        hasta_dt = date.fromisoformat(request.args.get('hasta', hoy.isoformat()))
        desde_dt = date.fromisoformat(request.args.get('desde', (hoy - timedelta(days=6)).isoformat()))
        desde = desde_dt.isoformat()
        hasta = hasta_dt.isoformat()
        mes  = hoy.month
        anio = hoy.year
        periodo_label = f"{desde} al {hasta}"

    uso_rows = db.execute("""
        SELECT ri.insumo_id,
               SUM(CASE WHEN ri.no_escalar THEN ri.cantidad ELSE ri.cantidad * p.cantidad END) as usado
        FROM produccion p JOIN receta_insumos ri ON ri.sabor_id=p.sabor_id
        WHERE p.fecha BETWEEN ? AND ? GROUP BY ri.insumo_id
    """, (desde, hasta)).fetchall()
    uso = {r['insumo_id']: (r['usado'] or 0) for r in uso_rows}

    insumos = db.execute("SELECT * FROM insumos ORDER BY proveedor, nombre").fetchall()
    calculo = []
    costo_total = 0
    for ins in insumos:
        stock_act = float(ins['stock_actual'] or 0)
        stock_seg = float(ins['stock_seguridad'] or 0)
        precio    = float(ins['precio_unitario'] or 0)
        necesaria = float(uso.get(ins['id'], 0) or 0)
        a_pedir   = max(0.0, necesaria - stock_act + stock_seg)
        subtotal  = round(a_pedir * precio, 2)
        costo_total += subtotal
        calculo.append({
            'id': ins['id'],
            'nombre': ins['nombre'],
            'unidad': ins['unidad'],
            'proveedor': ins['proveedor'] or 'Sin proveedor',
            'stock_actual': stock_act,
            'stock_seguridad': stock_seg,
            'necesaria': round(necesaria, 3),
            'a_pedir': round(a_pedir, 3),
            'precio_unitario': precio,
            'subtotal': subtotal,
        })
    calculo_s = sorted(calculo, key=lambda x: x['proveedor'])
    por_proveedor = {}
    for k, g in igrp(calculo_s, key=lambda x: x['proveedor']):
        lista = list(g)
        por_proveedor[k] = {'items': lista, 'total': sum(i['subtotal'] for i in lista)}
    pedidos_hist = db.execute(
        "SELECT * FROM pedidos_insumos ORDER BY created_at DESC LIMIT 20"
    ).fetchall()
    db.close()
    return render_template('pedido_insumos.html',
                           modo=modo, mes=mes, anio=anio,
                           desde=desde, hasta=hasta,
                           periodo_label=periodo_label,
                           calculo=calculo, por_proveedor=por_proveedor,
                           costo_total=round(costo_total, 2),
                           pedidos_hist=pedidos_hist, meses=MESES,
                           hoy=hoy.isoformat())

@app.route('/pedido-insumos/confirmar', methods=['POST'])
@admin_required
def pedido_insumos_confirmar():
    mes  = int(request.form.get('mes',  date.today().month))
    anio = int(request.form.get('anio', date.today().year))
    notas = request.form.get('notas', '')
    periodo_label = request.form.get('periodo_label', '')
    items = json.loads(request.form.get('items_json', '[]'))
    cantidades_override = {}
    for k, v in request.form.items():
        if k.startswith('qty_'):
            try:
                iid = int(k[4:])
                cantidades_override[iid] = float(v or 0)
            except ValueError:
                pass
    for item in items:
        if item['id'] in cantidades_override:
            item['a_pedir'] = cantidades_override[item['id']]
            item['subtotal'] = round(item['a_pedir'] * item['precio_unitario'], 2)
    items = [i for i in items if i['a_pedir'] > 0]
    db = get_db()
    costo_total = sum(i['subtotal'] for i in items)
    cur = db.execute(
        "INSERT INTO pedidos_insumos (mes, anio, estado, costo_total, notas) VALUES (?,?,'confirmado',?,?)",
        (mes, anio, costo_total, f"{periodo_label} | {notas}".strip(' |'))
    )
    pid = cur.lastrowid
    for item in items:
        db.execute("""
            INSERT INTO pedido_insumos_items
            (pedido_insumos_id, insumo_id, cantidad_necesaria, stock_actual,
             stock_seguridad, cantidad_pedir, precio_unitario, subtotal)
            VALUES (?,?,?,?,?,?,?,?)
        """, (pid, item['id'], item['necesaria'], item['stock_actual'],
              item['stock_seguridad'], item['a_pedir'], item['precio_unitario'], item['subtotal']))
    db.commit(); db.close()
    flash('Pedido de insumos guardado', 'success')
    return redirect(url_for('pedido_insumos'))

# ─────────────────────────────────────────────
# HISTORIAL
# ─────────────────────────────────────────────

@app.route('/historial')
@admin_required
def historial():
    db = get_db()
    tab = request.args.get('tab', 'produccion')
    if tab == 'produccion':
        data = db.execute("""
            SELECT p.*, s.nombre as sabor_nombre FROM produccion p JOIN sabores s ON s.id=p.sabor_id
            ORDER BY p.fecha DESC, p.created_at DESC LIMIT 500
        """).fetchall()
    elif tab == 'pedidos':
        data = db.execute("""
            SELECT pi.*, h.nombre as heladeria_nombre,
                   (SELECT GROUP_CONCAT(s.nombre || ' x' || pit.cantidad, ', ')
                    FROM pedido_items pit JOIN sabores s ON s.id=pit.sabor_id
                    WHERE pit.pedido_id=pi.id) as resumen
            FROM pedidos_internos pi JOIN heladerias h ON h.id=pi.heladeria_id
            ORDER BY pi.created_at DESC LIMIT 500
        """).fetchall()
    elif tab == 'insumos':
        data = db.execute("SELECT * FROM pedidos_insumos ORDER BY created_at DESC LIMIT 100").fetchall()
    elif tab == 'bases':
        data = db.execute("""
            SELECT pb.*, b.nombre as base_nombre FROM produccion_bases pb JOIN bases b ON b.id=pb.base_id
            ORDER BY pb.fecha DESC, pb.created_at DESC LIMIT 500
        """).fetchall()
    else:
        data = []
    db.close()
    return render_template('historial.html', tab=tab, data=data)

# ─────────────────────────────────────────────
# GESTIÓN HELADERÍAS
# ─────────────────────────────────────────────

@app.route('/heladerias')
@superadmin_required
def heladerias():
    db = get_db()
    items = db.execute("SELECT * FROM heladerias ORDER BY nombre").fetchall()
    db.close()
    return render_template('heladerias.html', heladerias=items)

@app.route('/heladerias/nueva', methods=['POST'])
@superadmin_required
def heladeria_nueva():
    db = get_db()
    try:
        db.execute("INSERT INTO heladerias (nombre) VALUES (?)", (request.form['nombre'].strip(),))
        db.commit()
        flash('Heladería agregada', 'success')
    except Exception:
        flash('Ya existe una heladería con ese nombre', 'danger')
    db.close()
    return redirect(url_for('heladerias'))

@app.route('/heladerias/<int:id>/toggle', methods=['POST'])
@superadmin_required
def heladeria_toggle(id):
    db = get_db()
    db.execute("UPDATE heladerias SET activo = 1 - activo WHERE id=?", (id,))
    db.commit(); db.close()
    return redirect(url_for('heladerias'))

# ─────────────────────────────────────────────
# GESTIÓN DE USUARIOS
# ─────────────────────────────────────────────

@app.route('/usuarios')
@superadmin_required
def usuarios():
    db = get_db()
    users = db.execute("""
        SELECT u.*, h.nombre as heladeria_nombre
        FROM usuarios u LEFT JOIN heladerias h ON h.id=u.heladeria_id
        ORDER BY u.rol, u.username
    """).fetchall()
    heladerias = db.execute("SELECT id, nombre FROM heladerias WHERE activo=1 ORDER BY nombre").fetchall()
    db.close()
    return render_template('usuarios.html', usuarios=users, heladerias=heladerias)

@app.route('/usuarios/nuevo', methods=['POST'])
@superadmin_required
def usuario_nuevo():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    nombre   = request.form.get('nombre', '').strip()
    rol      = request.form.get('rol', 'admin')
    hel_id   = request.form.get('heladeria_id') or None
    if not username or not password:
        flash('Usuario y contraseña son obligatorios.', 'danger')
        return redirect(url_for('usuarios'))
    db = get_db()
    try:
        db.execute(
            "INSERT INTO usuarios (username, password_hash, nombre, rol, heladeria_id) VALUES (?,?,?,?,?)",
            (username, generate_password_hash(password), nombre, rol, hel_id)
        )
        db.commit()
        flash(f'Usuario {username} creado', 'success')
    except Exception:
        flash('El nombre de usuario ya existe.', 'danger')
    db.close()
    return redirect(url_for('usuarios'))

@app.route('/usuarios/<int:id>/editar', methods=['GET', 'POST'])
@superadmin_required
def usuario_editar(id):
    db = get_db()
    usuario = db.execute("SELECT * FROM usuarios WHERE id=?", (id,)).fetchone()
    heladerias = db.execute("SELECT id, nombre FROM heladerias WHERE activo=1 ORDER BY nombre").fetchall()
    if request.method == 'POST':
        nombre   = request.form.get('nombre', '').strip()
        rol      = request.form.get('rol', 'admin')
        hel_id   = request.form.get('heladeria_id') or None
        password = request.form.get('password', '')
        if password:
            db.execute("UPDATE usuarios SET nombre=?, rol=?, heladeria_id=?, password_hash=? WHERE id=?",
                       (nombre, rol, hel_id, generate_password_hash(password), id))
        else:
            db.execute("UPDATE usuarios SET nombre=?, rol=?, heladeria_id=? WHERE id=?",
                       (nombre, rol, hel_id, id))
        db.commit(); db.close()
        flash('Usuario actualizado', 'success')
        return redirect(url_for('usuarios'))
    db.close()
    return render_template('usuario_form.html', usuario=usuario, heladerias=heladerias)

@app.route('/usuarios/<int:id>/toggle', methods=['POST'])
@superadmin_required
def usuario_toggle(id):
    db = get_db()
    db.execute("UPDATE usuarios SET activo = 1 - activo WHERE id=?", (id,))
    db.commit(); db.close()
    return redirect(url_for('usuarios'))

@app.route('/usuarios/<int:id>/eliminar', methods=['POST'])
@superadmin_required
def usuario_eliminar(id):
    if id == session.get('user_id'):
        flash('No podés eliminarte a vos mismo.', 'danger')
        return redirect(url_for('usuarios'))
    db = get_db()
    db.execute("DELETE FROM usuarios WHERE id=?", (id,))
    db.commit(); db.close()
    flash('Usuario eliminado', 'warning')
    return redirect(url_for('usuarios'))

# ─────────────────────────────────────────────
# PDF GENERATION
# ─────────────────────────────────────────────

@app.route('/sabores/<int:id>/pdf')
@admin_required
def pdf_receta(id):
    from pdf_gen import pdf_receta as gen_pdf
    db = get_db()
    sabor = db.execute("SELECT * FROM sabores WHERE id=?", (id,)).fetchone()
    ingredientes = db.execute("""
        SELECT ri.*, i.nombre as insumo_nombre, i.unidad
        FROM receta_insumos ri JOIN insumos i ON i.id=ri.insumo_id
        WHERE ri.sabor_id=? ORDER BY i.nombre
    """, (id,)).fetchall()
    pasos = db.execute("SELECT * FROM proceso_pasos WHERE sabor_id=? ORDER BY orden", (id,)).fetchall()
    db.close()
    path = gen_pdf(sabor, ingredientes, pasos)
    return send_file(path, as_attachment=True, download_name=f"receta_{sabor['nombre']}.pdf")

@app.route('/pedidos/<int:id>/pdf')
@admin_required
def pdf_pedido(id):
    from pdf_gen import pdf_pedido as gen_pdf
    db = get_db()
    pedido = db.execute("""
        SELECT pi.*, h.nombre as heladeria_nombre
        FROM pedidos_internos pi JOIN heladerias h ON h.id=pi.heladeria_id WHERE pi.id=?
    """, (id,)).fetchone()
    items = db.execute("""
        SELECT pit.*, s.nombre as sabor_nombre
        FROM pedido_items pit JOIN sabores s ON s.id=pit.sabor_id WHERE pit.pedido_id=?
    """, (id,)).fetchall()
    db.close()
    path = gen_pdf(pedido, items)
    return send_file(path, as_attachment=True, download_name=f"remito_pedido_{id}.pdf")

@app.route('/pedido-insumos/<int:id>/pdf')
@admin_required
def pdf_pedido_insumos_hist(id):
    from pdf_gen import pdf_pedido_insumos as gen_pdf
    db = get_db()
    pedido = db.execute("SELECT * FROM pedidos_insumos WHERE id=?", (id,)).fetchone()
    items = db.execute("""
        SELECT pii.*, i.nombre, i.unidad, i.proveedor
        FROM pedido_insumos_items pii JOIN insumos i ON i.id=pii.insumo_id
        WHERE pii.pedido_insumos_id=? ORDER BY i.proveedor, i.nombre
    """, (id,)).fetchall()
    db.close()
    path = gen_pdf(pedido, items)
    return send_file(path, as_attachment=True, download_name=f"pedido_insumos_{id}.pdf")

# ─────────────────────────────────────────────
# STARTUP
# ─────────────────────────────────────────────

if __name__ == '__main__':
    print("\nOGGI -- Sistema de Produccion")
    print("URL:      http://127.0.0.1:5000")
    print("Usuario:  admin  |  Clave: oggi2024\n")
    threading.Timer(1.5, lambda: webbrowser.open('http://127.0.0.1:5000')).start()
    app.run(debug=False, use_reloader=False)
