import math
import os
import pandas as pd
import numpy_financial as npf
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from workalendar.america import Chile

DATA_CACHE = {}

def cargar_datos_csv():
    global DATA_CACHE
    dir_actual = os.path.dirname(__file__)
    archivos = {
        'normal': '1.1 plantilla_normal.csv', 
        'mora_blanda': '1.2 plantilla_mora_blanda.csv',
        'nuevo': '1.3 plantilla_nuevo.csv',
        'banca': '2. plantilla_banca.csv',
        'perfil': '3. plantilla_perfil.csv', 
        'seguros_s01': '4.1 plantilla_seguros_s01.csv',
        'seguros_s02': '4.2 plantilla_seguros_s02.csv',
        'canal': '5. plantilla_canal.csv', 
        'cf': 'cf.csv', 'uf': 'uf.csv'
    }
    for clave, nombre in archivos.items():
        ruta = os.path.join(dir_actual, nombre)
        # Buscar en la misma carpeta o en subcarpeta 'data'
        if not os.path.exists(ruta):
            ruta = os.path.join(dir_actual, 'data', nombre)
        if not os.path.exists(ruta): continue
        
        try:
            if clave in ['cf', 'uf']:
                df = pd.read_csv(ruta, sep=';', engine='python')
                if len(df.columns) < 2:
                    df = pd.read_csv(ruta, sep=',', engine='python')
                DATA_CACHE[clave] = df
            else:
                # Plantillas de descuentos y spreads
                df = pd.read_csv(ruta, sep=None, engine='python')
                df.set_index(df.columns[0], inplace=True)
                df = df.replace({',': '.'}, regex=True).astype(float)
                df.index = df.index.astype(str)
                DATA_CACHE[clave] = df
        except: pass

def obtener_valor_matriz(tipo, fila_val, monto_bruto, es_plazo=False):
    """ Función para extraer el valor en base al tramo de monto (columnas) y la fila correspondiente """
    if tipo not in DATA_CACHE: return 0.0
    df = DATA_CACHE[tipo]
    
    # Los montos en las cabeceras están en millones
    m_millones = monto_bruto / 1_000_000.0
    cols = sorted([int(c) for c in df.columns])
    col = str(next((c for c in cols if m_millones <= c), cols[-1]))
    
    if es_plazo:
        idxs = sorted([int(float(r)) for r in df.index])
        idx = str(next((r for r in idxs if float(fila_val) <= r), idxs[-1]))
    else:
        idx = str(fila_val).upper().strip()
        
    return float(df.loc[idx, col]) if idx in df.index else 0.0

