import math
import os
import pandas as pd
import numpy_financial as npf
import re
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from workalendar.america import Chile

DATA_CACHE = {}

# --- RESTRICCIONES DE NEGOCIO ---
TABLA_TMC = {
    "hasta_50_uf": 3.4400,
    "hasta_200_uf": 2.85666,
    "hasta_5000_uf": 2.5350,
    "mas_de_5000_uf": 0.8200
}

def obtener_tmc(monto_uf):
    if monto_uf <= 50: return TABLA_TMC["hasta_50_uf"]
    elif monto_uf <= 200: return TABLA_TMC["hasta_200_uf"]
    elif monto_uf <= 5000: return TABLA_TMC["hasta_5000_uf"]
    else: return TABLA_TMC["mas_de_5000_uf"]

def obtener_tasa_minima(perfil_str, segmento):
    try:
        num_perfil = int(re.sub(r'\D', '', str(perfil_str)))
    except:
        num_perfil = 1 
        
    if num_perfil <= 10:
        if segmento == 'PBP': return 0.70
        elif segmento == 'PRE': return 0.75
        else: return 0.90 
    else:
        return 0.90
# ---------------------------------

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
                df = pd.read_csv(ruta, sep=None, engine='python')
                df.set_index(df.columns[0], inplace=True)
                df = df.replace({',': '.'}, regex=True).astype(float)
                df.index = df.index.astype(str)
                DATA_CACHE[clave] = df
        except: pass

def obtener_valor_matriz(tipo, fila_val, monto_bruto, es_plazo=False):
    if tipo not in DATA_CACHE: return 0.0
    df = DATA_CACHE[tipo]
    m_millones = monto_bruto / 1_000_000.0
    cols = sorted([int(c) for c in df.columns])
    col = str(next((c for c in cols if m_millones <= c), cols[-1]))
    
    if es_plazo:
        idxs = sorted([int(float(r)) for r in df.index])
        idx = str(next((r for r in idxs if float(fila_val) <= r), idxs[-1]))
    else:
        idx = str(fila_val).upper().strip()
        
    return float(df.loc[idx, col]) if idx in df.index else 0.0

