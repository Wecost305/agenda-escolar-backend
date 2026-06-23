import os
from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import requests
import pandas as pd
from reportlab.lib.pagesizes import letter, landscape
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
DATABASE_GRUPOS_ID = os.environ.get('DATABASE_GRUPOS_ID')  # <- NUEVA VARIABLE

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
    return "Servidor Multiescuela de la Agenda Escolar Activo.", 200

# ==========================================
# NUEVA RUTA: OBTENER LOS GRUPOS CONFIGURADOS
# ==========================================
@app.route('/obtener-grupos', methods=['GET'])
def obtener_grupos():
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_GRUPOS_ID}/query"
        response = requests.post(url, headers=NOTION_HEADERS)
        if response.status_code != 200:
            return jsonify({"error": "No se pudo leer la configuración de grupos"}), 500
            
        data = response.json()
        grupos = []
        for result in data.get("results", []):
            props = result.get("properties", {})
            codigo = props.get("Código Grupo", {}).get("title", [{}])[0].get("text", {}).get("content", "")
            escuela = props.get("Nombre de la Escuela", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            grado_grupo = props.get("Grado y Grupo", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "")
            
            if codigo:
                grupos.append({
                    "id": result.get("id"),
                    "codigo": codigo,
                    "label": f"{escuela} - {grado_grupo} ({codigo})"
                })
        return jsonify({"grupos": grupos}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# OBTENER ALUMNOS FILTRADOS POR GRUPO
# ==========================================
@app.route('/obtener-alumnos', methods=['GET'])
def obtener_alumnos():
    try:
        grupo_id = request.args.get('grupo_id')
        url = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        
        # Si mandan un grupo_id, filtramos relacionalmente en Notion
        payload = {"sorts": [{"property": "Nombre Completo", "direction": "ascending"}]}
        if grupo_id:
            payload["filter"] = {
                "property": "Grupo Relación",
                "relation": { "contains": grupo_id }
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

        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        resultados = response_query.json().get("results", [])
        mapa_alumnos = {alum.get("properties", {}).get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", ""): alum.get("id") for alum in resultados}

        for alumno in alumnos_lista:
            estatus = alumno.get("estatus")
            nombre_alumno = alumno.get("nombre")
            motivo = alumno.get("motivo", "Ninguno") if estatus == "Falta" else "Ninguno"
            nota = alumno.get("nota", "")

            alumno_page_id = mapa_alumnos.get(nombre_alumno)
            if not alumno_page_id: continue

            # NOTION
            requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json={
                "parent": { "database_id": DATABASE_ASISTENCIAS_ID },
                "properties": {
                    "Registro": {"title": [{"text": {"content": f"{estatus} - {fecha}"}}]},
                    "Alumno": {"relation": [{"id": alumno_page_id}]},
                    "Fecha": {"date": {"start": fecha}},
                    "Estatus Asistencia": {"select": {"name": estatus}},
                    "Motivo Falta": {"select": {"name": motivo}},
                    "Nota / Observación": {"rich_text": [{"text": {"content": nota}}]}
                }
            })

            # AIRTABLE
            requests.post(f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Asistencias_Historico", headers=AIRTABLE_HEADERS, json={
                "fields": {"Registro": f"{estatus} - {fecha}", "Alumno": nombre_alumno, "Fecha": fecha, "Estatus": estatus, "Motivo": motivo, "Nota": nota}
            })
        return jsonify({"status": "éxito"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/registrar-calificaciones', methods=['POST'])
def registrar_calificaciones():
    try:
        datos = request.json
        proyecto = datos.get("proyecto")
        trimestre = datos.get("trimestre")
        calificaciones = datos.get("calificaciones", [])

        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        resultados = response_query.json().get("results", [])
        mapa_alumnos = {alum.get("properties", {}).get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", ""): alum.get("id") for alum in resultados}

        for calif in calificaciones:
            nombre = calif.get("nombre")
            alumno_page_id = mapa_alumnos.get(nombre)
            if not alumno_page_id: continue

            n_leng = float(calif["lenguajes"]) if calif.get("lenguajes") else None
            n_sabe = float(calif["saberes"]) if calif.get("saberes") else None
            n_etic = float(calif["etica"]) if calif.get("etica") else None
            n_huma = float(calif["humano"]) if calif.get("humano") else None
            nota = calif.get("nota", "")

            properties = {
                "Nombre del Proyecto": {"title": [{"text": {"content": proyecto}}]},
                "Alumno": {"relation": [{"id": alumno_page_id}]},
                "Periodo": {"select": {"name": trimestre}},
                "Notas": {"rich_text": [{"text": {"content": nota}}]}
            }
            if n_leng is not None: properties["Lenguajes"] = {"number": n_leng}
            if n_sabe is not None: properties["Saberes y Ciencias"] = {"number": n_sabe}
            if n_etic is not None: properties["Ética, Nat y Soc"] = {"number": n_etic}
            if n_huma is not None: properties["De lo Humano y Com"] = {"number": n_huma}

            requests.post("https://api.notion.com/v1/pages", headers=NOTION_HEADERS, json={"parent": {"database_id": DATABASE_PROYECTOS_ID}, "properties": properties})

            # AIRTABLE
            requests.post(f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Proyectos_Historico", headers=AIRTABLE_HEADERS, json={
                "fields": {"Proyecto": proyecto, "Alumno": nombre, "Trimestre": trimestre, "Lenguajes": n_leng, "Saberes": n_sabe, "Etica": n_etic, "Humano": n_huma, "Nota": nota}
            })
        return jsonify({"status": "éxito"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/generar-reportes', methods=['GET'])
def generar_reportes():
    try:
        trimestre_solicitado = request.args.get('trimestre', 'Trimestre 1')
        grupo_id = request.args.get('grupo_id')

        if not grupo_id:
            return jsonify({"error": "Debe especificar un grupo_id"}), 400

        # 1. Traer configuración del grupo desde Notion
        url_grupo = f"https://api.notion.com/v1/pages/{grupo_id}"
        res_grupo = requests.get(url_grupo, headers=NOTION_HEADERS)
        if res_grupo.status_code != 200:
            return jsonify({"error": "No se pudo recuperar la configuración del grupo"}), 500
            
        props_grupo = res_grupo.json().get("properties", {})
        escuela_name = props_grupo.get("Nombre de la Escuela", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "ESC. PRIMARIA")
        cct_val = props_grupo.get("CCT", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")
        turno_val = props_grupo.get("Turno", {}).get("select", {}).get("name", "MATUTINO")
        grado_val = props_grupo.get("Grado y Grupo", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "1° A")

        # 2. Consultar únicamente alumnos del grupo seleccionado
        url_alumnos = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        payload_alumnos = {"filter": {"property": "Grupo Relación", "relation": {"contains": grupo_id}}}
        res_alumnos = requests.post(url_alumnos, headers=NOTION_HEADERS, json=payload_alumnos)
        alumnos_notion = res_alumnos.json().get("results", [])

        # 3. Consultar proyectos para los promedios reales
        res_proyectos = requests.post(f"https://api.notion.com/v1/databases/{DATABASE_PROYECTOS_ID}/query", headers=NOTION_HEADERS)
        proyectos_lista = res_proyectos.json().get("results", []) if res_proyectos.status_code == 200 else []

        historico_notas = {}
        for proy in proyectos_lista:
            props = proy.get("properties", {})
            relacion_alumno = props.get("Alumno", {}).get("relation", [])
            if not relacion_alumno: continue
            alum_id = relacion_alumno[0].get("id")
            periodo = props.get("Periodo", {}).get("select", {}).get("name", "Trimestre 1")
            
            if alum_id not in historico_notas:
                historico_notas[alum_id] = {
                    "Trimestre 1": {"L": [], "S": [], "E": [], "H": []},
                    "Trimestre 2": {"L": [], "S": [], "E": [], "H": []},
                    "Trimestre 3": {"L": [], "S": [], "E": [], "H": []}
                }
            if periodo in historico_notas[alum_id]:
                l_nota = props.get("Lenguajes", {}).get("number")
                s_nota = props.get("Saberes y Ciencias", {}).get("number")
                e_nota = props.get("Ética, Nat y Soc", {}).get("number")
                h_nota = props.get("De lo Humano y Com", {}).get("number")
                if l_nota is not None: historico_notas[alum_id][periodo]["L"].append(l_nota)
                if s_nota is not None: historico_notas[alum_id][periodo]["S"].append(s_nota)
                if e_nota is not None: historico_notas[alum_id][periodo]["E"].append(e_nota)
                if h_nota is not None: historico_notas[alum_id][periodo]["H"].append(h_nota)

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for alum in alumnos_notion:
                alum_id = alum.get("id")
                nombre = alum.get("properties", {}).get("Nombre Completo", {}).get("title", [{}])[0].get("text", {}).get("content", "ALUMNO")
                curp = alum.get("properties", {}).get("CURP", {}).get("rich_text", [{}])[0].get("text", {}).get("content", "N/A")

                def promediar(lista): return sum(lista) / len(lista) if lista else 0.0

                notas_alum = historico_notas.get(alum_id, {"Trimestre 1": {"L": [], "S": [], "E": [], "H": []}, "Trimestre 2": {"L": [], "S": [], "E": [], "H": []}, "Trimestre 3": {"L": [], "S": [], "E": [], "H": []}})
                
                t1_l, t1_s, t1_e, t1_h = promediar(notas_alum["Trimestre 1"]["L"]), promediar(notas_alum["Trimestre 1"]["S"]), promediar(notas_alum["Trimestre 1"]["E"]), promediar(notas_alum["Trimestre 1"]["H"])
                t2_l, t2_s, t2_e, t2_h = promediar(notas_alum["Trimestre 2"]["L"]), promediar(notas_alum["Trimestre 2"]["S"]), promediar(notas_alum["Trimestre 2"]["E"]), promediar(notas_alum["Trimestre 2"]["H"])
                t3_l, t3_s, t3_e, t3_h = promediar(notas_alum["Trimestre 3"]["L"]), promediar(notas_alum["Trimestre 3"]["S"]), promediar(notas_alum["Trimestre 3"]["E"]), promediar(notas_alum["Trimestre 3"]["H"])

                t1_prom = (t1_l + t1_s + t1_e + t1_h) / 4 if (t1_l or t1_s or t1_e or t1_h) else 0.0
                t2_prom = (t2_l + t2_s + t2_e + t2_h) / 4 if (t2_l or t2_s or t2_e or t2_h) else 0.0
                t3_prom = (t3_l + t3_s + t3_e + t3_h) / 4 if (t3_l or t3_s or t3_e or t3_h) else 0.0

                def calcular_promedio_final_campo(notas_periodos):
                    validas = [n for n in notas_periodos if n > 0]
                    return sum(validas) / len(validas) if validas else 0.0

                f_l = calcular_promedio_final_campo([t1_l, t2_l, t3_l])
                f_s = calcular_promedio_final_campo([t1_s, t2_s, t3_s])
                f_e = calcular_promedio_final_campo([t1_e, t2_e, t3_e])
                f_h = calcular_promedio_final_campo([t1_h, t2_h, t3_h])

                promedios_trimestres_validos = [p for p in [t1_prom, t2_prom, t3_prom] if p > 0]
                promedio_final_grado = sum(promedios_trimestres_validos) / len(promedios_trimestres_validos) if promedios_trimestres_validos else 0.0

                # --- REPORTE PDF HORIZONTAL (LANDSCAPE) ---
                pdf_buffer = io.BytesIO()
                doc = SimpleDocTemplate(pdf_buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=25, bottomMargin=25)
                story = []
                styles = getSampleStyleSheet()
                
                # Definición de tipografía y estilos institucionales
                style_sep_izq = ParagraphStyle('SepIzq', fontName='Helvetica-Bold', fontSize=24, textColor=colors.HexColor('#621132'))
                style_sep_sub = ParagraphStyle('SepSub', fontName='Helvetica', fontSize=7.5, textColor=colors.HexColor('#64748b'))
                
                style_sistema = ParagraphStyle('SistStyle', fontName='Helvetica-Bold', fontSize=10.5, textColor=colors.HexColor('#475569'), alignment=1, leading=14)
                
                style_edomex_der = ParagraphStyle('EdomexDer', fontName='Helvetica-Bold', fontSize=18, textColor=colors.HexColor('#334155'), alignment=2)
                style_edomex_sub = ParagraphStyle('EdomexSub', fontName='Helvetica', fontSize=6.5, textColor=colors.HexColor('#64748b'), alignment=2)
                
                style_label = ParagraphStyle('LabelStyle', fontName='Helvetica', fontSize=8, textColor=colors.HexColor('#475569'))
                style_value = ParagraphStyle('ValueStyle', fontName='Helvetica-Bold', fontSize=9, textColor=colors.black)
                style_th = ParagraphStyle('ThStyle', fontName='Helvetica-Bold', fontSize=7, textColor=colors.HexColor('#78350f'), alignment=1)
                style_td = ParagraphStyle('TdStyle', fontName='Helvetica', fontSize=9, alignment=1)
                style_td_bold = ParagraphStyle('TdBoldStyle', fontName='Helvetica-Bold', fontSize=9, alignment=1)

                # 3 COLUMNAS DEL ENCABEZADO OFICIAL
                header_data = [
                    [
                        Paragraph("Educación", style_sep_izq),
                        Paragraph("SISTEMA EDUCATIVO NACIONAL<br/><b>ESTADO DE MÉXICO</b><br/>BOLETA DE EVALUACIÓN<br/><b>" + grado_val + " DE EDUCACIÓN PRIMARIA</b><br/>CICLO ESCOLAR 2026-2027", style_sistema),
                        Paragraph("EDUCACIÓN", style_edomex_der)
                    ],
                    [
                        Paragraph("Secretaría de Educación Pública", style_sep_sub),
                        Paragraph("", style_sistema),
                        Paragraph("SECRETARÍA DE EDUCACIÓN, CIENCIA, TECNOLOGÍA E INNOVACIÓN", style_edomex_sub)
                    ]
                ]
                t_header = Table(header_data, colWidths=[200, 320, 200])
                t_header.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'TOP'),
                    ('ALIGN', (0,0), (0,1), 'LEFT'),
                    ('ALIGN', (1,0), (1,1), 'CENTER'),
                    ('ALIGN', (2,0), (2,1), 'RIGHT'),
                    ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ]))
                story.append(t_header)
                story.append(Spacer(1, 15))

                # GRID DE DATOS SIN EL PROFESOR (IGUAL AL ORIGINAL)
                datos_alumno_grid = [
                    [Paragraph("NOMBRE(S) Y APELLIDOS DE LA ALUMNA O DEL ALUMNO:", style_label), Paragraph(nombre, style_value), Paragraph("CURP:", style_label), Paragraph(curp, style_value)],
                    [Paragraph(f"NOMBRE DE LA ESCUELA: {escuela_name}", style_label), Paragraph("", style_label), Paragraph(f"CCT: {cct_val}", style_label), Paragraph(f"TURNO: {turno_val}", style_label)]
                ]
                t_alumno = Table(datos_alumno_grid, colWidths=[240, 240, 70, 170])
                t_alumno.setStyle(TableStyle([
                    ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                    ('LINEBELOW', (1,0), (1,0), 0.5, colors.black),
                    ('LINEBELOW', (3,0), (3,0), 0.5, colors.black),
                    ('SPAN', (0,1), (1,1)),
                    ('PADDING', (0,0), (-1,-1), 4)
                ]))
                story.append(t_alumno)
                story.append(Spacer(1, 15))

                matriz_data = [
                    [Paragraph("PERIODO DE EVALUACIÓN", style_th), Paragraph("CAMPOS FORMATIVOS", style_th), "", "", "", Paragraph("LENGUA INDÍGENA", style_th), ""],
                    ["", Paragraph("LENGUAJES", style_th), Paragraph("SABERES Y PENSAMIENTO CIENTÍFICO", style_th), Paragraph("ÉTICA, NATURALEZA Y SOCIEDADES", style_th), Paragraph("DE LO HUMANO Y LO COMUNITARIO", style_th), "", ""],
                    [Paragraph("1°", style_td_bold), Paragraph(f"{t1_l:.1f}" if t1_l > 0 else "-", style_td), Paragraph(f"{t1_s:.1f}" if t1_s > 0 else "-", style_td), Paragraph(f"{t1_e:.1f}" if t1_e > 0 else "-", style_td), Paragraph(f"{t1_h:.1f}" if t1_h > 0 else "-", style_td), Paragraph("PROMEDIO FINAL DE GRADO", style_th), Paragraph(f"{promedio_final_grado:.1f}" if promedio_final_grado > 0 else "-", style_td_bold)],
                    [Paragraph("2°", style_td_bold), Paragraph(f"{t2_l:.1f}" if t2_l > 0 else "-", style_td), Paragraph(f"{t2_s:.1f}" if t2_s > 0 else "-", style_td), Paragraph(f"{t2_e:.1f}" if t2_e > 0 else "-", style_td), Paragraph(f"{t2_h:.1f}" if t2_h > 0 else "-", style_td), Paragraph("ASISTENCIAS", style_th), Paragraph("190", style_td)],
                    [Paragraph("3°", style_td_bold), Paragraph(f"{t3_l:.1f}" if t3_l > 0 else "-", style_td), Paragraph(f"{t3_s:.1f}" if t3_s > 0 else "-", style_td), Paragraph(f"{t3_e:.1f}" if t3_e > 0 else "-", style_td), Paragraph(f"{t3_h:.1f}" if t3_h > 0 else "-", style_td), Paragraph("FOLIO", style_th), Paragraph("BE15251340178", style_td)],
                    [Paragraph("PROMEDIO FINAL", style_th), Paragraph(f"{f_l:.1f}" if f_l > 0 else "-", style_td_bold), Paragraph(f"{f_s:.1f}" if f_s > 0 else "-", style_td_bold), Paragraph(f"{f_e:.1f}" if f_e > 0 else "-", style_td_bold), Paragraph(f"{f_h:.1f}" if f_h > 0 else "-", style_td_bold), "", ""]
                ]
                t_matriz = Table(matriz_data, colWidths=[90, 110, 110, 110, 110, 110, 80])
                t_matriz.setStyle(TableStyle([('SPAN', (0,0), (0,1)), ('SPAN', (1,0), (4,0)), ('SPAN', (5,0), (6,1)), ('BACKGROUND', (0,0), (4,1), colors.HexColor('#fef08a')), ('BACKGROUND', (5,0), (6,1), colors.HexColor('#fde047')), ('BACKGROUND', (0,5), (4,5), colors.HexColor('#fef08a')), ('BACKGROUND', (5,2), (5,4), colors.HexColor('#fef08a')), ('BACKGROUND', (6,2), (6,2), colors.HexColor('#fde047')), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('PADDING', (0,0), (-1,-1), 6), ('GRID', (0,0), (4,5), 0.5, colors.HexColor('#94a3b8')), ('GRID', (5,2), (6,4), 0.5, colors.HexColor('#94a3b8'))]))
                story.append(t_matriz)
                story.append(Spacer(1, 15))

                t_obs = Table([[Paragraph("OBSERVACIONES Y SUGERENCIAS SOBRE LOS APRENDIZAJES", style_th)], [Paragraph("<br/><br/>", style_td)]], colWidths=[720])
                t_obs.setStyle(TableStyle([('BACKGROUND', (0,0), (0,0), colors.HexColor('#fef08a')), ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#94a3b8')), ('PADDING', (0,0), (-1,-1), 5)]))
                story.append(t_obs)

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
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
