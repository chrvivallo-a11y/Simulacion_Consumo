import streamlit as st
import pandas as pd
import time
from datetime import date
from dateutil.relativedelta import relativedelta

# Importación desde el motor consumo
from motor_simulacion_consumo import con_simulacion_consumo 

# ==============================================================================
# CONFIGURACIÓN DE PÁGINA
# ==============================================================================
st.set_page_config(page_title="Simulador Consumo BCI", page_icon="🏦", layout="wide")

st.title("🏦 Simulador Créditos de Consumo - BCI")
st.markdown("""
**Estado del Motor:** - Cascada de Pricing Consumo Mensualizada mediante CSVs.
- **🛡️ Restricciones:** Tasa Piso, TMC dinámico según UF, Factor de Desfase en Cuota y Holgura de 0.30% en CAE interno activadas.
""")

tab_individual, tab_masivo = st.tabs(["👤 Simulación Individual", "📁 Simulación Masiva (Batch)"])

# ==============================================================================
# MÓDULO 1: SIMULACIÓN INDIVIDUAL
# ==============================================================================
with tab_individual:
    st.header("1. Datos de la Operación")
    
    # Entrada de UF requerida para calcular la TMC exacta en tiempo real
    val_uf = st.number_input("Valor UF Hoy ($)", value=38000.0, step=10.0, format="%.1f")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        f_curse = st.date_input("Fecha de Curse", value=date.today())
        monto = st.number_input("Monto Líquido ($)", min_value=100000, value=5000000, step=500000)
        tipo_cliente = st.selectbox("Tipo de Cliente", ["NORMAL", "MORA_BLANDA", "NUEVO"])
    
    with col2:
        plazo = st.number_input("Plazo (Cuotas)", min_value=3, max_value=120, value=24, step=1)
        banca = st.selectbox("Banca", ["PP", "PBP", "PRE"])
        perfil = st.selectbox("Perfil de Riesgo", [f"P{i}" for i in range(1, 12)])
        
    with col3:
        f_pago = st.date_input("Fecha Primer Pago", value=f_curse + relativedelta(months=1))
        canal_ind = st.selectbox("Canal de Venta", ["CCDD", "ASISTIDO"])
        seguro_ind = st.selectbox("Seguro Cruzado", ["SIN_SEGURO", "S01 (Desgravamen)", "S02 (Full)"])

    st.markdown("---")
    
    if st.button("🚀 Calcular Simulación Consumo", type="primary", use_container_width=True):
        try:
            seg_clean = "SIN_SEGURO"
            if "S01" in seguro_ind: seg_clean = "S01"
            elif "S02" in seguro_ind: seg_clean = "S02"

            res = con_simulacion_consumo(
                in_fecha_curse=f_curse,
                in_primer_venc=f_pago,
                in_monto_liquido=monto,
                in_cuotas=plazo,
                in_tipo_cliente=tipo_cliente,
                in_banca=banca,
                in_perfil=perfil,
                in_canal=canal_ind,
                in_seguro=seg_clean,
                in_valor_uf=val_uf
            )
            
            # --- SECCIÓN DE RESULTADOS ---
            r1, r2, r3, r4, r5 = st.columns(5)
            r1.metric("Valor Cuota", f"${res['valor_cuota']:,.0f}".replace(',', '.'))
            r2.metric("Tasa Mensual", f"{res['tasa_mensual']:.4f}%")
            r3.metric("Monto Bruto", f"${res['monto_bruto']:,.0f}".replace(',', '.'))
            r4.metric("CAE Sernac", f"{res['cae_sernac']:.2f}%")
            r5.metric("CAE 2 (+0.30%)", f"{res['cae_interno']:.2f}%")

            # --- CASCADA VISUAL DE DOS COLUMNAS ---
            st.subheader("🪜 Detalle de Cascada (Pricing Mensual)")
            df_c = pd.DataFrame(res["detalle_cascada"])
            df_c["Tasa Paso (Mes)"] = df_c["Valor Mensual"].apply(lambda x: f"**{x:.4f}%**")
            st.table(df_c[["Concepto", "Tasa Paso (Mes)"]])

        except Exception as e:
            st.error(f"Error en el cálculo: {e}")

