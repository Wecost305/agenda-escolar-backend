import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import pandas as pd

app = Flask(__name__)
CORS(app)

# ==========================================
# CONFIGURACIÓN DE VARIABLES DE ENTORNO
# ==========================================
# Variables de Notion
NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ALUMNOS_ID = os.environ.get('NOTION_DATABASE_ID')
DATABASE_ASISTENCIAS_ID = os.environ.get('DATABASE_ASISTENCIAS_ID')

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

# Variables de Airtable
AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')
AIRTABLE_TABLE_NAME = "Asistencias_Historico"  # Nombre exacto de tu tabla en Airtable

AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

@app.route('/', methods=['GET'])
def home():
    return "Servidor de la Agenda Escolar Activo y Corriendo con Respaldo en Airtable.", 200

@app.route('/obtener-alumnos', methods=['GET'])
def obtener_alumnos():
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        payload = {
            "sorts": [{"property": "Nombre Completo", "direction": "ascending"}]
        }
        response = requests.post(url, headers=NOTION_HEADERS, json=payload)
        
        if response.status_code != 200:
            return jsonify({"error": f"Error de Notion: {response.text}"}), response.status_code
            
        data = response.json()
        nombres = []
        for result in data.get("results", []):
            props = result.get("properties", {})
            nombre_prop = props.get("Nombre Completo", {}).get("title", [])
            if nombre_prop:
                nombres.append(nombre_prop[0]["text"]["content"])
                
        return jsonify({"alumnos": nombres}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/registrar-asistencia', methods=['POST'])
def registrar_asistencia():
    try:
        datos = request.json
        fecha = datos.get("fecha")
        alumnos_lista = datos.get("alumnos", [])

        # 1. Consultamos los alumnos en Notion para obtener sus IDs internos (Page IDs)
        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        if response_query.status_code != 200:
            return jsonify({"error": "No se pudo consultar la base de alumnos en Notion"}), 500
            
        resultados = response_query.json().get("results", [])
        mapa_alumnos = {}
        for alum in resultados:
            props = alum.get("properties", {})
            nombre_tit = props.get("Nombre Completo", {}).get("title", [])
            if nombre_tit:
                mapa_alumnos[nombre_tit[0]["text"]["content"]] = alum.get("id")

        # 2. Procesamos la asistencia de TODOS los alumnos
        for alumno in alumnos_lista:
            estatus = alumno.get("estatus")  # "Presente" o "Falta"
            nombre_alumno = alumno.get("nombre")
            motivo = alumno.get("motivo", "Ninguno") if estatus == "Falta" else "Ninguno"
            nota = alumno.get("nota", "")

            alumno_page_id = mapa_alumnos.get(nombre_alumno)
            if not alumno_page_id:
                continue  # Si el alumno no existe en Notion, se lo salta

            # --------------------------------------------------------
            # FLUJO A: INSERCIÓN EN NOTION (Para todos: Presentes y Faltas)
            # --------------------------------------------------------
            url_notion = "https://api.notion.com/v1/pages"
            payload_notion = {
                "parent": { "database_id": DATABASE_ASISTENCIAS_ID },
                "properties": {
                    "Registro": {"title": [{"text": {"content": f"{estatus} - {fecha}"}}]},
                    "Alumno": {"relation": [{"id": alumno_page_id}]},
                    "Fecha": {"date": {"start": fecha}},
                    "Estatus Asistencia": {"select": {"name": estatus}},
                    "Motivo Falta": {"select": {"name": motivo}},
                    "Nota / Observación": {"rich_text": [{"text": {"content": nota}}]}
                }
            }
            requests.post(url_notion, headers=NOTION_HEADERS, json=payload_notion)

            # --------------------------------------------------------
            # FLUJO B: INSERCIÓN EN AIRTABLE (RESPALDO EN PARALELO)
            # --------------------------------------------------------
            url_airtable = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/{AIRTABLE_TABLE_NAME}"
            payload_airtable = {
                "fields": {
                    "Registro": f"{estatus} - {fecha}",
                    "Alumno": nombre_alumno,  # En el respaldo guardamos el nombre directo en texto plano
                    "Fecha": fecha,
                    "Estatus": estatus,
                    "Motivo": motivo,
                    "Nota": nota
                }
            }
            # Enviamos a Airtable de forma silenciosa
            requests.post(url_airtable, headers=AIRTABLE_HEADERS, json=payload_airtable)

        return jsonify({"status": "éxito", "mensaje": "Asistencia guardada en Notion y respaldada en Airtable"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cargar-alumnos', methods=['POST'])
def cargar_alumnos():
    try:
        if 'file' not in request.files:
            return jsonify({"error": "No se encontró ningún archivo Excel"}), 400
        file = request.files['file']
        df = pd.read_excel(file)
        
        for index, row in df.iterrows():
            url = "https://api.notion.com/v1/pages"
            fecha_nac = str(row['Fecha_Nacimiento']).split(" ")[0] if pd.notna(row['Fecha_Nacimiento']) else None
            tel_contacto = str(int(row['Telefono'])) if pd.notna(row['Telefono']) and str(row['Telefono']).replace('.0','').isdigit() else str(row['Telefono']) if pd.notna(row['Telefono']) else None

            payload = {
                "parent": { "database_id": DATABASE_ALUMNOS_ID },
                "properties": {
                    "Nombre Completo": {"title": [{"text": {"content": str(row['Nombre_Completo'])}}]},
                    "CURP": {"rich_text": [{"text": {"content": str(row['CURP'])}}]},
                    "Genero": {"select": {"name": str(row['Genero'])}},
                    "Fecha de Nacimiento": {"date": {"start": fecha_nac} if fecha_nac else None},
                    "Nombre Tutor": {"rich_text": [{"text": {"content": str(row['Nombre_Tutor']) if pd.notna(row['Nombre_Tutor']) else ""}}]},
                    "Teléfono de Contacto": {"phone_number": tel_contacto if tel_contacto else None},
                    "Correo Électrónico": {"email": str(row['Correo']) if pd.notna(row['Correo']) else None},
                    "Estatus": {"select": {"name": str(row['Estatus']) if pd.notna(row['Estatus']) else "Activo"}}
                }
            }
            requests.post(url, headers=NOTION_HEADERS, json=payload)
        return jsonify({"status": "éxito", "mensaje": "Alumnos cargados"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
from flask import send_file
import zipfile

# ID de la Base de Datos de Proyectos/Calificaciones (agrégala arriba con las demás si prefieres)
DATABASE_PROYECTOS_ID = os.environ.get('DATABASE_PROYECTOS_ID')

@app.route('/generar-reportes', methods=['GET'])
def generar_reportes():
    try:
        # 1. Obtenemos el periodo que quiere el maestro (por defecto Trimestre 1)
        trimestre_solicitado = request.args.get('trimestre', 'Trimestre 1')

        # 2. Jalamos todos los alumnos para tener la lista oficial
        url_alumnos = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        res_alumnos = requests.post(url_alumnos, headers=NOTION_HEADERS)
        if res_alumnos.status_code != 200:
            return jsonify({"error": "No se pudo leer la lista de alumnos"}), 500
        alumnos_notion = res_alumnos.json().get("results", [])

        # 3. Jalamos TODOS los proyectos calificados de ese trimestre
        url_proyectos = f"https://api.notion.com/v1/databases/{DATABASE_PROYECTOS_ID}/query"
        payload_proyectos = {
            "filter": {
                "property": "Periodo",
                "select": { "equals": trimestre_solicitado }
            }
        }
        res_proyectos = requests.post(url_proyectos, headers=NOTION_HEADERS, json=payload_proyectos)
        proyectos_lista = res_proyectos.json().get("results", []) if res_proyectos.status_code == 200 else []

        # 4. Agrupamos las calificaciones por alumno en un diccionario matemático
        # Estructura: { "page_id_alumno": { "lenguajes": [], "saberes": [], "etica": [], "humano": [] } }
        notas_por_alumno = {}
        
        for proy in proyectos_lista:
            props = proy.get("properties", {})
            
            # Obtenemos la relación con el alumno (Page ID)
            relacion_alumno = props.get("Alumno", {}).get("relation", [])
            if not relacion_alumno:
                continue
            alumno_id = relacion_alumno[0].get("id")
            
            if alumno_id not in notas_por_alumno:
                notas_por_alumno[alumno_id] = {"L": [], "S": [], "E": [], "H": []}
                
            # Extraemos las notas cuidando que si están vacías cuenten como None
            l_nota = props.get("Lenguajes", {}).get("number")
            s_nota = props.get("Saberes y Ciencias", {}).get("number")
            e_nota = props.get("Ética, Nat y Soc", {}).get("number")
            h_nota = props.get("De lo Humano y Com", {}).get("number")
            
            if l_nota is not None: notas_por_alumno[alumno_id]["L"].append(l_nota)
            if s_nota is not None: notas_por_alumno[alumno_id]["S"].append(s_nota)
            if e_nota is not None: notas_por_alumno[alumno_id]["E"].append(e_nota)
            if h_nota is not None: notas_por_alumno[alumno_id]["H"].append(h_nota)

        # 5. Creamos el archivo ZIP en memoria para guardar los PDFs
        zip_buffer = io.BytesIO()
        
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            
            for alum in alumnos_notion:
                alum_id = alum.get("id")
                props_alum = alum.get("properties", {})
                nombre = props_alum.get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", "Alumno")
                curp = props_alum.get("CURP", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")
                tutor = props_alum.get("Nombre Tutor", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")

                # Calculamos promedios de los proyectos de este alumno en específico
                registro_notas = notas_por_alumno.get(alum_id, {"L": [], "S": [], "E": [], "H": []})
                
                def promediar_lista(lista):
                    return sum(lista) / len(lista) if lista else 0.0

                n1 = promediar_lista(registro_notas["L"])
                n2 = promediar_lista(registro_notas["S"])
                n3 = promediar_lista(registro_notas["E"])
                n4 = promediar_lista(registro_notas["H"])
                
                promedio_final = (n1 + n2 + n3 + n4) / 4

                # --- DISEÑO E INYECCIÓN EN REPORTE PDF (ReportLab) ---
                pdf_buffer = io.BytesIO()
                doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
                story = []
                
                styles = getSampleStyleSheet()
                title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0d9488'), alignment=1)
                text_style = ParagraphStyle('TextStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#334155'))
                bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
                
                story.append(Paragraph("<b>REPORTE DE EVALUACIÓN TRIMESTRAL (NEM)</b>", title_style))
                story.append(Spacer(1, 15))
                
                # Datos Generales
                datos_alumno = [
                    [Paragraph("<b>Alumno:</b>", text_style), Paragraph(nombre, bold_style)],
                    [Paragraph("<b>CURP:</b>", text_style), Paragraph(curp, text_style)],
                    [Paragraph("<b>Tutor:</b>", text_style), Paragraph(tutor, text_style)]
                ]
                t_alumno = Table(datos_alumno, colWidths=[100, 400])
                t_alumno.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
                    ('PADDING', (0,0), (-1,-1), 5),
                    ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0')),
                ]))
                story.append(t_alumno)
                story.append(Spacer(1, 25))
                
                # Tabla de Calificaciones por Campo Formativo
                tabla_calificaciones = [
                    [Paragraph("<b>Campo Formativo (NEM)</b>", bold_style), Paragraph("<b>Calificación Promedio</b>", bold_style)],
                    [Paragraph("Lenguajes", text_style), Paragraph(f"{n1:.1f}", text_style)],
                    [Paragraph("Saberes y Pensamiento Científico", text_style), Paragraph(f"{n2:.1f}", text_style)],
                    [Paragraph("Ética, Naturaleza y Sociedades", text_style), Paragraph(f"{n3:.1f}", text_style)],
                    [Paragraph("De lo Humano y lo Comunitario", text_style), Paragraph(f"{n4:.1f}", text_style)],
                    [Paragraph("<b>PROMEDIO TRIMESTRAL FINAL</b>", bold_style), Paragraph(f"<b>{promedio_final:.1f}</b>", bold_style)]
                ]
                t_calif = Table(tabla_calificaciones, colWidths=[360, 140])
                t_calif.setStyle(TableStyle([
                    ('BACKGROUND', (0,0), (1,0), colors.HexColor('#0d9488')),
                    ('PADDING', (0,0), (-1,-1), 8),
                    ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
                    ('BACKGROUND', (0,-1), (1,-1), colors.HexColor('#f0fdfa')),
                ]))
                story.append(t_calif)
                
                doc.build(story)
                pdf_buffer.seek(0)
                
                # Guardamos este PDF individual dentro del ZIP
                zip_file.writestr(f"Boleta_{nombre.replace(' ', '_')}.pdf", pdf_buffer.getvalue())
                
        zip_buffer.seek(0)
        return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f'Boletas_{trimestre_solicitado.replace(" ", "_")}.zip')
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
