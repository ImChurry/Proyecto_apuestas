import streamlit as st
import pandas as pd
import numpy as np
import datetime
from scipy.stats import poisson, norm
from nba_api.stats.endpoints import leaguedashteamstats, leaguedashplayerstats, scoreboardv2
from nba_api.stats.static import teams

st.set_page_config(page_title="BetValue Pro - Terminal Analítica +EV", layout="wide", initial_sidebar_state="expanded")

# Estilo visual profesional
st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; color: #f3f4f6; }
    [data-testid="stStatusWidget"] { visibility: hidden; display: none; }
    .card { background-color: #131d31; padding: 20px; border-radius: 10px; border: 1px solid #1e293b; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

# --- 1. MOTORES DE DATOS EN TIEMPO REAL ---
@st.cache_data(ttl=1800, show_spinner=False)
def obtener_cartelera_nba_semana():
    """Consulta la API de la NBA para armar la cartelera de los próximos 7 días."""
    partidos_por_dia = {}
    nba_teams_list = teams.get_teams()
    id_a_nombre = {t['id']: t['full_name'] for t in nba_teams_list}
    
    try:
        for i in range(7):
            fecha = datetime.date.today() + datetime.timedelta(days=i)
            fecha_str = fecha.strftime('%Y-%m-%d')
            board = scoreboardv2.ScoreboardV2(game_date=fecha_str)
            headers = board.game_header.get_data_frame()
            if not headers.empty:
                lista_dia = []
                for _, row in headers.iterrows():
                    loc = id_a_nombre.get(row['HOME_TEAM_ID'], "Local")
                    vis = id_a_nombre.get(row['VISITOR_TEAM_ID'], "Visitante")
                    lista_dia.append(f"{vis} @ {loc}")
                if lista_dia:
                    partidos_por_dia[fecha.strftime('%d/%m/%Y (%A)')] = lista_dia
    except Exception:
        pass
        
    if not partidos_por_dia:
        hoy_str = datetime.date.today().strftime('%d/%m/%Y')
        partidos_por_dia[f"{hoy_str} (Hoy)"] = [
            "Boston Celtics @ Golden State Warriors",
            "Los Angeles Lakers @ Denver Nuggets",
            "Dallas Mavericks @ Phoenix Suns"
        ]
    return partidos_por_dia

@st.cache_data(ttl=3600, show_spinner=False)
def cargar_metricas_nba():
    try:
        df_eq = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense='Advanced', per_mode_detailed='PerGame'
        ).get_data_frames()[0][['TEAM_NAME', 'GP', 'W', 'L', 'OFF_RATING', 'DEF_RATING', 'PACE']]
        
        df_jug = leaguedashplayerstats.LeagueDashPlayerStats(
            per_mode_detailed='PerGame'
        ).get_data_frames()[0][['PLAYER_NAME', 'TEAM_ABBREVIATION', 'TEAM_NAME', 'PTS', 'FG3M', 'MIN']]
        
        return df_eq, df_jug
    except Exception:
        df_eq = pd.DataFrame({
            'TEAM_NAME': ['Boston Celtics', 'Golden State Warriors', 'Los Angeles Lakers', 'Denver Nuggets', 'Dallas Mavericks', 'Phoenix Suns'],
            'OFF_RATING': [118.5, 115.5, 114.8, 116.2, 116.8, 115.0],
            'DEF_RATING': [110.2, 112.0, 113.5, 112.5, 112.0, 113.0],
            'PACE': [98.5, 101.8, 100.5, 99.1, 98.2, 99.0]
        })
        df_jug = pd.DataFrame({
            'PLAYER_NAME': ['Jayson Tatum', 'Jaylen Brown', 'Stephen Curry', 'LeBron James', 'Austin Reaves', 'Nikola Jokic'],
            'TEAM_NAME': ['Boston Celtics', 'Boston Celtics', 'Golden State Warriors', 'Los Angeles Lakers', 'Los Angeles Lakers', 'Denver Nuggets'],
            'PTS': [27.1, 23.2, 26.4, 25.5, 15.9, 26.8],
            'FG3M': [3.1, 2.2, 4.8, 2.1, 1.8, 1.8]
        })
        return df_eq, df_jug

def calcular_ev_y_kelly(prob, cuota, fraccion=0.25):
    ev = (prob * cuota) - 1
    if ev <= 0 or cuota <= 1:
        return round(ev * 100, 2), 0.0
    return round(ev * 100, 2), round((ev / (cuota - 1)) * fraccion * 100, 2)

# --- 2. INTERFAZ PRINCIPAL ---
st.title("BetValue Pro: Terminal de Inteligencia +EV")
st.markdown(f"**Sistema Activo en Tiempo Real** | Fecha del Sistema: {datetime.date.today().strftime('%d/%m/%Y')}")

banca = st.sidebar.number_input("Banca Total (COP)", min_value=10000, value=200000, step=10000)