# ==============================================================================
# MÓDULO 2: SIMULACIÓN MASIVA
# ==============================================================================
with tab_masivo:
    st.header("📁 Simulación por Lotes (Masiva)")
    
    with st.expander("ℹ️ Instrucciones y Formato del Archivo CSV", expanded=False):
        diccionario = pd.DataFrame({
            "Nombre Columna": ["rut", "fecha_curse", "fecha_pago", "monto", "plazo", "tipo_cliente", "banca", "perfil", "canal", "seguro"],
            "Descripción": ["RUT del cliente", "Fecha de otorgamiento", "Fecha primer venc.", "Monto Líquido", "Cantidad de cuotas", "Base spread spread", "Segmento o Banca", "Perfil de Riesgo", "Canal de curse", "Seguro asociado"],
            "Valores Permitidos": ["Texto (ej: 12345678-9)", "YYYY-MM-DD", "YYYY-MM-DD", "Entero", "Entero", "NORMAL, MORA_BLANDA, NUEVO", "PP, PBP, PRE", "P1 al P11", "CCDD o ASISTIDO", "SIN_SEGURO, S01, S02"]
        })
        st.table(diccionario)
        
        plantilla_df = pd.DataFrame(columns=diccionario["Nombre Columna"].tolist())
        st.download_button(
            label="📥 Descargar Plantilla CSV Vacía",
            data=plantilla_df.to_csv(index=False, sep=';').encode('utf-8-sig'),
            file_name="plantilla_masiva_consumo.csv",
            mime="text/csv"
        )
    
    st.markdown("---")
    up = st.file_uploader("Sube tu archivo CSV con los casos a simular", type="csv")
    
    if up:
        try:
            df_in = pd.read_csv(up, sep=None, engine='python')
            columnas_requeridas = ["rut", "fecha_curse", "fecha_pago", "monto", "plazo", "tipo_cliente", "banca", "perfil", "canal", "seguro"]
            columnas_faltantes = [col for col in columnas_requeridas if col not in df_in.columns]
            
            if columnas_faltantes:
                st.error(f"❌ Error: El archivo no cumple con el formato requerido. Faltan las columnas: {', '.join(columnas_faltantes)}")
            else:
                st.success(f"Archivo cargado correctamente con {len(df_in)} registros.")
                st.dataframe(df_in.head())
                
                if st.button("▶️ Iniciar Procesamiento de Lote", type="primary"):
                    start_time = time.time()
                    results = []
                    bar = st.progress(0)
                    
                    for i, row in df_in.iterrows():
                        try:
                            r = con_simulacion_consumo(
                                in_fecha_curse=pd.to_datetime(row['fecha_curse']).date(), 
                                in_primer_venc=pd.to_datetime(row['fecha_pago']).date(), 
                                in_monto_liquido=int(row['monto']), 
                                in_cuotas=int(row['plazo']), 
                                in_tipo_cliente=str(row['tipo_cliente']).upper().strip(), 
                                in_banca=str(row['banca']).upper().strip(), 
                                in_perfil=str(row['perfil']).upper().strip(), 
                                in_canal=str(row['canal']).upper().strip(), 
                                in_seguro=str(row['seguro']).upper().strip(),
                                in_valor_uf=38000.0 # Se asume una UF estándar para evaluar el lote
                            )
                            
                            fila = row.to_dict()
                            fila.update({
                                "monto_bruto_res": r["monto_bruto"], 
                                "valor_cuota_res": r["valor_cuota"], 
                                "tasa_mensual_res": r["tasa_mensual"],
                                "cae_sernac_res": r["cae_sernac"],
                                "cae_interno_res": r["cae_interno"],
                                "tasa_piso_res": r["piso_aplicado"],
                                "tmc_tope_res": r["tmc_aplicada"]
                            })
                            results.append(fila)
                        except Exception as fila_err:
                            fila_error = row.to_dict()
                            fila_error.update({"monto_bruto_res": "ERROR", "valor_cuota_res": str(fila_err)})
                            results.append(fila_error)
                            
                        bar.progress((i+1)/len(df_in))
                    
                    df_out = pd.DataFrame(results)
                    st.success(f"✅ Procesamiento completado en **{(time.time() - start_time):.2f} segundos**.")
                    st.dataframe(df_out)
                    
                    st.download_button(
                        label="📥 Descargar Resultados Consolidados", 
                        data=df_out.to_csv(index=False, sep=';', decimal=',').encode('utf-8-sig'), 
                        file_name=f"resultados_batch_consumo_{date.today()}.csv",
                        mime="text/csv"
                    )
        except Exception as e:
            st.error(f"Error al procesar el archivo CSV: {e}")
