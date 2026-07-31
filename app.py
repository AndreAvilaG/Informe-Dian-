# -*- coding: utf-8 -*-
"""
Generador de Solicitud de Documentos — Declaración de Renta Personas Naturales
------------------------------------------------------------------------------
Sube el reporte de terceros (información exógena) que descargas de la DIAN y la
app identifica las entidades reportantes, las clasifica, asigna el documento que
debes solicitar y arma un correo + reporte profesional listo para enviar al
cliente. La fecha de vencimiento se calcula automáticamente con los dos últimos
dígitos de la cédula.

Autoría del flujo: herramienta de apoyo para contadores. Orientativa, no sustituye
el criterio profesional ni la revisión de cada caso.
"""

import io
import re
import unicodedata
from datetime import date

import pandas as pd

# ---------------------------------------------------------------------------
# 1. CALENDARIO DE VENCIMIENTOS
# ---------------------------------------------------------------------------
# Fuente: Calendario Tributario 2026 - DIAN (art. 1.6.1.13.2.15 DUT 1625/2016,
# modificado por el Decreto 2229 de 2023). Personas naturales AG 2025,
# a presentar en 2026, según los DOS ÚLTIMOS dígitos del NIT/cédula
# (sin dígito de verificación).

MESES_ES = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
    7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre",
    12: "diciembre",
}

# (dígito_bajo, dígito_alto, mes, día) para AG 2025 (vence en 2026)
_TABLA_AG2025 = [
    (1, 2, 8, 12), (3, 4, 8, 13), (5, 6, 8, 14), (7, 8, 8, 18), (9, 10, 8, 19),
    (11, 12, 8, 20), (13, 14, 8, 21), (15, 16, 8, 24), (17, 18, 8, 25),
    (19, 20, 8, 26), (21, 22, 8, 27), (23, 24, 8, 28), (25, 26, 8, 31),
    (27, 28, 9, 1), (29, 30, 9, 2), (31, 32, 9, 3), (33, 34, 9, 4),
    (35, 36, 9, 7), (37, 38, 9, 8), (39, 40, 9, 9), (41, 42, 9, 10),
    (43, 44, 9, 11), (45, 46, 9, 14), (47, 48, 9, 15), (49, 50, 9, 16),
    (51, 52, 9, 17), (53, 54, 9, 18), (55, 56, 9, 21), (57, 58, 9, 22),
    (59, 60, 9, 23), (61, 62, 9, 24), (63, 64, 9, 25), (65, 66, 9, 28),
    (67, 68, 10, 1), (69, 70, 10, 2), (71, 72, 10, 5), (73, 74, 10, 6),
    (75, 76, 10, 7), (77, 78, 10, 8), (79, 80, 10, 9), (81, 82, 10, 13),
    (83, 84, 10, 14), (85, 86, 10, 15), (87, 88, 10, 16), (89, 90, 10, 19),
    (91, 92, 10, 20), (93, 94, 10, 21), (95, 96, 10, 22), (97, 98, 10, 23),
    (99, 0, 10, 26),
]


def _expandir_tabla(tabla, anio_vencimiento):
    """Convierte la tabla de pares en un dict {'01': date, '02': date, ...}."""
    d = {}
    for bajo, alto, mes, dia in tabla:
        fecha = date(anio_vencimiento, mes, dia)
        d[f"{bajo:02d}"] = fecha
        d[f"{alto:02d}"] = fecha
    return d


VENCIMIENTOS = {
    "2025": _expandir_tabla(_TABLA_AG2025, 2026),  # AG 2025, presenta en 2026
}


def dos_ultimos_digitos(cedula):
    """Extrae los dos últimos dígitos de la cédula (ignora puntos, guiones, DV)."""
    solo_num = re.sub(r"\D", "", str(cedula or ""))
    if not solo_num:
        return None
    return solo_num[-2:].zfill(2)


def calcular_vencimiento(cedula, anio_gravable="2025"):
    """Devuelve (fecha, texto_largo, digitos) o (None, None, None) si no aplica."""
    dd = dos_ultimos_digitos(cedula)
    tabla = VENCIMIENTOS.get(str(anio_gravable))
    if not dd or not tabla or dd not in tabla:
        return None, None, dd
    f = tabla[dd]
    texto = f"{f.day} de {MESES_ES[f.month]} de {f.year}"
    return f, texto, dd


# ---------------------------------------------------------------------------
# 2. NORMALIZACIÓN
# ---------------------------------------------------------------------------
def normalizar(texto):
    """Mayúsculas, sin tildes, sin dobles espacios — para hacer match de keywords."""
    if texto is None:
        return ""
    t = str(texto)
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii")
    t = t.upper()
    t = re.sub(r"\s+", " ", t).strip()
    return t


