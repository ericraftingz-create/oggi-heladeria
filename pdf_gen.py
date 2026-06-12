"""PDF generation for: recetas, remitos de pedidos, pedidos de insumos."""
import os
import tempfile
from datetime import datetime
from itertools import groupby

try:
    from fpdf import FPDF
except ImportError:
    raise ImportError("Instala fpdf2: pip install fpdf2")

TEMP = tempfile.gettempdir()
MESES = ['','Enero','Febrero','Marzo','Abril','Mayo','Junio',
         'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']


class BasePDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 13)
        self.cell(0, 9, 'Heladeria', align='L')
        self.set_font('Helvetica', '', 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 9, datetime.now().strftime('%d/%m/%Y  %H:%M'), align='R')
        self.set_text_color(0, 0, 0)
        self.ln(12)

    def footer(self):
        self.set_y(-13)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(140, 140, 140)
        self.cell(0, 8, f'Pagina {self.page_no()}', align='C')

    def titulo(self, texto):
        self.set_font('Helvetica', 'B', 16)
        self.cell(0, 10, texto)
        self.ln()
        self.ln(2)

    def subtitulo(self, texto):
        self.set_font('Helvetica', 'B', 12)
        self.set_fill_color(230, 240, 255)
        self.cell(0, 8, texto, fill=True)
        self.ln()
        self.ln(1)

    def th(self, cols):
        """Table header row. cols = list of (text, width, align)"""
        self.set_font('Helvetica', 'B', 9)
        self.set_fill_color(245, 245, 245)
        for txt, w, align in cols:
            self.cell(w, 7, txt, border=1, fill=True, align=align)
        self.ln()

    def td(self, cols):
        """Table data row. cols = list of (text, width, align)"""
        self.set_font('Helvetica', '', 9)
        for txt, w, align in cols:
            self.cell(w, 6, str(txt), border=1, align=align)
        self.ln()


def pdf_receta(sabor, ingredientes, pasos):
    p = BasePDF()
    p.add_page()
    p.set_auto_page_break(True, 15)

    p.titulo(f'Receta: {sabor["nombre"]}')
    p.set_font('Helvetica', '', 10)
    p.cell(0, 6, 'Rendimiento: 1 reserva = 4 litros')
    p.ln()
    if sabor['notas']:
        p.set_text_color(80, 80, 80)
        p.multi_cell(0, 6, f'Notas: {sabor["notas"]}')
        p.set_text_color(0, 0, 0)
    p.ln(4)

    # Ingredientes
    p.subtitulo('Ingredientes por reserva')
    p.th([('Insumo', 100, 'L'), ('Cantidad', 35, 'C'), ('Unidad', 30, 'C'), ('No escala', 25, 'C')])
    for r in ingredientes:
        p.td([
            (r['insumo_nombre'], 100, 'L'),
            (r['cantidad'], 35, 'C'),
            (r['unidad'], 30, 'C'),
            ('Si' if r['no_escalar'] else '-', 25, 'C'),
        ])
    p.ln(6)

    # Proceso
    if pasos:
        p.subtitulo('Proceso de elaboracion')
        for paso in pasos:
            p.set_font('Helvetica', 'B', 10)
            p.multi_cell(0, 6, f"Paso {paso['orden']}: {paso['descripcion']}")
            p.set_font('Helvetica', '', 9)
            extras = []
            if paso['tiempo_minutos']:
                extras.append(f"Tiempo: {paso['tiempo_minutos']} min")
            if paso['temperatura_c']:
                extras.append(f"Temp: {paso['temperatura_c']} C")
            if extras:
                p.cell(0, 5, '  ' + '  |  '.join(extras))
                p.ln()
            if paso['notas']:
                p.set_text_color(100, 100, 100)
                p.multi_cell(0, 5, f"  Nota: {paso['notas']}")
                p.set_text_color(0, 0, 0)
            p.ln(3)

    path = os.path.join(TEMP, f'hel_receta_{sabor["id"]}.pdf')
    p.output(path)
    return path


