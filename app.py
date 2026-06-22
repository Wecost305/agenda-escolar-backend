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
# IDs de tus Bases de Datos de Notion
DATABASE_ALUMNOS_ID = "tu_id_de_la_tabla_alumnos"  # La que ya tenías
DATABASE_ASISTENCIAS_ID = "PEGA_AQUÍ_EL_NUEVO_ID_DE_DIARIO_DE_ASISTENCIAS"

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
        if 'file' not in request.files:
            return jsonify({"error": "No se encontró ningún archivo Excel"}), 400
            
        file = request.files['file']
        df = pd.read_excel(file)
        
        for index, row in df.iterrows():
            url = "https://api.notion.com/v1/pages"
            
            # Formateamos la fecha de nacimiento para que Notion la acepte (YYYY-MM-DD)
            fecha_nac = str(row['Fecha_Nacimiento']).split(" ")[0] if pd.notna(row['Fecha_Nacimiento']) else None
            
            # Convertimos teléfono a string limpio si existe
            tel_contacto = str(int(row['Telefono'])) if pd.notna(row['Telefono']) and str(row['Telefono']).replace('.0','').isdigit() else str(row['Telefono']) if pd.notna(row['Telefono']) else None

            # Construimos el JSON con la estructura EXACTA de tu captura de Notion
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
                    "Género": {
                        "select": { "name": str(row['Genero']) }
                    },
                    "Fecha de Nacimiento": {
                        "date": { "start": fecha_nac } if fecha_nac else None
                    },
                    "Nombre del Tutor": {
                        "rich_text": [
                            { "text": { "content": str(row['Nombre_Tutor']) if pd.notna(row['Nombre_Tutor']) else "" } }
                        ]
                    },
                    "Teléfono de Contacto": {
                        "phone_number": tel_contacto if tel_contacto else None
                    },
                    "Correo Electrónico": {
                        "email": str(row['Correo']) if pd.notna(row['Correo']) else None  # Tipo Email de Notion
                    },
                    "Estatus": {
                        "select": { "name": str(row['Estatus']) } if pd.notna(row['Estatus']) else { "name": "Activo" } # Tipo Select / Status
                    },
                    "Total Faltas T1": {
                        "number": 0
                    }
                }
            }
            
            response = requests.post(url, headers=NOTION_HEADERS, json=payload)
            if response.status_code != 200:
                print(f"Error con el alumno {row['Nombre_Completo']}: {response.text}")
                
        return jsonify({"status": "éxito", "mensaje": "Alumnos cargados con estructura completa en Notion"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
# ==========================================
# 2. RUTA PARA RECIBIR EL PASE DE LISTA DESDE NETLIFY
# ==========================================
@app.route('/registrar-asistencia', methods=['POST'])
def registrar_asistencia():
    try:
        datos = request.json
        fecha = datos.get("fecha")
        alumnos_lista = datos.get("alumnos", [])

        # 1. Traemos los alumnos de Notion para mapear sus Nombres con sus IDs internos (Page IDs)
        url_query = f"https://api.notion.com/v1/databases/{DATABASE_ALUMNOS_ID}/query"
        response_query = requests.post(url_query, headers=NOTION_HEADERS)
        
        if response_query.status_code != 200:
            return jsonify({"error": "No se pudo consultar la base de datos de alumnos"}), 500
            
        resultados = response_query.json().get("results", [])
        
        # Creamos un diccionario { "Nombre Completo": "page_id_de_notion" }
        mapa_alumnos = {}
        for alum in resultados:
            props = alum.get("properties", {})
            nombre_tit = props.get("Nombre Completo", {}).get("title", [])
            if nombre_tit:
                nombre_txt = nombre_tit[0]["text"]["content"]
                mapa_alumnos[nombre_txt] = alum.get("id")

        # 2. Procesamos cada alumno enviado desde el Frontend
        for alumno in alumnos_lista:
            estatus = alumno.get("estatus")
            nombre_alumno = alumno.get("nombre")
            
            # Si el alumno está "Presente", no creamos registro de falta para no saturar la BD. 
            # Solo registramos si es "Falta" (o puedes quitar esta condición si quieres guardar también las asistencias)
            if estatus == "Falta":
                alumno_page_id = mapa_alumnos.get(nombre_alumno)
                
                if not alumno_page_id:
                    print(f"Advertencia: No se encontró el Page ID para {nombre_alumno}")
                    continue

                motivo = alumno.get("motivo", "Injustificada")
                nota = alumno.get("nota", "")

                # Armamos el Payload relacional para la BD de Diario de Asistencias
                url_crear = "https://api.notion.com/v1/pages"
                payload_asistencia = {
                    "parent": { "database_id": DATABASE_ASISTENCIAS_ID },
                    "properties": {
                        "Registro": {
                            "title": [
                                { "text": { "content": f"Falta - {fecha}" } }
                            ]
                        },
                        "Alumno": {
                            "relation": [
                                { "id": alumno_page_id }  # Aquí se hace la magia de la relación
                            ]
                        },
                        "Fecha": {
                            "date": { "start": fecha }
                        },
                        "Estatus Asistencia": {
                            "select": { "name": "Falta" }
                        },
                        "Motivo Falta": {
                            "select": { "name": motivo }
                        },
                        "Nota / Observación": {
                            "rich_text": [
                                { "text": { "content": nota } }
                            ]
                        }
                    }
                }
                
                res_crear = requests.post(url_crear, headers=NOTION_HEADERS, json=payload_asistencia)
                if res_crear.status_code != 200:
                    print(f"Error al registrar falta de {nombre_alumno}: {res_crear.text}")

        return jsonify({"status": "éxito", "mensaje": "Pase de lista relacional procesado correctamente"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==========================================
# 3. RUTA PARA JALAR ALUMOS DESDE NOTION AL FORMULARIO
# ==========================================
@app.route('/obtener-alumnos', methods=['GET'])
def obtener_alumnos():
    try:
        url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
        
        # Le pedimos a Notion que ordene los nombres alfabéticamente
        payload = {
            "sorts": [
                {
                    "property": "Nombre Completo",
                    "direction": "ascending"
                }
            ]
        }
        
        response = requests.post(url, headers=NOTION_HEADERS, json=payload)
        
        if response.status_code != 200:
            return jsonify({"error": f"Error de Notion: {response.text}"}), response.status_code
            
        data = response.json()
        nombres = []
        
        # Extraemos solo el texto limpio del nombre de cada fila
        for result in data.get("results", []):
            propiedades = result.get("properties", {})
            nombre_prop = propiedades.get("Nombre Completo", {}).get("title", [])
            if nombre_prop:
                nombres.append(nombre_prop[0]["text"]["content"])
                
        return jsonify({"alumnos": nombres}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == '__main__':
    # Render asigna el puerto automáticamente mediante la variable PORT
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
