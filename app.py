import os
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import io
import zipfile

app = Flask(__name__)
CORS(app)

# ==========================================
# CONFIGURACIÓN DE VARIABLES DE ENTORNO
# ==========================================
NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ALUMNOS_ID = os.environ.get('NOTION_DATABASE_ID')
DATABASE_ASISTENCIAS_ID = os.environ.get('DATABASE_ASISTENCIAS_ID')
DATABASE_PROYECTOS_ID = os.environ.get('DATABASE_PROYECTOS_ID')

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

AIRTABLE_TOKEN = os.environ.get('AIRTABLE_TOKEN')
AIRTABLE_BASE_ID = os.environ.get('AIRTABLE_BASE_ID')

AIRTABLE_HEADERS = {
    "Authorization": f"Bearer {AIRTABLE_TOKEN}",
    "Content-Type": "application/json"
}

@app.route('/', methods=['GET'])
def home():
    return "Servidor de la Agenda Escolar Activo con Doble Respaldo.", 200

@app.route('/obtener-alumnos', methods=['GET'])
def obtener_alumnos():
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        payload = {"sorts": [{"property": "Nombre Completo", "direction": "ascending"}]}
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

        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        if response_query.status_code != 200:
            return jsonify({"error": "No se pudo consultar la base de alumnos"}), 500
            
        resultados = response_query.json().get("results", [])
        mapa_alumnos = {}
        for alum in resultados:
            props = alum.get("properties", {})
            nombre_tit = props.get("Nombre Completo", {}).get("title", [])
            if nombre_tit:
                mapa_alumnos[nombre_tit[0]["text"]["content"]] = alum.get("id")

        for alumno in alumnos_lista:
            estatus = alumno.get("estatus")
            nombre_alumno = alumno.get("nombre")
            motivo = alumno.get("motivo", "Ninguno") if estatus == "Falta" else "Ninguno"
            nota = alumno.get("nota", "")

            alumno_page_id = mapa_alumnos.get(nombre_alumno)
            if not alumno_page_id: continue

            # NOTION
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

            # AIRTABLE
            url_airtable = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Asistencias_Historico"
            payload_airtable = {
                "fields": {
                    "Registro": f"{estatus} - {fecha}",
                    "Alumno": nombre_alumno,
                    "Fecha": fecha,
                    "Estatus": estatus,
                    "Motivo": motivo,
                    "Nota": nota
                }
            }
            requests.post(url_airtable, headers=AIRTABLE_HEADERS, json=payload_airtable)

        return jsonify({"status": "éxito", "mensaje": "Asistencia guardada"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/registrar-calificaciones', methods=['POST'])
def registrar_calificaciones():
    try:
        datos = request.json
        proyecto = datos.get("proyecto")
        trimestre = datos.get("trimestre")
        calificaciones = datos.get("calificaciones", [])

        # Consultamos los IDs internos de los alumnos
        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        resultados = response_query.json().get("results", [])
        mapa_alumnos = {alum.get("properties", {}).get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", ""): alum.get("id") for alum in resultados}

        for calif in calificaciones:
            nombre = calif.get("nombre")
            alumno_page_id = mapa_alumnos.get(nombre)
            if not alumno_page_id: continue

            # Convertimos las notas a número si existen
            n_leng = float(calif["lenguajes"]) if calif.get("lenguajes") else None
            n_sabe = float(calif["saberes"]) if calif.get("saberes") else None
            n_etic = float(calif["etica"]) if calif.get("etica") else None
            n_huma = float(calif["humano"]) if calif.get("humano") else None
            nota = calif.get("nota", "")

            # Guardar en NOTION [BD] Registro de Proyectos
            url_notion = "https://api.notion.com/v1/pages"
            properties = {
                "Nombre del Proyecto": {"title": [{"text": {"content": proyecto}}]},
                "Alumno": {"relation": [{"id": alumno_page_id}]},
                "Periodo": {"select": {"name": trimestre}}
            }
            if n_leng is not None: properties["Lenguajes"] = {"number": n_leng}
            if n_sabe is not None: properties["Saberes y Ciencias"] = {"number": n_sabe}
            if n_etic is not None: properties["Ética, Nat y Soc"] = {"number": n_etic}
            if n_huma is not None: properties["De lo Humano y Com"] = {"number": n_huma}

            requests.post(url_notion, headers=NOTION_HEADERS, json={"parent": {"database_id": DATABASE_PROYECTOS_ID}, "properties": properties})

            # Guardar Respaldo en AIRTABLE
            url_airtable = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Proyectos_Historico"
            payload_airtable = {
                "fields": {
                    "Proyecto": proyecto,
                    "Alumno": nombre,
                    "Trimestre": trimestre,
                    "Lenguajes": n_leng,
                    "Saberes": n_sabe,
                    "Etica": n_etic,
                    "Humano": n_huma,
                    "Nota": nota
                }
            }
            requests.post(url_airtable, headers=AIRTABLE_HEADERS, json=payload_airtable)

        return jsonify({"status": "éxito", "mensaje": "Calificaciones registradas masivamente"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generar-reportes', methods=['GET'])
def generar_reportes():
    try:
        trimestre_solicitado = request.args.get('trimestre', 'Trimestre 1')

        res_alumnos = requests.post(f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query", headers=NOTION_HEADERS)
        alumnos_notion = res_alumnos.json().get("results", [])

        res_proyectos = requests.post(f"https://api.notion.com/v1/databases/{DATABASE_PROYECTOS_ID}/query", headers=NOTION_HEADERS, json={"filter": {"property": "Periodo", "select": {"equals": trimestre_solicitado}}})
        proyectos_lista = res_proyectos.json().get("results", []) if res_proyectos.status_code == 200 else []

        notas_por_alumno = {}
        for proy in proyectos_lista:
            props = proy.get("properties", {})
            relacion_alumno = props.get("Alumno", {}).get("relation", [])
            if not relacion_alumno: continue
            alumno_id = relacion_alumno[0].get("id")
            
            if alumno_id not in notas_por_alumno:
                notas_por_alumno[alumno_id] = {"L": [], "S": [], "E": [], "H": []}
                
            l_nota = props.get("Lenguajes", {}).get("number")
            s_nota = props.get("Saberes y Ciencias", {}).get("number")
            e_nota = props.get("Ética, Nat y Soc", {}).get("number")
            h_nota = props.get("De lo Humano y Com", {}).get("number")
            
            if l_nota is not None: notas_por_alumno[alumno_id]["L"].append(l_nota)
            if s_nota is not None: notas_por_alumno[alumno_id]["S"].append(s_nota)
            if e_nota is not None: notas_por_alumno[alumno_id]["E"].append(e_nota)
            if h_nota is not None: notas_por_alumno[alumno_id]["H"].append(h_nota)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for alum in alumnos_notion:
                alum_id = alum.get("id")
                nombre = alum.get("properties", {}).get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", "Alumno")
                curp = alum.get("properties", {}).get("CURP", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")
                tutor = alum.get("properties", {}).get("Nombre Tutor", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")

                registro_notas = notas_por_alumno.get(alum_id, {"L": [], "S": [], "E": [], "H": []})
                def promediar_lista(lista): return sum(lista) / len(lista) if lista else 0.0

                n1, n2, n3, n4 = promediar_lista(registro_notas["L"]), promediar_lista(registro_notas["S"]), promediar_lista(registro_notas["E"]), promediar_lista(registro_notas["H"])
                promedio_final = (n1 + n2 + n3 + n4) / 4

                pdf_buffer = io.BytesIO()
                doc = SimpleDocTemplate(pdf_buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
                story = []
                styles = getSampleStyleSheet()
                
                title_style = ParagraphStyle('TitleStyle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#0d9488'), alignment=1)
                text_style = ParagraphStyle('TextStyle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#334155'))
                bold_style = ParagraphStyle('BoldStyle', parent=styles['Normal'], fontSize=10, fontName='Helvetica-Bold', textColor=colors.HexColor('#0f172a'))
                
                story.append(Paragraph("<b>REPORTE DE EVALUACIÓN TRIMESTRAL (NEM)</b>", title_style))
                story.append(Spacer(1, 15))
                
                t_alumno = Table([[Paragraph("<b>Alumno:</b>", text_style), Paragraph(nombre, bold_style)], [Paragraph("<b>CURP:</b>", text_style), Paragraph(curp, text_style)], [Paragraph("<b>Tutor:</b>", text_style), Paragraph(tutor, text_style)]], colWidths=[100, 400])
                t_alumno.setStyle(TableStyle([('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')), ('PADDING', (0,0), (-1,-1), 5), ('LINEBELOW', (0,0), (-1,-1), 0.5, colors.HexColor('#e2e8f0'))]))
                story.append(t_alumno)
                story.append(Spacer(1, 25))
                
                t_calif = Table([[Paragraph("<b>Campo Formativo (NEM)</b>", bold_style), Paragraph("<b>Calificación Promedio</b>", bold_style)], [Paragraph("Lenguajes", text_style), Paragraph(f"{n1:.1f}", text_style)], [Paragraph("Saberes y Pensamiento Científico", text_style), Paragraph(f"{n2:.1f}", text_style)], [Paragraph("Ética, Naturaleza y Sociedades", text_style), Paragraph(f"{n3:.1f}", text_style)], [Paragraph("De lo Humano y lo Comunitario", text_style), Paragraph(f"{n4:.1f}", text_style)], [Paragraph("<b>PROMEDIO TRIMESTRAL FINAL</b>", bold_style), Paragraph(f"<b>{promedio_final:.1f}</b>", bold_style)]], colWidths=[360, 140])
                t_calif.setStyle(TableStyle([('BACKGROUND', (0,0), (1,0), colors.HexColor('#0d9488')), ('PADDING', (0,0), (-1,-1), 8), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')), ('BACKGROUND', (0,-1), (1,-1), colors.HexColor('#f0fdfa'))]))
                story.append(t_calif)
                
                doc.build(story)
                pdf_buffer.seek(0)
                zip_file.writestr(f"Boleta_{nombre.replace(' ', '_')}.pdf", pdf_buffer.getvalue())
                
        zip_buffer.seek(0)
        return send_file(zip_buffer, mimetype='application/zip', as_attachment=True, download_name=f'Boletas_{trimestre_solicitado.replace(" ", "_")}.zip')
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cargar-alumnos', methods=['POST'])
def cargar_alumnos():
    try:
        if 'file' not in request.files: return jsonify({"error": "No se encontró ningún archivo"}), 400
        file = request.files['file']
        df = pd.read_excel(file)
        for index, row in df.iterrows():
            fecha_nac = str(row['Fecha_Nacimiento']).split(" ")[0] if pd.notna(row['Fecha_Nacimiento']) else None
            tel_contacto = str(int(row['Telefono'])) if pd.notna(row['Telefono']) and str(row['Telefono']).replace('.0','').isdigit() else str(row['Telefono']) if pd.notna(row['Telefono']) else None
            payload = {"parent": {"database_id": DATABASE_ALUMNOS_ID}, "properties": {"Nombre Completo": {"title": [{"text": {"content": str(row['Nombre_Completo'])}}]}, "CURP": {"rich_text": [{"text": {"content": str(row['CURP'])}}]}, "Genero": {"select": {"name": str(row['Genero'])}}, "Fecha de Nacimiento": {"date": {"start": fecha_nac}}, "Nombre Tutor": {"rich_text": [{"text": {"content": str(row['Nombre_Tutor'])}}]}, "Teléfono de Contacto": {"phone_number": tel_contacto}, "Correo Électrónico": {"email": str(row['Correo'])}, "Estatus": {"select": {"name": "Activo"}}}}
            requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json=payload)
        return jsonify({"status": "éxito"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