def con_simulacion_consumo(in_fecha_curse, in_primer_venc, in_monto_liquido, in_cuotas, in_tipo_cliente, in_banca, in_perfil, in_canal, in_seguro, in_valor_uf):
    if not DATA_CACHE: cargar_datos_csv()
    
    # 1. Monto Bruto (Impuesto de Timbres y Estampillas LTE + Gasto Notarial)
    t_imp = min(in_cuotas * 0.066, 0.8)
    monto_bruto = math.ceil((in_monto_liquido + 2640) / (1.0 - t_imp/100.0))

    # 2. CF - Búsqueda Mensual y Anualización
    cf_anual_aplicado = 5.4 
    cf_mensual_viz = 5.4 / 12.0
    try:
        df_cf = DATA_CACHE['cf']
        per_max = df_cf['periodo'].max()
        df_r = df_cf[df_cf['periodo'] == per_max].copy()
        df_r['cf'] = df_r['cf'].astype(str).str.replace(',', '.').astype(float)
        df_r = df_r.sort_values(by='plazo_desde').reset_index(drop=True)
        f_idx = df_r[(df_r['plazo_desde'] <= in_cuotas) & (df_r['plazo_hasta'] >= in_cuotas)].index
        if not f_idx.empty:
            cf_mensual_viz = df_r.loc[f_idx[0], 'cf']
            cf_anual_aplicado = cf_mensual_viz * 12.0
    except: pass

    # 3. CASCADA DE PRICING (MODIFICADA: Descuentos sólo sobre el Spread)
    tipo_b = 'normal'
    if in_tipo_cliente == 'MORA_BLANDA': tipo_b = 'mora_blanda'
    elif in_tipo_cliente == 'NUEVO': tipo_b = 'nuevo'
    
    # I. Spread Inicial
    sp_base = obtener_valor_matriz(tipo_b, in_cuotas, monto_bruto, True)
    
    # II. Descuentos en Puntos (Aditivos)
    d_banca = obtener_valor_matriz('banca', in_banca, monto_bruto)
    d_perfil = obtener_valor_matriz('perfil', in_perfil, monto_bruto)
    
    d_seguro = 0.0
    if in_seguro == 'S01': d_seguro = obtener_valor_matriz('seguros_s01', in_cuotas, monto_bruto, True)
    elif in_seguro == 'S02': d_seguro = obtener_valor_matriz('seguros_s02', in_cuotas, monto_bruto, True)
    
    # Spread Subtotal (Aplicación de puntos)
    spread_subtotal = sp_base + d_banca + d_perfil + d_seguro
    
    # III. Descuento por Canal (Porcentual) -> Aplicado al Spread Subtotal
    p_can = obtener_valor_matriz('canal', in_canal, monto_bruto)
    spread_final = spread_subtotal * (1.0 - p_can/100.0)
    
    # IV. Obtención de Tasa Anual y Mensual (Spread Final + Costo de Fondo)
    tasa_final_anual_calc = spread_final + cf_anual_aplicado
    tasa_mensual_calc = tasa_final_anual_calc / 12.0

    # 4. RESTRICCIONES DE NEGOCIO (Piso y TMC sobre la Tasa Mensual)
    tasa_piso = obtener_tasa_minima(in_perfil, in_banca)
    monto_bruto_uf = monto_bruto / in_valor_uf if in_valor_uf > 0 else 0
    tmc_limite = obtener_tmc(monto_bruto_uf)
        
    tasa_aplicada = max(tasa_mensual_calc, tasa_piso) 
    tasa_aplicada = min(tasa_aplicada, tmc_limite) 
    
    # 5. Cálculo de Cuota con Desfase
    f_desfase = {12: 1.0008, 24: 1.0020, 36: 1.0025, 48: 1.0030, 60: 1.0036}.get(in_cuotas, 1.0021)
    valor_cuota = math.ceil(npf.pmt(tasa_aplicada/100.0, in_cuotas, -monto_bruto) * f_desfase)

    # 6. Cálculo de los 2 CAEs
    flujo = [in_monto_liquido] + [-valor_cuota]*in_cuotas
    tir = npf.irr(flujo)
    cae_sernac = (tir * 12.0 * 100.0) if not math.isnan(tir) else 0.0
    cae_interno = cae_sernac + 0.30 

    return {
        "monto_bruto": monto_bruto, 
        "valor_cuota": valor_cuota, 
        "tasa_mensual": tasa_aplicada,
        "cae_sernac": cae_sernac, 
        "cae_interno": cae_interno,
        "piso_aplicado": tasa_piso,
        "tmc_aplicada": tmc_limite,
        "detalle_cascada": [
            {"Concepto": f"1. Spread Base ({tipo_b.upper()})", "Valor Mensual": sp_base / 12.0},
            {"Concepto": f"2. Desc. Banca ({in_banca})", "Valor Mensual": (sp_base + d_banca) / 12.0},
            {"Concepto": f"3. Desc. Perfil ({in_perfil})", "Valor Mensual": (sp_base + d_banca + d_perfil) / 12.0},
            {"Concepto": f"4. Desc. Seguros ({in_seguro})", "Valor Mensual": spread_subtotal / 12.0},
            {"Concepto": f"5. Spread Final (Tras desc. Canal {p_can}%)", "Valor Mensual": spread_final / 12.0},
            {"Concepto": f"6. Suma Costo Fondo (CF: {cf_mensual_viz:.4f}%)", "Valor Mensual": tasa_final_anual_calc / 12.0},
            {"Concepto": f"🛡️ TASA FINAL (Piso {tasa_piso:.2f}% | TMC {tmc_limite:.2f}%)", "Valor Mensual": tasa_aplicada}
        ]
    }