# ---------------------------------------------------------------------------
# 3. CATEGORÍAS Y CHECKLIST GENERAL (lista completa de la contadora)
# ---------------------------------------------------------------------------
CATEGORIAS_ORDEN = [
    "Ingresos laborales y pensiones",
    "Financiero y bancario",
    "Inversiones",
    "Patrimonio (inmuebles, vehículos y otros bienes)",
    "Deducciones",
    "Ganancias ocasionales",
    "Dependientes",
]

CHECKLIST_GENERAL = {
    "Ingresos laborales y pensiones": [
        "Certificados de ingresos y retenciones y rentas de trabajo en general del año gravable.",
        "Constancia de ingresos recibidos por concepto de pensiones.",
        "Certificados de indemnizaciones sustitutivas de la pensión o devoluciones de saldos de ahorro pensional.",
        "Certificado de pagos por concepto de alimentación efectuados por el empleador.",
        "Certificado de cesantías con saldo a 31 de diciembre.",
    ],
    "Financiero y bancario": [
        "Certificados bancarios de saldos de cuentas corrientes y de ahorros (corte 31 de diciembre).",
        "Certificados de rendimientos financieros y de GMF (4x1.000).",
        "Certificados bancarios de saldos de obligaciones financieras: créditos de consumo, tarjetas de crédito, etc.",
        "Certificado de pagos de intereses por préstamos para adquisición de vivienda.",
        "Certificado de intereses pagados sobre préstamos educativos del ICETEX.",
        "Certificados de cuentas de ahorro voluntario de pensiones y cuentas AFC.",
    ],
    "Inversiones": [
        "Certificados de inversiones (CDT, títulos valores, bonos, derechos fiduciarios, etc.) en moneda nacional o extranjera.",
        "Certificados de dividendos y participaciones en empresas, fondos de pensiones y demás entidades financieras.",
        "Certificados de fondos de empleados y cooperativas.",
    ],
    "Patrimonio (inmuebles, vehículos y otros bienes)": [
        "Impuesto predial de los inmuebles (informar valor de adiciones, remodelaciones o reparaciones, soportadas con facturas). Si no cuenta con el predial, enviar la escritura pública de adquisición de bienes nacionales o del exterior.",
        "En caso de venta de inmueble en el año: informar fecha de escrituración y valor de venta.",
        "Relación de ingresos por arrendamiento de bienes inmuebles nacionales o internacionales.",
        "Facturas de compra de vehículos (si hubo venta en el año, informar el valor de venta).",
        "Relación de muebles, enseres, maquinaria y equipo (valor promedio).",
        "Letras, pagarés, hipotecas y demás documentos que respalden cuentas por cobrar y deudas, conforme a la ley.",
    ],
    "Deducciones": [
        "Certificados de pagos de medicina prepagada o plan complementario.",
    ],
    "Ganancias ocasionales": [
        "Escritura pública que soporte ingresos recibidos por donaciones, herencias o legados.",
        "Escritura pública que soporte ingresos por gananciales y/o porción conyugal.",
        "Certificados que acrediten el pago de indemnizaciones por parte de entidades aseguradoras.",
        "Certificados que acrediten el pago de premios, rifas o loterías.",
    ],
    "Dependientes": [
        "Tipo de documento y número de identificación de los dependientes (máximo 4).",
    ],
}


# ---------------------------------------------------------------------------
# 4. MOTOR DE CLASIFICACIÓN DE ENTIDADES
# ---------------------------------------------------------------------------
# Cada regla: (lista de keywords, tipo de entidad, documento a solicitar, categoría)
# El match se hace sobre el nombre/razón social normalizado. El orden importa:
# las reglas más específicas van primero.

