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
    "hasta_50_uf": 3.3500,
    "hasta_200_uf": 2.7666,
    "hasta_5000_uf": 2.4000,
    "mas_de_5000_uf": 0.8300
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
    
    # 0. Monto Bruto (Impuesto de Timbres y Estampillas LTE + Gasto Notarial fijo)
    t_imp = min(in_cuotas * 0.066, 0.8)
    monto_bruto = math.ceil((in_monto_liquido + 2640) / (1.0 - t_imp/100.0))

    # ========================================================================
    # PASO 1: Definir Spread Base Inicial (Anualizado según tabla)
    # ========================================================================
    tipo_b = 'normal'
    if in_tipo_cliente == 'MORA_BLANDA': tipo_b = 'mora_blanda'
    elif in_tipo_cliente == 'NUEVO': tipo_b = 'nuevo'
    
    spread_base_anual = obtener_valor_matriz(tipo_b, in_cuotas, monto_bruto, True)
    
    # ========================================================================
    # PASO 2: Aplicar Descuentos en ORDEN ESTRICTO (Suma algebraica)
    # ========================================================================
    
    # 2.1. Descuento por Banca
    d_banca_anual = obtener_valor_matriz('banca', in_banca, monto_bruto)
    spread_paso_banca = spread_base_anual + d_banca_anual
    
    # 2.2. Descuento por Cruce de Seguros (S01 o S02)
    d_seguro_anual = 0.0
    if in_seguro == 'S01': d_seguro_anual = obtener_valor_matriz('seguros_s01', in_cuotas, monto_bruto, True)
    elif in_seguro == 'S02': d_seguro_anual = obtener_valor_matriz('seguros_s02', in_cuotas, monto_bruto, True)
    spread_paso_seguros = spread_paso_banca + d_seguro_anual
    
    # 2.3. Descuento por Perfil de Riesgo
    d_perfil_anual = obtener_valor_matriz('perfil', in_perfil, monto_bruto)
    spread_paso_perfiles = spread_paso_seguros + d_perfil_anual
    
    # 2.4. Descuento por Canal de Curse (% porcentual aplicado al spread acumulado)
    p_can = obtener_valor_matriz('canal', in_canal, monto_bruto)
    spread_final_anual = spread_paso_perfiles * (1.0 - p_can/100.0)
    
    # Llevamos el Spread Final Anual a base MENSUAL
    spread_final_mensual = spread_final_anual / 12.0

    # ========================================================================
    # PASO 3: Sumar Costo de Fondo (Búsqueda de CF Mensual)
    # ========================================================================
    cf_mensual = 5.4 / 12.0 # Default fallback
    try:
        df_cf = DATA_CACHE['cf']
        per_max = df_cf['periodo'].max()
        df_r = df_cf[df_cf['periodo'] == per_max].copy()
        df_r['cf'] = df_r['cf'].astype(str).str.replace(',', '.').astype(float)
        df_r = df_r.sort_values(by='plazo_desde').reset_index(drop=True)
        f_idx = df_r[(df_r['plazo_desde'] <= in_cuotas) & (df_r['plazo_hasta'] >= in_cuotas)].index
        if not f_idx.empty:
            cf_mensual = df_r.loc[f_idx[0], 'cf']
    except: pass

    # ========================================================================
    # PASO 4: Obtener Tasa Mensual
    # ========================================================================
    tasa_mensual_pura = spread_final_mensual + cf_mensual

    # ========================================================================
    # RESTRICCIONES DE NEGOCIO (Tasa Piso y Tope TMC)
    # ========================================================================
    tasa_piso = obtener_tasa_minima(in_perfil, in_banca)
    monto_bruto_uf = monto_bruto / in_valor_uf if in_valor_uf > 0 else 0
    tmc_limite = obtener_tmc(monto_bruto_uf)
        
    tasa_aplicada = max(tasa_mensual_pura, tasa_piso) 
    tasa_aplicada = min(tasa_aplicada, tmc_limite) 
    
    # Cálculo de Cuota con Desfase
    f_desfase = {12: 1.0008, 24: 1.0020, 36: 1.0025, 48: 1.0030, 60: 1.0036}.get(in_cuotas, 1.0021)
    valor_cuota = math.ceil(npf.pmt(tasa_aplicada/100.0, in_cuotas, -monto_bruto) * f_desfase)

    # Cálculo de los CAEs
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
        
        # ---> VARIABLES DE DESCUENTO (Para exportación masiva) <---
        "desc_banca_anual": d_banca_anual,
        "desc_seguro_anual": d_seguro_anual,
        "desc_perfil_anual": d_perfil_anual,
        "desc_canal_anual": -(spread_paso_perfiles * (p_can/100.0)),
        # -----------------------------------------------------------

        "detalle_cascada": [
            {"Paso": "1", "Concepto": f"Spread Base Inicial ({tipo_b.upper()}) - Anual", "Valor": f"{spread_base_anual:.4f}%"},
            {"Paso": "2.1", "Concepto": f"Sumar Ajuste por Banca ({in_banca})", "Valor": f"{d_banca_anual:+.4f}%"},
            {"Paso": "-", "Concepto": "  ↳ Subtotal Spread tras Banca", "Valor": f"{spread_paso_banca:.4f}%"},
            {"Paso": "2.2", "Concepto": f"Sumar Ajuste por Seguros ({in_seguro})", "Valor": f"{d_seguro_anual:+.4f}%"},
            {"Paso": "-", "Concepto": "  ↳ Subtotal Spread tras Seguros", "Valor": f"{spread_paso_seguros:.4f}%"},
            {"Paso": "2.3", "Concepto": f"Sumar Ajuste por Perfil ({in_perfil})", "Valor": f"{d_perfil_anual:+.4f}%"},
            {"Paso": "-", "Concepto": "  ↳ Subtotal Spread tras Perfil", "Valor": f"{spread_paso_perfiles:.4f}%"},
            {"Paso": "2.4", "Concepto": f"Descuento Porcentual Canal ({p_can}%)", "Valor": f"-{spread_paso_perfiles * (p_can/100.0):.4f}%"},
            {"Paso": "-", "Concepto": "▶️ SPREAD FINAL COMERCIAL (Anual)", "Valor": f"{spread_final_anual:.4f}%"},
            {"Paso": "-", "Concepto": "▶️ SPREAD FINAL COMERCIAL (Mensual)", "Valor": f"{spread_final_mensual:.4f}%"},
            {"Paso": "3", "Concepto": "Sumar Costo de Fondo (CF Mensual)", "Valor": f"{cf_mensual:+.4f}%"},
            {"Paso": "4", "Concepto": "Tasa Mensual Pura Calculada", "Valor": f"{tasa_mensual_pura:.4f}%"},
            {"Paso": "🛡️", "Concepto": f"TASA FINAL APLICADA (Límites: Piso {tasa_piso:.2f}% | TMC {tmc_limite:.2f}%)", "Valor": f"{tasa_aplicada:.4f}%"}
        ]
    }
