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
            ('Insumo', 70, 'L'), ('Unid.', 18, 'C'),
            ('A pedir', 25, 'C'), ('Precio', 27, 'C'), ('Subtotal', 30, 'C')
        ])
        sub_prov = 0
        for item in grupo:
            p.td([
                (item['nombre'], 70, 'L'),
                (item['unidad'], 18, 'C'),
                (round(item['cantidad_pedir'], 2), 25, 'C'),
                (f"${item['precio_unitario']:.2f}", 27, 'C'),
                (f"${item['subtotal']:.2f}", 30, 'C'),
            ])
            sub_prov += item['subtotal']
        p.set_font('Helvetica', 'B', 9)
        p.cell(140, 6, f'Subtotal {prov}:', align='R')
        p.cell(30, 6, f'${sub_prov:.2f}', border=1, align='C')
        p.ln(8)
        grand_total += sub_prov

    p.set_font('Helvetica', 'B', 12)
    p.cell(0, 10, f'TOTAL DEL PEDIDO: ${grand_total:.2f}', align='R')
    p.ln()

    path = os.path.join(TEMP, f'hel_insumos_{pedido["id"]}.pdf')
    p.output(path)
    return path