REGLAS_ENTIDAD = [
    # --- Medicina prepagada (antes que EPS para no confundir) ---
    (["MEDICINA PREPAGADA", "COLSANITAS", "COLMEDICA", "MEDPLUS", "COOMEVA MEDICINA"],
     "Medicina prepagada",
     "Certificado de pagos de medicina prepagada o plan complementario (deducción).",
     "Deducciones"),

    # --- ICETEX ---
    (["ICETEX"],
     "ICETEX",
     "Certificado de intereses pagados sobre el préstamo educativo (deducción).",
     "Financiero y bancario"),

    # --- Fondo Nacional del Ahorro ---
    (["FONDO NACIONAL DEL AHORRO", " FNA ", "FNA "],
     "Fondo Nacional del Ahorro",
     "Certificado de cesantías, ahorro voluntario contractual (AVC) y/o crédito de vivienda e intereses.",
     "Financiero y bancario"),

    # --- Fondos de pensiones y cesantías ---
    (["PORVENIR", "PROTECCION", "COLFONDOS", "SKANDIA", "OLD MUTUAL", "COLPENSIONES",
      "FONDO DE PENSIONES", "PENSIONES Y CESANTIAS", "FONDO DE CESANTIAS"],
     "Fondo de pensiones / cesantías",
     "Certificado de saldo de cesantías a 31 de diciembre, aportes a pensión voluntaria/AFC y/o constancia de pensión (si es pensionado).",
     "Ingresos laborales y pensiones"),

    # --- Fiduciarias ---
    (["FIDUCIARIA", "FIDUCOLOMBIA", "FIDUBOGOTA", "FIDUOCCIDENTE", "FIDUDAVIVIENDA",
      "ALIANZA FIDUCIARIA", "FIDUPREVISORA", "FIDUAGRARIA", "FIDU "],
     "Fiduciaria",
     "Certificado de derechos fiduciarios, rendimientos y saldo a 31 de diciembre.",
     "Inversiones"),

    # --- Comisionistas de bolsa / valores ---
    (["COMISIONISTA", "CASA DE BOLSA", "ACCIONES Y VALORES", "CREDICORP CAPITAL",
      "BTG PACTUAL", "VALORES BANCOLOMBIA", "CASA DE VALORES", "S.A. COMISIONISTA"],
     "Comisionista de bolsa",
     "Certificado de inversiones (acciones, bonos, títulos), rendimientos y valor a 31 de diciembre.",
     "Inversiones"),

    # --- Aseguradoras ---
    (["SEGUROS", "ASEGURADORA", "SURAMERICANA", "SEGUROS BOLIVAR", "MAPFRE", "AXA",
      "ALLIANZ", "LIBERTY SEGUROS", "SEGUROS DEL ESTADO", "SEGUROS ALFA"],
     "Aseguradora",
     "Certificado de indemnizaciones, pólizas, rentas vitalicias o seguros de pensiones/AFC si aplica.",
     "Ganancias ocasionales"),

    # --- Cooperativas y fondos de empleados ---
    (["COOPERATIVA", "FONDO DE EMPLEADOS", "COOPCENTRAL", "CONFIAR", "COTRAFA",
      "CANAPRO", "COOMEVA COOPERATIVA", "FECOL", "JURISCOOP", "COOP "],
     "Cooperativa / fondo de empleados",
     "Certificado de aportes, ahorros, saldos y obligaciones (créditos) a 31 de diciembre.",
     "Inversiones"),

    # --- EPS / Salud (normalmente sin efecto en renta, se informa) ---
    (["EPS", "SANITAS EPS", "NUEVA EPS", "SALUD TOTAL", "FAMISANAR", "COMPENSAR",
      "SURA EPS", "COOSALUD", "MUTUAL SER"],
     "EPS / Salud",
     "Revisar: por lo general no genera documento para renta (solo si hay medicina prepagada / plan complementario).",
     "Deducciones"),

    # --- Bancos (regla amplia, va después de las específicas) ---
    (["BANCOLOMBIA", "DAVIVIENDA", "BBVA", "BANCO DE BOGOTA", "BANCO DE OCCIDENTE",
      "AV VILLAS", "SCOTIABANK", "COLPATRIA", "BANCO ITAU", "BANCO FALABELLA",
      "BANCO PICHINCHA", "BANCO CAJA SOCIAL", "BANCO AGRARIO", "GNB SUDAMERIS",
      "SERFINANZA", "BANCO POPULAR", "BANCOOMEVA", "BANCAMIA", "NEQUI", "DAVIPLATA",
      "BANCO", "BANCO W"],
     "Banco / entidad financiera",
     "Certificado bancario a corte 31 de diciembre: saldos de cuentas, rendimientos, GMF (4x1.000) y, si hay créditos/tarjetas, saldo de la obligación e intereses.",
     "Financiero y bancario"),
]

# Reglas por FORMATO de exógena (refuerzan la clasificación cuando la columna existe)
REGLAS_FORMATO = {
    "2276": ("Empleador / pagador de rentas de trabajo",
             "Certificado de ingresos y retenciones (rentas de trabajo / salarios).",
             "Ingresos laborales y pensiones"),
    "2275": ("Pagador de ingresos no laborales",
             "Certificado de ingresos y retenciones por rentas no laborales.",
             "Ingresos laborales y pensiones"),
    "1001": ("Pagador (formato 1001)",
             "Certificado del pago realizado (honorarios, servicios, arrendamientos, etc.) y retención practicada.",
             "Ingresos laborales y pensiones"),
    "1007": ("Fuente de ingresos (formato 1007)",
             "Certificado de los ingresos recibidos en el año.",
             "Ingresos laborales y pensiones"),
    "1008": ("Deudor / cuenta por cobrar (formato 1008)",
             "Soporte de la cuenta por cobrar (saldo a 31 de diciembre).",
             "Patrimonio (inmuebles, vehículos y otros bienes)"),
    "1009": ("Acreedor / pasivo (formato 1009)",
             "Certificado del saldo de la deuda a 31 de diciembre.",
             "Patrimonio (inmuebles, vehículos y otros bienes)"),
    "1012": ("Inversión / saldo (formato 1012)",
             "Certificado de la inversión o saldo (cuentas, CDT, bonos, acciones, aportes) a 31 de diciembre.",
             "Inversiones"),
}