def pdf_pedido(pedido, items):
    p = BasePDF()
    p.add_page()

    p.titulo(f'Remito de Pedido #{pedido["id"]}')
    p.set_font('Helvetica', '', 11)
    p.cell(0, 7, f'Heladeria: {pedido["heladeria_nombre"]}')
    p.ln()
    p.cell(0, 7, f'Estado: {pedido["estado"].upper()}')
    p.ln()
    if pedido['responsable']:
        p.cell(0, 7, f'Solicitado por: {pedido["responsable"]}')
        p.ln()
    p.cell(0, 7, f'Fecha: {str(pedido["created_at"])[:10]}')
    p.ln()
    if pedido['notas']:
        p.multi_cell(0, 7, f'Notas: {pedido["notas"]}')
    p.ln(5)

    p.th([('Sabor', 110, 'L'), ('Reservas', 40, 'C'), ('Litros', 40, 'C')])
    total_r = 0
    for item in items:
        qty = item['cantidad']
        p.td([(item['sabor_nombre'], 110, 'L'), (qty, 40, 'C'), (round(qty * 4, 2), 40, 'C')])
        total_r += qty
    p.set_font('Helvetica', 'B', 9)
    p.cell(110, 7, 'TOTAL', border=1)
    p.cell(40, 7, str(round(total_r, 2)), border=1, align='C')
    p.cell(40, 7, str(round(total_r * 4, 2)) + ' L', border=1, align='C')
    p.ln(20)

    p.set_font('Helvetica', '', 10)
    p.cell(90, 8, 'Firma Entrega: ___________________')
    p.cell(90, 8, 'Firma Recepcion: ___________________')

    path = os.path.join(TEMP, f'hel_pedido_{pedido["id"]}.pdf')
    p.output(path)
    return path


def pdf_pedido_insumos(pedido, items):
    p = BasePDF()
    p.add_page()
    p.set_auto_page_break(True, 15)

    mes_txt = MESES[pedido['mes']] if pedido['mes'] <= 12 else str(pedido['mes'])
    p.titulo(f'Pedido de Insumos - {mes_txt} {pedido["anio"]}')
    p.set_font('Helvetica', '', 10)
    p.cell(0, 6, f'Generado: {datetime.now().strftime("%d/%m/%Y")}')
    p.ln()
    if pedido['notas']:
        p.multi_cell(0, 6, f'Notas: {pedido["notas"]}')
    p.ln(4)

    items_s = sorted(items, key=lambda x: x['proveedor'] or 'ZZZ')
    grand_total = 0

    for prov, grupo in groupby(items_s, key=lambda x: x['proveedor'] or 'Sin proveedor'):
        grupo = list(grupo)
        p.subtitulo(f'Proveedor: {prov}')
        p.th([
            ('Insumo', 100, 'L'), ('Unid.', 25, 'C'), ('A pedir', 45, 'C')
        ])
        for item in grupo:
            p.td([
                (item['nombre'], 100, 'L'),
                (item['unidad'], 25, 'C'),
                (round(item['cantidad_pedir'], 2), 45, 'C'),
            ])
        p.ln(4)

    path = os.path.join(TEMP, f'hel_insumos_{pedido["id"]}.pdf')
    p.output(path)
    return path


def pdf_produccion_report(registros, label):
    """PDF report of production records. Returns bytes."""
    import io
    p = BasePDF()
    p.add_page()
    p.set_auto_page_break(True, 15)
    p.titulo(f'Reporte de Produccion')
    p.set_font('Helvetica', '', 10)
    p.set_text_color(100, 100, 100)
    p.cell(0, 6, f'Periodo: {label}', align='L')
    p.ln(10)
    p.set_text_color(0, 0, 0)
    p.th([('Fecha', 35, 'C'), ('Sabor', 85, 'L'), ('Reservas', 30, 'C'), ('Litros', 30, 'C')])
    total_r = 0; total_l = 0
    for r in registros:
        p.td([(r['fecha'], 35, 'C'), (r['sabor'], 85, 'L'),
              (r['cantidad'], 30, 'C'), (round(r['litros'], 1), 30, 'C')])
        total_r += r['cantidad']; total_l += r['litros']
    p.set_font('Helvetica', 'B', 10)
    p.cell(120, 7, 'TOTAL', border=1, align='R')
    p.cell(30, 7, str(round(total_r, 2)), border=1, align='C')
    p.cell(30, 7, str(round(total_l, 1)) + ' L', border=1, align='C')
    p.ln()
    buf = io.BytesIO(); p.output(buf); return buf.getvalue()


