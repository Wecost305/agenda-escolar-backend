import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import pandas as pd

app = Flask(__name__)
# Habilitamos CORS para que tu página de Netlify pueda enviarle datos sin bloqueos de seguridad
CORS(app)

# Configuración de Notion (Se cargan de forma segura desde las variables del servidor)
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

NOTION_HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28"
}

@app.route('/', methods=['GET'])
def home():
    return "Servidor de la Agenda Escolar 2026-2027 Activo y Corriendo.", 200

# ==========================================
# 1. RUTA PARA CARGA MASIVA DESDE EXCEL
# ==========================================
@app.route('/cargar-alumnos', methods=['POST'])
def cargar_alumnos():
    try:
        # Verificamos si viene el archivo de Excel en la petición
        if 'file' not in request.files:
            return jsonify({"error": "No se encontró ningún archivo Excel"}), 400
            
        file = request.files['file']
        df = pd.read_excel(file)
        
        # Iteramos cada fila del Excel para subirla a Notion
        for index, row in df.iterrows():
            url = "https://api.notion.com/v1/pages"
            
            # Construimos el JSON con la estructura exacta de tus columnas de Notion
            payload = {
                "parent": { "database_id": DATABASE_ID },
                "properties": {
                    "Nombre Completo": {
                        "title": [
                            { "text": { "content": str(row['Nombre_Completo']) } }
                        ]
                    },
                    "CURP": {
                        "rich_text": [
                            { "text": { "content": str(row['CURP']) } }
                        ]
                    },
                    "Total Faltas T1": {
                        "number": 0  # Iniciamos el ciclo escolar con cero faltas
                    }
                }
            }
            # Enviamos el alumno a Notion
            response = requests.post(url, headers=NOTION_HEADERS, json=payload)
            if response.status_code != 200:
                print(f"Error al subir a: {row['Nombre_Completo']}: {response.text}")
                
        return jsonify({"status": "éxito", "mensaje": "Alumnos cargados en Notion correctamente"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# 2. RUTA PARA RECIBIR EL PASE DE LISTA DESDE NETLIFY
# ==========================================
@app.route('/registrar-asistencia', methods=['POST'])
def registrar_asistencia():
    try:
        datos = request.json  # Recibe el JSON de Netlify
        fecha = datos.get("fecha")
        reporte_alumnos = datos.get("alumnos") # Lista de alumnos con su estatus y motivos
        
        for alumno in reporte_alumnos:
            nombre = alumno.get("nombre")
            estatus = alumno.get("estatus")       # "Presente" o "Falta"
            motivo = alumno.get("motivo", "")      # "Enfermedad", "Injustificada", etc.
            nota = alumno.get("nota", "")          # Comentarios del maestro
            
            # Si el alumno faltó, buscamos su registro en Notion y le sumamos 1 falta
            if estatus == "Falta":
                # Primero buscamos al alumno por nombre para obtener su ID de página de Notion
                search_url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
                search_payload = {
                    "filter": {
                        "property": "Nombre Completo",
                        "title": { "equals": nombre }
                    }
                }
                search_res = requests.post(search_url, headers=NOTION_HEADERS, json=search_payload).json()
                
                if search_res.get("results"):
                    page_id = search_res["results"][0]["id"]
                    # Leemos cuántas faltas tiene actualmente acumuladas
                    faltas_actuales = search_res["results"][0]["properties"]["Total Faltas T1"].get("number", 0) or 0
                    
                    # Actualizamos sumándole la nueva falta
                    update_url = f"https://api.notion.com/v1/pages/{page_id}"
                    update_payload = {
                        "properties": {
                            "Total Faltas T1": {
                                "number": faltas_actuales + 1
                            }
                        }
                    }
                    requests.patch(update_url, headers=NOTION_HEADERS, json=update_payload)
                    
                    # Aquí opcionalmente podemos crear un registro en otra tabla de bitácora
                    # guardando el "motivo" y la "nota" para que quede el historial detallado.
                    
        return jsonify({"status": "éxito", "mensaje": "Asistencias procesadas en Notion"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Render asigna el puerto automáticamente mediante la variable PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