def clasificar_entidad(nombre, formato=None):
    """Devuelve (tipo, documento, categoria) para una entidad reportante."""
    n = normalizar(nombre)

    # 1) Match por nombre / razón social
    for keywords, tipo, doc, cat in REGLAS_ENTIDAD:
        for kw in keywords:
            if kw.strip() and kw.strip() in n:
                return tipo, doc, cat

    # 2) Match por formato de exógena
    if formato is not None:
        fmt = re.sub(r"\D", "", str(formato))
        if fmt in REGLAS_FORMATO:
            return REGLAS_FORMATO[fmt]

    # 3) Sin match: entidad genérica
    return ("Otra entidad reportante",
            "Solicitar el certificado correspondiente al año gravable y verificar a qué concepto aplica.",
            "Financiero y bancario")


# ---------------------------------------------------------------------------
# 5. LECTURA DEL ARCHIVO DE LA DIAN
# ---------------------------------------------------------------------------
# Palabras clave "fuertes" (identifican con confianza cada columna). Se resuelven
# primero el NIT, formato, concepto y valor; el nombre se resuelve al final para
# evitar que una columna "NIT Informante" sea tomada como la del nombre.
STRONG = {
    "nit": ["nit informante", "numero de identificacion", "no. identificacion",
            "identificacion", "documento", "nit"],
    "formato": ["numero formato", "no. formato", "formato"],
    "concepto": ["codigo concepto", "concepto"],
    "valor": ["valor reportado", "cuantia reportada", "valor", "cuantia",
              "monto", "pago"],
    "nombre": ["apellidos y nombres o razon social", "nombre o razon social",
               "razon social", "nombre", "razon"],
}
# Palabras clave "débiles" para el nombre (solo si no hubo match fuerte)
WEAK_NOMBRE = ["informante", "tercero", "nombres"]
ROLES = ["nit", "formato", "concepto", "valor", "nombre"]

# Lista plana para detectar la fila de encabezado
_TODAS_KEYS = [kw for lst in STRONG.values() for kw in lst] + WEAK_NOMBRE


def _match_kw(ncol, keyword):
    """3 = igual, 2 = palabra completa, 1 = subcadena, 0 = no."""
    if ncol == keyword:
        return 3
    if re.search(r"\b" + re.escape(keyword) + r"\b", ncol):
        return 2
    if keyword in ncol:
        return 1
    return 0


def _leer_dataframe_crudo(file_bytes, filename):
    """Lee xlsx/xls/csv en un DataFrame sin asumir la fila de encabezado."""
    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(io.BytesIO(file_bytes), header=None, dtype=str)
    # CSV (probar separadores comunes)
    for sep in [";", ",", "\t", "|"]:
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str, sep=sep)
            if df.shape[1] > 1:
                return df
        except Exception:
            continue
    return pd.read_csv(io.BytesIO(file_bytes), header=None, dtype=str)


def _detectar_fila_encabezado(df_crudo, max_filas=20):
    """Busca la fila que parece ser el encabezado (contiene nombres reconocibles)."""
    mejor_fila, mejor_score = 0, -1
    for i in range(min(max_filas, len(df_crudo))):
        celdas = [normalizar(c).lower() for c in df_crudo.iloc[i].tolist()]
        score = sum(1 for celda in celdas for kw in _TODAS_KEYS if kw in celda)
        if score > mejor_score:
            mejor_score, mejor_fila = score, i
    return mejor_fila if mejor_score > 0 else 0


def _mapear_columnas(columnas):
    """Mapea columnas reales a roles. Resuelve NIT/formato/concepto/valor antes
    que el nombre, y usa palabras débiles para el nombre solo como último recurso."""
    norm = {col: normalizar(col).lower() for col in columnas}
    mapping, usadas = {}, set()

    # Fase 1: match fuerte, en orden de roles (nit primero, nombre al final)
    for rol in ROLES:
        candidatos = []
        for col, ncol in norm.items():
            if col in usadas:
                continue
            best = max((_match_kw(ncol, k) for k in STRONG[rol]), default=0)
            if best > 0:
                candidatos.append((best, col))
        if candidatos:
            candidatos.sort(key=lambda x: -x[0])
            mapping[rol] = candidatos[0][1]
            usadas.add(candidatos[0][1])

    # Fase 2: nombre por palabras débiles si aún no se asignó
    if "nombre" not in mapping:
        for col, ncol in norm.items():
            if col in usadas:
                continue
            if any(_match_kw(ncol, k) > 0 for k in WEAK_NOMBRE):
                mapping["nombre"] = col
                usadas.add(col)
                break
    return mapping


def leer_reporte_dian(file_bytes, filename):
    """
    Devuelve (df_limpio, mapping, df_crudo).
    df_limpio tiene el encabezado detectado aplicado.
    mapping indica qué columna cumple cada rol.
    """
    crudo = _leer_dataframe_crudo(file_bytes, filename)
    fila_h = _detectar_fila_encabezado(crudo)
    encabezado = [str(c).strip() if pd.notna(c) else f"col_{j}"
                  for j, c in enumerate(crudo.iloc[fila_h].tolist())]
    df = crudo.iloc[fila_h + 1:].copy()
    df.columns = encabezado
    df = df.dropna(how="all").reset_index(drop=True)
    mapping = _mapear_columnas(list(df.columns))
    return df, mapping, crudo