def pdf_etiqueta(prod, usuario, copias=1):
    """
    Etiqueta 80x60 mm para producción — cumple requisitos Seremi Chile.
    Genera `copias` páginas (una por tarro/unidad) — cada página = un corte en impresora térmica.

    Campos en prod (dict o sqlite3.Row):
      nombre / sabor_nombre   — nombre del producto
      cantidad                — tarros o kg (también determina copias si copias=None)
      tipo                    — 'reserva' | 'base'  (default: reserva)
      fecha                   — fecha elaboración  YYYY-MM-DD
      hora                    — hora elaboración   HH:MM  (default: ahora)
      fecha_vencimiento       — YYYY-MM-DD o ''
      local                   — nombre heladería destino (optional)
    """
    import io
    from datetime import datetime

    def _g(key, default=''):
        try: return prod[key] or default
        except Exception: return default

    W = 80  # page width (landscape)

    nombre       = _g('nombre') or _g('sabor_nombre')
    cantidad     = _g('cantidad', 1)
    try: cantidad = float(cantidad)
    except: cantidad = 1.0
    tipo         = (_g('tipo', 'reserva') or 'reserva').upper()
    fecha        = _g('fecha', datetime.now().strftime('%d/%m/%Y'))
    if fecha and '-' in fecha and len(fecha) == 10:
        p1, p2, p3 = fecha.split('-')
        fecha = f'{p3}/{p2}/{p1}'
    hora         = _g('hora', datetime.now().strftime('%H:%M'))
    vence        = _g('fecha_vencimiento', '')
    if vence and '-' in vence and len(vence) == 10:
        v1, v2, v3 = vence.split('-')
        vence = f'{v3}/{v2}/{v1}'
    local_dest   = _g('local', '')

    if tipo == 'RESERVA':
        neto = f'1 tarro (4 L)'
    elif tipo == 'INSUMO':
        neto = f'{cantidad} u/kg'
    else:
        neto = f'{cantidad} kg'

    # copias: cuántas etiquetas imprimir (default = cantidad, mínimo 1)
    if copias is None:
        copias = max(1, int(cantidad))
    else:
        try: copias = max(1, int(copias))
        except: copias = 1

    class EtiquetaPDF(FPDF):
        pass

    p = EtiquetaPDF(orientation='L', unit='mm', format=(60, W))
    p.set_margins(0, 0, 0)
    p.set_auto_page_break(False)

    def _draw_label():
        p.set_draw_color(0, 0, 0)
        p.set_text_color(0, 0, 0)

        # ── Borde exterior ────────────────────────────────────────
        p.rect(1, 1, W - 2, 58)

        # ── Header: oggi | TIPO | neto ────────────────────────────
        p.set_fill_color(0, 0, 0)
        p.rect(1, 1, W - 2, 10, 'F')
        p.set_text_color(255, 255, 255)
        p.set_font('Helvetica', 'B', 11)
        p.set_xy(3, 2)
        p.cell(16, 8, 'OGGI', align='L')
        p.set_font('Helvetica', 'B', 7)
        p.set_draw_color(255, 255, 255)
        p.rect(21, 3, 20, 5.5)
        p.set_xy(21, 3)
        p.cell(20, 5.5, tipo, align='C')
        p.set_draw_color(0, 0, 0)
        p.set_font('Helvetica', '', 6.5)
        p.set_xy(44, 2.5)
        p.cell(34, 7, neto, align='R')
        p.set_text_color(0, 0, 0)

        # ── Nombre del producto ───────────────────────────────────
        p.set_font('Helvetica', 'B', 18 if len(nombre) <= 16 else 13)
        p.set_xy(2, 12)
        p.cell(W - 4, 11, nombre, align='C')

        # ── Línea divisoria ───────────────────────────────────────
        p.line(1, 24, W - 1, 24)

        # ── Fecha elab + local ────────────────────────────────────
        p.set_font('Helvetica', '', 7)
        p.set_xy(3, 25)
        p.cell(38, 5, f'Elab: {fecha}  {hora}', align='L')
        if local_dest:
            p.set_xy(41, 25)
            p.cell(37, 5, f'Para: {local_dest}', align='R')

        # ── Vencimiento ───────────────────────────────────────────
        p.line(1, 31, W - 1, 31)
        if vence:
            p.set_fill_color(0, 0, 0)
            p.rect(1, 31, W - 2, 16, 'F')
            p.set_font('Helvetica', 'B', 16)
            p.set_text_color(255, 255, 255)
            p.set_xy(1, 33)
            p.cell(W - 2, 12, f'VENCE: {vence}', align='C')
            p.set_text_color(0, 0, 0)

        # ── Pie ───────────────────────────────────────────────────
        p.line(1, 53, W - 1, 53)
        p.set_font('Helvetica', '', 6)
        p.set_xy(3, 54)
        p.cell(36, 4, f'Resp: {usuario}', align='L')
        p.set_xy(39, 54)
        p.cell(39, 4, 'OGGI officina gelato gusto italiano', align='R')

    for _ in range(copias):
        p.add_page()
        _draw_label()

    buf = io.BytesIO()
    p.output(buf)
    return buf.getvalue()