def con_simulacion_consumo(in_fecha_curse, in_primer_venc, in_monto_liquido, in_cuotas, in_tipo_cliente, in_banca, in_perfil, in_canal, in_seguro):
    if not DATA_CACHE: cargar_datos_csv()
    cal = Chile()

    # 1. Monto Bruto (Asumimos impuesto de Timbres y Estampillas LTE)
    t_imp = min(in_cuotas * 0.066, 0.8)
    # Gasto Notarial fijo estimado de $2.640
    monto_bruto = math.ceil((in_monto_liquido + 2640) / (1.0 - t_imp/100.0))

    # 2. CF - Búsqueda Mensual
    cf_anual_aplicado = 5.4 
    cf_mensual_viz = 5.4 / 12.0
    tramo_usado = "Fallback"
    try:
        df_cf = DATA_CACHE['cf']
        per_max = df_cf['periodo'].max()
        df_r = df_cf[df_cf['periodo'] == per_max].copy()
        df_r['cf'] = df_r['cf'].astype(str).str.replace(',', '.').astype(float)
        df_r = df_r.sort_values(by='plazo_desde').reset_index(drop=True)
        
        f_idx = df_r[(df_r['plazo_desde'] <= in_cuotas) & (df_r['plazo_hasta'] >= in_cuotas)].index
        if not f_idx.empty:
            idx = f_idx[0]
            cf_mensual_viz = df_r.loc[idx, 'cf']
            tramo_usado = f"{df_r.loc[idx, 'plazo_desde']}-{df_r.loc[idx, 'plazo_hasta']}m"
            cf_anual_aplicado = cf_mensual_viz * 12.0
    except Exception as e:
        pass

    # 3. Cascada de Pricing Consumo
    # I. Obtener Spread Base (Normal, Mora Blanda o Nuevo)
    tipo_b = 'normal'
    if in_tipo_cliente == 'MORA_BLANDA': tipo_b = 'mora_blanda'
    elif in_tipo_cliente == 'NUEVO': tipo_b = 'nuevo'
    
    sp_base = obtener_valor_matriz(tipo_b, in_cuotas, monto_bruto, True)
    
    # II. Tasa Base (Spread + CF)
    tasa_p0 = sp_base + cf_anual_aplicado
    
    # III. Descuentos en orden
    # 1. Banca
    d_banca = obtener_valor_matriz('banca', in_banca, monto_bruto)
    tasa_p1 = tasa_p0 + d_banca
    
    # 2. Perfil
    d_perfil = obtener_valor_matriz('perfil', in_perfil, monto_bruto)
    tasa_p2 = tasa_p1 + d_perfil
    
    # 3. Seguros (S01 o S02)
    d_seguro = 0.0
    if in_seguro == 'S01':
        d_seguro = obtener_valor_matriz('seguros_s01', in_cuotas, monto_bruto, True)
    elif in_seguro == 'S02':
        d_seguro = obtener_valor_matriz('seguros_s02', in_cuotas, monto_bruto, True)
    tasa_p3 = tasa_p2 + d_seguro
    
    # 4. Canal (Porcentaje sobre la tasa previa)
    p_can = obtener_valor_matriz('canal', in_canal, monto_bruto)
    tasa_final_anual = tasa_p3 * (1.0 - p_can/100.0)
    
    tasa_mensual = tasa_final_anual / 12.0

    # 4. Tabla de Desarrollo (Amortización)
    tabla = []
    f_venc = in_fecha_curse
    for c in range(in_cuotas + 1):
        if c == 1: f_venc = in_primer_venc
        elif c > 1: f_venc = in_primer_venc + relativedelta(months=c-1)
        while not cal.is_working_day(f_venc): f_venc += timedelta(days=1)
        tabla.append({'cuota': c, 'fec_ven': f_venc, 'dias': 0, 'tasa_diaria': 0.0})

    c1_ac, c2_ac = 1.0, 0.0
    for i in range(1, len(tabla)):
        d = (tabla[i]['fec_ven'] - tabla[i-1]['fec_ven']).days
        tabla[i]['dias'] = d
        tabla[i]['tasa_diaria'] = (d * tasa_mensual) / 3000.0
        c1_ac *= (1.0 + tabla[i]['tasa_diaria'])
        c2_ac += (1.0 / c1_ac)
    
    valor_cuota = math.ceil(monto_bruto / c2_ac)

    # 5. Cálculo de los 2 CAEs
    flujo = [in_monto_liquido] + [-valor_cuota]*in_cuotas
    tir = npf.irr(flujo)
    cae_sernac = (tir * 12.0 * 100.0) if not math.isnan(tir) else 0.0
    
    # Si requieres una fórmula distinta para el 2do CAE (ej. interno sin un gasto en particular), 
    # la puedes adaptar aquí. Por defecto lo dejo listo para reportar.
    cae_interno = cae_sernac 

    return {
        "monto_bruto": monto_bruto, "valor_cuota": valor_cuota, "tasa_mensual": tasa_mensual,
        "cae_sernac": cae_sernac, "cae_interno": cae_interno, "tabla_desarrollo": tabla,
        "detalle_cascada": [
            {"Concepto": f"1. Spread Base ({tipo_b.upper()})", "Ajuste": None, "Valor Mensual": sp_base / 12.0},
            {"Concepto": f"2. Suma Costo Fondo (CF: {cf_mensual_viz:.4f}%)", "Ajuste": cf_mensual_viz, "Valor Mensual": tasa_p0 / 12.0},
            {"Concepto": f"3. Desc. Banca ({in_banca})", "Ajuste": d_banca / 12.0, "Valor Mensual": tasa_p1 / 12.0},
            {"Concepto": f"4. Desc. Perfil ({in_perfil})", "Ajuste": d_perfil / 12.0, "Valor Mensual": tasa_p2 / 12.0},
            {"Concepto": f"5. Desc. Seguros ({in_seguro})", "Ajuste": d_seguro / 12.0, "Valor Mensual": tasa_p3 / 12.0},
            {"Concepto": f"6. TASA FINAL (Desc. Canal {p_can}%)", "Ajuste": -(tasa_p3 - tasa_final_anual) / 12.0, "Valor Mensual": tasa_mensual}
        ]
    }