# ---------------------------------------------------------------------------
# 6. CONSTRUCCIÓN DEL RESUMEN DE ENTIDADES
# ---------------------------------------------------------------------------
def construir_resumen(df, mapping):
    """Agrupa por entidad y clasifica. Devuelve un DataFrame ordenado."""
    col_nombre = mapping.get("nombre")
    col_formato = mapping.get("formato")
    col_valor = mapping.get("valor")

    if not col_nombre:
        return pd.DataFrame(columns=["Entidad", "Tipo", "Documento a solicitar",
                                     "Categoría", "Valor reportado"])

    filas = []
    for _, r in df.iterrows():
        nombre = r.get(col_nombre)
        if nombre is None or normalizar(nombre) == "":
            continue
        formato = r.get(col_formato) if col_formato else None
        valor = r.get(col_valor) if col_valor else None
        tipo, doc, cat = clasificar_entidad(nombre, formato)
        filas.append({
            "Entidad": str(nombre).strip(),
            "Tipo": tipo,
            "Documento a solicitar": doc,
            "Categoría": cat,
            "_valor_raw": valor,
        })

    if not filas:
        return pd.DataFrame(columns=["Entidad", "Tipo", "Documento a solicitar",
                                     "Categoría", "Valor reportado"])

    res = pd.DataFrame(filas)

    # Consolidar valores por entidad (suma si son numéricos)
    def _to_num(x):
        try:
            return float(re.sub(r"[^\d,.-]", "", str(x)).replace(".", "").replace(",", "."))
        except Exception:
            return None

    res["_valor_num"] = res["_valor_raw"].map(_to_num)
    agg = (res.groupby(["Entidad", "Tipo", "Documento a solicitar", "Categoría"],
                       as_index=False)
              .agg(_valor_num=("_valor_num", "sum")))

    def _fmt_valor(v):
        if v is None or pd.isna(v) or v == 0:
            return ""
        return "$ {:,.0f}".format(v).replace(",", ".")

    agg["Valor reportado"] = agg["_valor_num"].map(_fmt_valor)
    agg = agg.drop(columns=["_valor_num"])

    orden_cat = {c: i for i, c in enumerate(CATEGORIAS_ORDEN)}
    agg["_ord"] = agg["Categoría"].map(lambda c: orden_cat.get(c, 99))
    agg = agg.sort_values(["_ord", "Entidad"]).drop(columns=["_ord"]).reset_index(drop=True)
    return agg


# ---------------------------------------------------------------------------
# 7. GENERACIÓN DEL CORREO
# ---------------------------------------------------------------------------
def generar_correo(cliente, cedula, anio_gravable, resumen, firma,
                   incluir_general=True):
    _, fecha_texto, dd = calcular_vencimiento(cedula, anio_gravable)
    anio_soporte = int(anio_gravable)  # los soportes son del año gravable

    lineas = [f"Cordial saludo, {cliente or '[nombre del cliente]'}:", ""]

    if fecha_texto:
        lineas.append(
            f"De acuerdo con lo conversado, te comparto el listado de documentos "
            f"necesarios para la elaboración de tu declaración de renta correspondiente "
            f"al año gravable {anio_soporte}. Según los dos últimos dígitos de tu cédula "
            f"({dd}), tu fecha máxima de presentación y pago es el {fecha_texto}. "
            f"Te recomiendo no dejarlo para el último día, para evitar congestión en el "
            f"portal de la DIAN e inconvenientes de última hora."
        )
    else:
        lineas.append(
            f"De acuerdo con lo conversado, te comparto el listado de documentos "
            f"necesarios para la elaboración de tu declaración de renta correspondiente "
            f"al año gravable {anio_soporte}. (Verifica los dos últimos dígitos de tu "
            f"cédula en el RUT para confirmar tu fecha exacta de vencimiento.)"
        )

    lineas += [
        "",
        "Es muy importante revisar detenidamente qué documentos aplican en tu caso y "
        "descartar lo que no corresponda, para no omitir información relevante. Ten "
        "presente que no podemos basarnos únicamente en el reporte que emite la DIAN; "
        "es fundamental que como contribuyente tengas claridad de todos tus activos e "
        "ingresos, y así evitar posibles sanciones.",
        "",
        f"Recuerda que los soportes solicitados deben corresponder al año {anio_soporte}. "
        f"En el caso de los certificados bancarios y similares, estos deben estar emitidos "
        f"con fecha de corte 31 de diciembre de {anio_soporte}.",
        "",
    ]

    # Bloque personalizado: entidades que te reportaron
    if resumen is not None and len(resumen) > 0:
        lineas.append("── ENTIDADES QUE TE REPORTARON ANTE LA DIAN ──")
        lineas.append("(Documentos que debes solicitar a cada una)")
        lineas.append("")
        for cat in CATEGORIAS_ORDEN:
            sub = resumen[resumen["Categoría"] == cat]
            if len(sub) == 0:
                continue
            lineas.append(f"• {cat}:")
            for _, r in sub.iterrows():
                val = f"  [reportado: {r['Valor reportado']}]" if r.get("Valor reportado") else ""
                lineas.append(f"   - {r['Entidad']} ({r['Tipo']}): {r['Documento a solicitar']}{val}")
            lineas.append("")

    # Bloque general (checklist completo)
    if incluir_general:
        lineas.append("── DOCUMENTOS GENERALES A REVISAR ──")
        lineas.append("(Marca los que apliquen a tu caso)")
        lineas.append("")
        for cat in CATEGORIAS_ORDEN:
            items = CHECKLIST_GENERAL.get(cat, [])
            if not items:
                continue
            lineas.append(f"• {cat}:")
            for it in items:
                lineas.append(f"   [ ] {it}")
            lineas.append("")

    lineas += [
        "Quedo atenta a cualquier duda y con gusto te acompaño en el proceso.",
        "",
        "Cordialmente,",
        firma or "[Tu nombre]",
    ]
    return "\n".join(lineas)