def pdf_remito_termico(pedido, items):
    """
    Remito mini para impresora térmica 80mm — guía de despacho.
    Portrait, 80mm ancho, alto variable según items.
    """
    import io
    W = 72  # ancho útil dentro de los márgenes

    # Calcular alto necesario: cabecera ~40mm + 8mm por item + pie ~15mm
    n = len(items) if items else 1
    H = max(80, 45 + n * 10 + 20)

    class RemitoPDF(FPDF):
        pass

    p = RemitoPDF(orientation='P', unit='mm', format=(80, H))
    p.set_margins(4, 4, 4)
    p.set_auto_page_break(False)
    p.add_page()
    p.set_draw_color(0, 0, 0)
    p.set_text_color(0, 0, 0)

    # ── Encabezado ────────────────────────────────────────────
    p.set_fill_color(0, 0, 0)
    p.rect(0, 0, 80, 12, 'F')
    p.set_font('Helvetica', 'B', 13)
    p.set_text_color(255, 255, 255)
    p.set_xy(4, 2)
    p.cell(40, 8, 'OGGI', align='L')
    p.set_font('Helvetica', '', 7)
    p.set_xy(4, 8)
    p.cell(72, 0, 'officina gelato gusto italiano', align='L')
    p.set_text_color(0, 0, 0)

    # ── Info pedido ───────────────────────────────────────────
    y = 15
    p.set_font('Helvetica', 'B', 9)
    p.set_xy(4, y)
    p.cell(W, 5, f'DESPACHO PEDIDO #{pedido["id"]}', align='C')
    y += 6
    p.set_font('Helvetica', '', 7.5)
    p.set_xy(4, y)
    p.cell(W, 4, f'Para: {pedido["heladeria_nombre"]}', align='L')
    y += 5
    p.set_xy(4, y)
    p.cell(W, 4, f'Fecha: {datetime.now().strftime("%d/%m/%Y  %H:%M")}', align='L')
    y += 5

    # ── Línea separadora ──────────────────────────────────────
    p.line(4, y, 76, y)
    y += 2

    # ── Items ─────────────────────────────────────────────────
    p.set_font('Helvetica', 'B', 7.5)
    p.set_xy(4, y)
    p.cell(48, 5, 'PRODUCTO', border=0)
    p.cell(12, 5, 'CANT', align='C', border=0)
    p.cell(12, 5, 'OK', align='C', border=0)
    y += 5
    p.line(4, y, 76, y)
    y += 1

    p.set_font('Helvetica', '', 8)
    for item in (items or []):
        nombre = item['sabor_nombre'] or '—'
        cant = item['cantidad']
        try: unidad = item['unidad'] or 'tarro'
        except: unidad = 'tarro'
        cant_str = f"{int(cant) if float(cant) == int(cant) else cant} {unidad}"
        p.set_xy(4, y)
        # truncar nombre si es largo
        if len(nombre) > 22:
            nombre = nombre[:21] + '…'
        p.cell(48, 6, nombre)
        p.cell(12, 6, cant_str, align='C')
        # casilla de check para marcar a mano
        p.rect(68, y + 1, 5, 4)
        y += 6

    # ── Línea separadora ──────────────────────────────────────
    y += 1
    p.line(4, y, 76, y)
    y += 3

    # ── Pie ───────────────────────────────────────────────────
    p.set_font('Helvetica', '', 6.5)
    p.set_xy(4, y)
    p.cell(W, 4, 'Firma recepción: ___________________', align='L')
    y += 6
    p.set_xy(4, y)
    p.cell(W, 4, 'OGGI officina gelato gusto italiano', align='C')

    buf = io.BytesIO()
    p.output(buf)
    return buf.getvalue()


def pdf_pedido_semanal(items):
    """Returns PDF bytes for a simple weekly fresh-ingredient order."""
    import io
    p = BasePDF()
    p.add_page()
    p.set_auto_page_break(True, 15)

    fecha = datetime.now().strftime('%d/%m/%Y')
    p.set_font('Helvetica', 'B', 14)
    p.cell(0, 10, 'Pedido Semanal de Frutas / Frescos', align='C')
    p.ln(12)
    p.set_font('Helvetica', '', 10)
    p.set_text_color(100, 100, 100)
    p.cell(0, 6, f'Fecha: {fecha}', align='L')
    p.ln(10)
    p.set_text_color(0, 0, 0)

    # Table header
    p.set_fill_color(240, 240, 240)
    p.set_font('Helvetica', 'B', 10)
    p.cell(100, 8, 'Insumo', border=1, fill=True)
    p.cell(40, 8, 'Cantidad', border=1, fill=True, align='C')
    p.cell(40, 8, 'Unidad', border=1, fill=True, align='C')
    p.ln()

    p.set_font('Helvetica', '', 10)
    for item in items:
        p.cell(100, 8, item['nombre'], border=1)
        cant = item['cantidad']
        p.cell(40, 8, str(cant) if cant else '', border=1, align='C')
        p.cell(40, 8, item['unidad'], border=1, align='C')
        p.ln()

    buf = io.BytesIO()
    p.output(buf)
    return buf.getvalue()
