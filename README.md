# Generador de Solicitud de Documentos — Renta Personas Naturales

Herramienta para contadores: sube el **reporte de terceros (información exógena)**
que descargas de la DIAN y la app:

1. Identifica las **entidades reportantes**.
2. Las **clasifica** (banco, empleador, fondo de pensiones, fiduciaria, cooperativa,
   aseguradora, EPS/medicina prepagada, ICETEX, comisionista, etc.).
3. Asigna el **documento que debes solicitar** a cada una.
4. Calcula el **vencimiento** con los dos últimos dígitos de la cédula.
5. Genera el **correo listo** y un **reporte profesional** por cliente.
6. Muestra una **agenda consolidada** de vencimientos de todos tus clientes.

## Archivos
- `app.py` — la aplicación.
- `requirements.txt` — dependencias.
- `reporte_ejemplo.html` — ejemplo del reporte que genera (ábrelo en el navegador).

## Cómo ejecutarla

### Opción A — Streamlit Cloud (como tus otras apps)
1. Sube `app.py` y `requirements.txt` a un repo de GitHub.
2. En https://share.streamlit.io conéctalo y despliega.

### Opción B — En tu computador
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Notas
- El calendario cargado es el **oficial DIAN 2026** para personas naturales
  AG 2025 (12 ago – 26 oct), por los dos últimos dígitos del NIT/cédula sin DV.
- Si la DIAN entrega el archivo con otro encabezado, usa el panel
  **"Revisar mapeo de columnas"** para ajustar cuál columna es el nombre, NIT,
  formato y valor.
- Documento **orientativo**: no sustituye el criterio profesional ni la revisión
  individual de cada caso.