def generar_asunto(cliente, cedula, anio_gravable):
    _, fecha_texto, _ = calcular_vencimiento(cedula, anio_gravable)
    base = f"Documentos declaración de renta AG {anio_gravable}"
    if cliente:
        base += f" — {cliente}"
    if fecha_texto:
        base += f" (vence {fecha_texto})"
    return base


# ---------------------------------------------------------------------------
# 8. REPORTE HTML PROFESIONAL (imprimible a PDF)
# ---------------------------------------------------------------------------
def generar_html(cliente, cedula, anio_gravable, resumen, firma, color="#1F4E5F"):
    _, fecha_texto, dd = calcular_vencimiento(cedula, anio_gravable)
    hoy = date.today()
    dias = None
    fecha_v, _, _ = calcular_vencimiento(cedula, anio_gravable)
    if fecha_v:
        dias = (fecha_v - hoy).days

    def esc(x):
        return (str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    # Tabla de entidades por categoría
    bloques_ent = ""
    if resumen is not None and len(resumen) > 0:
        for cat in CATEGORIAS_ORDEN:
            sub = resumen[resumen["Categoría"] == cat]
            if len(sub) == 0:
                continue
            filas = ""
            for _, r in sub.iterrows():
                val = esc(r["Valor reportado"]) if r.get("Valor reportado") else "—"
                filas += (
                    f"<tr><td>{esc(r['Entidad'])}</td>"
                    f"<td>{esc(r['Tipo'])}</td>"
                    f"<td>{esc(r['Documento a solicitar'])}</td>"
                    f"<td class='num'>{val}</td></tr>"
                )
            bloques_ent += f"""
            <h3>{esc(cat)}</h3>
            <table class="tbl">
              <thead><tr><th>Entidad</th><th>Tipo</th><th>Documento a solicitar</th><th>Valor reportado</th></tr></thead>
              <tbody>{filas}</tbody>
            </table>"""
    else:
        bloques_ent = "<p class='muted'>No se identificaron entidades en el reporte (revisa el mapeo de columnas).</p>"

    # Checklist general
    bloques_chk = ""
    for cat in CATEGORIAS_ORDEN:
        items = CHECKLIST_GENERAL.get(cat, [])
        if not items:
            continue
        lis = "".join(f"<li><span class='box'></span>{esc(it)}</li>" for it in items)
        bloques_chk += f"<h3>{esc(cat)}</h3><ul class='chk'>{lis}</ul>"

    venc_html = ""
    if fecha_texto:
        urg = ""
        if dias is not None:
            clase = "ok" if dias > 30 else ("warn" if dias > 10 else "danger")
            urg = f"<span class='pill {clase}'>Faltan {dias} días</span>"
        venc_html = f"""
        <div class="venc">
          <div><span class="lbl">Fecha máxima de presentación y pago</span>
               <span class="big">{esc(fecha_texto)}</span></div>
          <div><span class="lbl">Dígitos de cédula</span><span class="big">{esc(dd)}</span> {urg}</div>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="utf-8">
<title>Solicitud de documentos — {esc(cliente)}</title>
<style>
  :root {{ --brand: {color}; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif;
         color:#1a2b32; margin:0; padding:0; background:#f4f6f7; }}
  .page {{ max-width: 820px; margin: 24px auto; background:#fff;
           box-shadow:0 2px 18px rgba(0,0,0,.08); border-radius:12px; overflow:hidden; }}
  .hd {{ background:var(--brand); color:#fff; padding:28px 36px; }}
  .hd h1 {{ margin:0; font-size:20px; letter-spacing:.3px; }}
  .hd p {{ margin:6px 0 0; opacity:.9; font-size:13px; }}
  .body {{ padding: 28px 36px; }}
  .meta {{ display:flex; gap:24px; flex-wrap:wrap; font-size:13px; color:#3a4b52;
           border-bottom:1px solid #eee; padding-bottom:16px; margin-bottom:20px; }}
  .meta b {{ color:#1a2b32; }}
  .venc {{ display:flex; gap:32px; flex-wrap:wrap; background:#f0f7f9;
           border-left:4px solid var(--brand); padding:16px 20px; border-radius:8px;
           margin: 8px 0 22px; }}
  .venc .lbl {{ display:block; font-size:11px; text-transform:uppercase;
                letter-spacing:.5px; color:#6b7a80; }}
  .venc .big {{ font-size:18px; font-weight:700; color:var(--brand); }}
  .pill {{ font-size:11px; padding:3px 10px; border-radius:20px; font-weight:600; margin-left:8px; }}
  .pill.ok {{ background:#e2f4e6; color:#1c7a34; }}
  .pill.warn {{ background:#fdf0d5; color:#9a6b00; }}
  .pill.danger {{ background:#fce0e0; color:#b02020; }}
  h2 {{ font-size:15px; color:var(--brand); border-bottom:2px solid var(--brand);
        padding-bottom:6px; margin-top:28px; }}
  h3 {{ font-size:13px; color:#2a3b42; margin:18px 0 8px; }}
  table.tbl {{ width:100%; border-collapse:collapse; font-size:12px; margin-bottom:8px; }}
  .tbl th {{ background:#eef3f4; text-align:left; padding:8px 10px; font-weight:600;
             border-bottom:2px solid #dde5e7; }}
  .tbl td {{ padding:8px 10px; border-bottom:1px solid #eef2f3; vertical-align:top; }}
  .tbl td.num {{ text-align:right; white-space:nowrap; color:#3a4b52; }}
  ul.chk {{ list-style:none; padding:0; margin:0 0 8px; }}
  ul.chk li {{ font-size:12px; padding:5px 0; display:flex; gap:9px; align-items:flex-start; }}
  .box {{ width:13px; height:13px; border:1.5px solid var(--brand); border-radius:3px;
          flex:0 0 auto; margin-top:1px; }}
  .muted {{ color:#8a999f; font-size:12px; }}
  .note {{ background:#fff8e6; border:1px solid #f0dca0; border-radius:8px;
           padding:12px 16px; font-size:12px; color:#6b5a2a; margin:20px 0; }}
  .ft {{ padding:18px 36px; border-top:1px solid #eee; font-size:11px; color:#8a999f; }}
  @media print {{ body {{ background:#fff; }} .page {{ box-shadow:none; margin:0; }} }}
</style></head>
<body><div class="page">
  <div class="hd">
    <h1>Solicitud de documentos — Declaración de Renta {esc(anio_gravable)}</h1>
    <p>Persona natural · Documento orientativo de preparación</p>
  </div>
  <div class="body">
    <div class="meta">
      <span><b>Cliente:</b> {esc(cliente) or '—'}</span>
      <span><b>Cédula:</b> {esc(cedula) or '—'}</span>
      <span><b>Año gravable:</b> {esc(anio_gravable)}</span>
      <span><b>Fecha de elaboración:</b> {hoy.day} de {MESES_ES[hoy.month]} de {hoy.year}</span>
    </div>
    {venc_html}

    <h2>1. Entidades que te reportaron ante la DIAN</h2>
    <p class="muted">Documentos que debes solicitar a cada entidad, según la información de terceros.</p>
    {bloques_ent}

    <h2>2. Documentos generales a revisar</h2>
    <p class="muted">Marca únicamente los que apliquen a tu caso.</p>
    {bloques_chk}

    <div class="note">
      <b>Importante:</b> este listado es orientativo. No podemos basarnos únicamente en el
      reporte de la DIAN; como contribuyente debes tener claridad de todos tus activos e
      ingresos para evitar sanciones. Los soportes deben corresponder al año {esc(anio_gravable)}
      y los certificados bancarios deben tener corte a 31 de diciembre de {esc(anio_gravable)}.
    </div>
  </div>
  <div class="ft">
    Elaborado por {esc(firma) or '[Tu nombre]'} · Herramienta de apoyo — no sustituye el criterio profesional ni la revisión individual de cada caso.
  </div>
</div></body></html>"""


# ---------------------------------------------------------------------------
# 9. INTERFAZ STREAMLIT
# ---------------------------------------------------------------------------
def main():
    import streamlit as st

    st.set_page_config(page_title="Solicitud Documentos Renta", page_icon="📄",
                       layout="wide")

    st.title("📄 Generador de Solicitud de Documentos — Renta Personas Naturales")
    st.caption("Sube el reporte de terceros de la DIAN → identifica entidades, "
               "asigna documentos y arma el correo + reporte por cliente.")

    with st.sidebar:
        st.header("⚙️ Configuración")
        anio = st.selectbox("Año gravable", ["2025"], index=0,
                            help="AG 2025 se presenta en 2026 (12 ago – 26 oct).")
        firma = st.text_input("Tu nombre / firma", value="")
        color = st.color_picker("Color del reporte", value="#1F4E5F")
        incluir_general = st.checkbox("Incluir checklist general en el correo",
                                      value=True)
        st.divider()
        st.markdown("**¿Cómo se usa?**\n\n1. Configura año y firma.\n"
                    "2. Sube uno o varios reportes de la DIAN (uno por cliente).\n"
                    "3. Escribe nombre y cédula de cada cliente.\n"
                    "4. Copia el correo y descarga el reporte.")

    archivos = st.file_uploader(
        "Sube el / los reporte(s) de terceros de la DIAN (Excel o CSV)",
        type=["xlsx", "xls", "csv"], accept_multiple_files=True)

    if not archivos:
        st.info("👆 Sube al menos un archivo para empezar. "
                "Cada archivo corresponde a un cliente.")
        return

    agenda = []  # para la vista consolidada

    for idx, archivo in enumerate(archivos):
        st.divider()
        try:
            df, mapping, crudo = leer_reporte_dian(archivo.getvalue(), archivo.name)
        except Exception as e:
            st.error(f"No pude leer **{archivo.name}**: {e}")
            continue

        st.subheader(f"📁 {archivo.name}")
        c1, c2, c3 = st.columns([2, 2, 3])
        cliente = c1.text_input("Nombre del cliente", key=f"cli_{idx}")
        cedula = c2.text_input("Cédula del cliente", key=f"ced_{idx}",
                               help="Se usan los dos últimos dígitos para el vencimiento.")

        _, fecha_texto, dd = calcular_vencimiento(cedula, anio)
        if fecha_texto:
            fv, _, _ = calcular_vencimiento(cedula, anio)
            dias = (fv - date.today()).days
            c3.metric(f"Vencimiento (dígitos {dd})", fecha_texto, f"{dias} días")
        elif cedula:
            c3.warning("Cédula no válida para calcular vencimiento.")

        # Mapeo de columnas (editable)
        with st.expander("🔧 Revisar mapeo de columnas (por si la DIAN cambia el formato)"):
            cols = ["(ninguna)"] + list(df.columns)
            m = {}
            mc = st.columns(5)
            for j, rol in enumerate(["nombre", "nit", "formato", "concepto", "valor"]):
                actual = mapping.get(rol)
                default = cols.index(actual) if actual in cols else 0
                sel = mc[j].selectbox(rol.capitalize(), cols, index=default,
                                      key=f"map_{idx}_{rol}")
                if sel != "(ninguna)":
                    m[rol] = sel
            mapping = m or mapping
            st.dataframe(df.head(8), use_container_width=True)

        resumen = construir_resumen(df, mapping)

        if len(resumen) == 0:
            st.warning("No se identificaron entidades. Revisa el mapeo de la columna "
                       "**nombre / razón social**.")
        else:
            st.success(f"✅ {len(resumen)} entidades reportantes identificadas.")
            st.dataframe(resumen, use_container_width=True, hide_index=True)

        # Correo + reporte
        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**✉️ Correo listo para enviar**")
            asunto = generar_asunto(cliente, cedula, anio)
            st.text_input("Asunto", value=asunto, key=f"asu_{idx}")
            correo = generar_correo(cliente, cedula, anio, resumen, firma,
                                    incluir_general)
            st.text_area("Cuerpo", value=correo, height=320, key=f"cor_{idx}")
        with col_b:
            st.markdown("**🖨️ Reporte profesional (HTML → imprime a PDF)**")
            html = generar_html(cliente, cedula, anio, resumen, firma, color)
            st.download_button("⬇️ Descargar reporte HTML", data=html,
                               file_name=f"solicitud_{(cliente or 'cliente').replace(' ', '_')}.html",
                               mime="text/html", key=f"dl_{idx}")
            st.components.v1.html(html, height=420, scrolling=True)

        if fecha_texto:
            agenda.append({"Cliente": cliente or archivo.name, "Cédula": cedula,
                           "Dígitos": dd, "Vencimiento": fecha_texto,
                           "Días restantes": (calcular_vencimiento(cedula, anio)[0] - date.today()).days})

    # Vista consolidada (agenda de vencimientos)
    if agenda:
        st.divider()
        st.subheader("🗓️ Agenda consolidada de vencimientos")
        ag = pd.DataFrame(agenda).sort_values("Días restantes").reset_index(drop=True)
        st.dataframe(ag, use_container_width=True, hide_index=True)
        st.download_button("⬇️ Descargar agenda (CSV)",
                           data=ag.to_csv(index=False).encode("utf-8-sig"),
                           file_name="agenda_vencimientos.csv", mime="text/csv")


if __name__ == "__main__":
    main()
