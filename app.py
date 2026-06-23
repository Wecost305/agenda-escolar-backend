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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
