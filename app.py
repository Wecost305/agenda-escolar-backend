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

# Variables de Entorno de Notion
NOTION_TOKEN = os.environ.get('NOTION_TOKEN')
DATABASE_ALUMNOS_ID = os.environ.get('NOTION_DATABASE_ID')
DATABASE_ASISTENCIAS_ID = os.environ.get('DATABASE_ASISTENCIAS_ID')

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.route('/', methods=['GET'])
def home():
    return "Servidor de la Agenda Escolar Activo y Corriendo.", 200

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

        # Consultamos los alumnos para obtener sus IDs internos
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
            
            if estatus == "Falta":
                alumno_page_id = mapa_alumnos.get(nombre_alumno)
                if not alumno_page_id:
                    continue

                motivo = alumno.get("motivo", "Injustificada")
                nota = alumno.get("nota", "")

                url_crear = "https://api.notion.com/v1/pages"
                payload_asistencia = {
                    "parent": { "database_id": DATABASE_ASISTENCIAS_ID },
                    "properties": {
                        "Registro": {"title": [{"text": {"content": f"Falta - {fecha}"}}]},
                        "Alumno": {"relation": [{"id": alumno_page_id}]},
                        "Fecha": {"date": {"start": fecha}},
                        "Estatus Asistencia": {"select": {"name": "Falta"}},
                        "Motivo Falta": {"select": {"name": motivo}},
                        "Nota / Observación": {"rich_text": [{"text": {"content": nota}}]}
                    }
                }
                requests.post(url_crear, headers=NOTION_HEADERS, json=payload_asistencia)

        return jsonify({"status": "éxito", "mensaje": "Asistencia registrada"}), 200
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