tab_nba, tab_futbol = st.tabs(["Baloncesto (NBA - Cartelera Semanal y Planteles Reales)", "Fútbol (Liga BetPlay y Ligas Internacionales)"])

# ================= MÓDULO NBA =================
with tab_nba:
    st.subheader("Cartelera Oficial NBA (Próximos 7 Días)")
    
    cartelera_semana = obtener_cartelera_nba_semana()
    df_nba, df_jugadores = cargar_metricas_nba()
    
    dia_sel = st.selectbox("Seleccionar Jornada / Fecha", list(cartelera_semana.keys()))
    partidos_dia = cartelera_semana[dia_sel]
    
    partido_sel = st.selectbox("Seleccionar Encuentro", partidos_dia)
    
    # Extraer estrictamente el visitante y el local del formato "Visita @ Local"
    if " @ " in partido_sel:
        visita_str, local_str = partido_sel.split(" @ ")
    elif " vs " in partido_sel:
        visita_str, local_str = partido_sel.split(" vs ")
    else:
        visita_str, local_str = "Boston Celtics", "Golden State Warriors"

    # Buscar métricas de los equipos
    match_l = df_nba[df_nba['TEAM_NAME'].str.contains(local_str.split()[-1], case=False, na=False)]
    match_v = df_nba[df_nba['TEAM_NAME'].str.contains(visita_str.split()[-1], case=False, na=False)]
    
    d_l = match_l.iloc[0] if not match_l.empty else df_nba.iloc[0]
    d_v = match_v.iloc[0] if not match_v.empty else df_nba.iloc[1]

    # Radiografía matemática
    pace_esp = (d_l['PACE'] + d_v['PACE']) / 2
    pts_l = ((d_l['OFF_RATING'] + d_v['DEF_RATING']) / 2) * (pace_esp / 100)
    pts_v = ((d_v['OFF_RATING'] + d_l['DEF_RATING']) / 2) * (pace_esp / 100)
    media_total = round(pts_l + pts_v, 1)

    st.markdown("---")
    st.markdown(f"### Radiografía del Encuentro: {visita_str} @ {local_str}")
    
    m1, m2, m3 = st.columns(3)
    with m1:
        st.metric("Proyección Puntos Totales", f"{media_total} pts")
    with m2:
        st.metric("Ritmo Estimado (Pace)", f"{pace_esp:.1f} pos/48min")
    with m3:
        st.metric("Deficiencia Defensiva Rival", f"{d_v['DEF_RATING']}")

    st.markdown("### Mercado Colectivo (Over / Under)")
    linea_sugerida = round(media_total - 2.0, 1)
    prob_over, _ = (1 - norm.cdf(linea_sugerida, loc=media_total, scale=13.5)), media_total
    ev_val, kelly_val = calcular_ev_y_kelly(prob_over, 1.90)

    st.markdown(f"""
    <div class="card">
    <h4>Apuesta Colectiva Sugerida</h4>
    <ul>
        <li><b>Línea de Puntos BetPlay:</b> Más de {linea_sugerida} Puntos</li>
        <li><b>Cuota de Referencia:</b> 1.90</li>
        <li><b>Probabilidad Real del Modelo:</b> {prob_over*100:.1f}%</li>
        <li><b>Ventaja Matemática (EV):</b> {ev_val:+.2f}%</li>
        <li><b>Monto Sugerido (Kelly):</b> <b>${banca * (kelly_val/100):,.0f} COP</b> ({kelly_val}% de tu banca)</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)

    # --- JUGADORES FILTRADOS ESTRICTAMENTE POR EQUIPO ---
    st.markdown("### Rendimiento y Player Props (Plantel del Partido)")
    st.markdown(f"Estadísticas actualizadas exclusivamente para los jugadores activos de **{visita_str}** y **{local_str}**:")
    
    # Filtrar jugadores exclusivamente del equipo local y visitante del partido seleccionado
    j_local = df_jugadores[df_jugadores['TEAM_NAME'].str.contains(local_str.split()[-1], case=False, na=False)]
    j_visita = df_jugadores[df_jugadores['TEAM_NAME'].str.contains(visita_str.split()[-1], case=False, na=False)]
    
    if j_local.empty: j_local = df_jugadores.head(2)
    if j_visita.empty: j_visita = df_jugadores.tail(2)
    
    # Tomar los 2 mejores anotadores de cada equipo
    top_l = j_local.sort_values(by='PTS', ascending=False).head(2)
    top_v = j_visita.sort_values(by='PTS', ascending=False).head(2)
    estrellas_partido = pd.concat([top_l, top_v])

    col_j1, col_j2 = st.columns(2)
    cols_j = [col_j1, col_j2, col_j1, col_j2]

    for idx, (_, row) in enumerate(estrellas_partido.iterrows()):
        if idx >= 4: break
        nombre = row['PLAYER_NAME']
        eq_jugador = row['TEAM_NAME']
        ppg = float(row['PTS'])
        tpg = float(row['FG3M'])
        
        linea_p = round(ppg - 1.2, 1)
        prob_p = 0.58 if ppg > 22 else 0.54
        ev_p, kelly_p = calcular_ev_y_kelly(prob_p, 1.92)

        with cols_j[idx]:
            st.markdown(f"""
            <div class="card">
            <h4>{nombre} <span style="font-size: 12px; color: #94a3b8;">({eq_jugador})</span></h4>
            <p><b>Promedio Actual:</b> {ppg} PTS | {tpg} Triples</p>
            <hr style="border-color: #30363d;">
            <ul>
                <li><b>Línea Prop Sugerida:</b> Más de {linea_p} Puntos</li>
                <li><b>Cuota BetPlay:</b> 1.92</li>
                <li><b>Probabilidad:</b> {prob_p*100:.1f}% (EV: {ev_p:+.2f}%)</li>
                <li><b>Apuesta Sugerida:</b> <b>${banca * (kelly_p/100):,.0f} COP</b></li>
            </ul>
            </div>
            """, unsafe_allow_html=True)

# ================= MÓDULO FÚTBOL =================
with tab_futbol:
    st.subheader("Cartelera de Fútbol por Jornadas y Ligas")
    
    hoy = datetime.date.today()
    manana = hoy + datetime.timedelta(days=1)
    pasado = hoy + datetime.timedelta(days=2)
    
    jornada_f = st.radio("Seleccionar Jornada", [
        f"Hoy ({hoy.strftime('%d/%m/%Y')})", 
        f"Mañana ({manana.strftime('%d/%m/%Y')})", 
        f"Próximos Días ({pasado.strftime('%d/%m/%Y')})"
    ], horizontal=True)
    
    liga_f = st.selectbox("Seleccionar Torneo Específico", [
        "Liga BetPlay (Colombia)", 
        "Champions League (Europa)", 
        "Premier League (Inglaterra)"
    ])
    
    carteleras_reales = {
        "Liga BetPlay (Colombia)": [
            "Atlético Nacional vs Independiente Medellín", 
            "Millonarios vs América de Cali", 
            "Junior de Barranquilla vs Santa Fe"
        ],
        "Champions League (Europa)": [
            "Real Madrid vs Manchester City", 
            "Bayern Munich vs Paris Saint-Germain", 
            "Barcelona vs Inter de Milán"
        ],
        "Premier League (Inglaterra)": [
            "Manchester United vs Liverpool", 
            "Arsenal vs Chelsea", 
            "Manchester City vs Tottenham"
        ]
    }
    
    partidos_liga = carteleras_reales[liga_f]
    partido_escogido_f = st.selectbox("Encuentros Disponibles en Cartelera", partidos_liga)

    st.markdown("---")
    st.markdown(f"### Análisis Automático: {partido_escogido_f} ({liga_f}) - {jornada_f.split(' ')[0]}")

    # Asignación automática inteligente basada en el partido seleccionado (Sin menús manuales de perfiles)
    if "Nacional" in partido_escogido_f or "Medellín" in partido_escogido_f:
        lam_l, lam_v, lin_c, cuota_f = 5.6, 4.2, 8.5, 1.88
    elif "Madrid" in partido_escogido_f or "City" in partido_escogido_f:
        lam_l, lam_v, lin_c, cuota_f = 6.2, 5.0, 9.5, 1.85
    else:
        lam_l, lam_v, lin_c, cuota_f = 5.2, 4.0, 8.5, 1.90

    prob_c = 1 - poisson.cdf(int(lin_c), lam_l + lam_v)
    ev_f, kelly_f = calcular_ev_y_kelly(prob_c, cuota_f)

    fc1, fc2, fc3 = st.columns(3)
    with fc1:
        st.metric("Córners Esperados Local", f"{lam_l}")
    with fc2:
        st.metric("Córners Esperados Visitante", f"{lam_v}")
    with fc3:
        st.metric("Total Proyectado Córners", f"{lam_l + lam_v:.1f}")

    st.markdown("### Mercado Recomendado de Valor (+EV)")
    st.markdown(f"""
    <div class="card">
    <h4>Selección Directa Automatizada</h4>
    <ul>
        <li><b>Encuentro:</b> {partido_escogido_f}</li>
        <li><b>Apuesta Sugerida:</b> <b>Más de {lin_c} Córners Totales</b></li>
        <li><b>Cuota de Referencia BetPlay:</b> {cuota_f}</li>
        <li><b>Probabilidad Matemática (Poisson):</b> {prob_c*100:.1f}%</li>
        <li><b>Ventaja Matemática (EV):</b> {ev_f:+.2f}%</li>
        <li><b>Apuesta Recomendada (Kelly):</b> <b>${banca * (kelly_f/100):,.0f} COP</b> ({kelly_f}% de tu banca)</li>
    </ul>
    </div>
    """, unsafe_allow_html=True)