import streamlit as st
import pandas as pd
import numpy as np
import datetime
import requests
import itertools
import textwrap
from scipy.stats import poisson, norm
from nba_api.stats.endpoints import (
    leaguedashteamstats, leaguedashplayerstats
)
from nba_api.stats.static import teams

# ============================================================
# CONFIGURACIÓN Y ESTILOS
# ============================================================
ODDS_API_KEY = "f98f201482871ab5bd2077cfcf7d0146"

st.set_page_config(page_title="BetValue Pro - Terminal +EV", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    .stApp { background-color: #0b0f19; color: #f3f4f6; }
    .card { background-color: #131d31; padding: 15px; border-radius: 10px; border: 1px solid #1e293b; margin-bottom: 10px; }
    .fair-odds { color: #38bdf8; font-weight: bold; font-size: 1.1em; }
    .metric-box { background-color: #0f172a; padding: 10px; border-radius: 8px; text-align: center; border: 1px solid #334155; margin-bottom: 10px;}
    .combo-box { background-color: #1e1b4b; padding: 15px; border-radius: 10px; border: 2px solid #6366f1; margin-bottom: 15px; }
    .combo-title { color: #a78bfa; font-weight: bold; font-size: 1.2em; margin-bottom: 10px; }
    .live-box { background-color: #0f172a; padding: 10px; border-radius: 8px; border-left: 4px solid #ef4444; margin-bottom: 8px; }
    .live-score { font-size: 1.5em; font-weight: bold; color: #fbbf24; }
    
    /* --- BANNER FLOTANTE --- */
    .floating-live-banner {
        position: fixed;
        top: 70px;
        right: 20px;
        width: 300px;
        background-color: #111827;
        border: 1px solid #374151;
        border-radius: 10px;
        padding: 12px;
        z-index: 9999;
        box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.7);
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .floating-live-title {
        font-size: 12px;
        color: #ef4444;
        font-weight: bold;
        margin-bottom: 10px;
        display: flex;
        align-items: center;
        gap: 5px;
        text-transform: uppercase;
    }
    .floating-match {
        display: flex;
        justify-content: space-between;
        align-items: center;
        font-size: 13px;
        padding: 8px 0;
        border-bottom: 1px solid #1f2937;
        color: #e5e7eb;
    }
    .floating-match:last-child { border-bottom: none; }
    .team-badge {
        background-color: #374151;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 10px;
        font-weight: bold;
        color: #9ca3af;
        margin-right: 5px;
    }
    .floating-score {
        font-weight: bold;
        color: #fbbf24;
        background-color: #1f2937;
        padding: 3px 8px;
        border-radius: 6px;
        font-size: 13px;
        border: 1px solid #374151;
    }
    .floating-time { font-size: 10px; color: #6b7280; margin-top: 2px; }
    </style>
""", unsafe_allow_html=True)

# ============================================================
# MATEMÁTICAS Y LÓGICA
# ============================================================
def calcular_ev_y_kelly(prob, cuota, fraccion=0.25):
    ev = (prob * cuota) - 1
    if ev <= 0 or cuota <= 1: return round(ev * 100, 2), 0.0
    return round(ev * 100, 2), round((ev / (cuota - 1)) * fraccion * 100, 2)

def prob_player_prop(media, linea, stat_type='PTS'):
    cv = {'PTS': 0.25, 'REB': 0.35, 'AST': 0.40, 'FG3M': 0.50, 'CORNERS': 0.30, 'CARDS': 0.45}.get(stat_type, 0.25)
    sigma = max(1.0, media * cv)
    return float(1 - norm.cdf(linea, loc=media, scale=sigma)), sigma

def format_fecha(iso_str):
    try:
        dt = datetime.datetime.strptime(iso_str, "%Y-%m-%dT%H:%M:%SZ")
        dt_local = dt - datetime.timedelta(hours=5)
        return dt_local.strftime("%d/%m %I:%M %p")
    except:
        return iso_str

# ============================================================
# CONSULTAS A THE ODDS API
# ============================================================
@st.cache_data(ttl=900, show_spinner="Consultando mercado real...")
def obtener_cuotas_referencia(sport_key):
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds/?apiKey={ODDS_API_KEY}&regions=eu&markets=h2h,totals,spreads&bookmakers=pinnacle"
    try:
        r = requests.get(url, timeout=10)
        return r.json() if r.status_code == 200 else []
    except:
        return []

@st.cache_data(ttl=120, show_spinner=False)
def obtener_marcadores_banner():
    partidos = []
    ligas = ["basketball_nba", "soccer_uefa_champs_league", "soccer_epl", "soccer_spain_la_liga"]
    for liga in ligas:
        try:
            url = f"https://api.the-odds-api.com/v4/sports/{liga}/scores/?apiKey={ODDS_API_KEY}&daysFrom=1"
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                for e in r.json():
                    # SOLO agregar si no ha terminado
                    if not e.get('completed', False):
                        partidos.append({
                            "deporte": "NBA" if liga == "basketball_nba" else "Fútbol",
                            "local": e['home_team'], 
                            "visita": e['away_team'], 
                            "scores": e.get('scores'), 
                            "time": e['commence_time']
                        })
        except: 
            pass
    partidos.sort(key=lambda x: x['time'])
    return partidos[:3] # Mostrar máximo 3 en el banner

@st.cache_data(ttl=3600, show_spinner="Cargando estadísticas NBA...")
def cargar_metricas_nba():
    _TEAMS_RAW = teams.get_teams()
    _ABBR_TO_NAME = {t['abbreviation']: t['full_name'] for t in _TEAMS_RAW}
    try:
        df_eq = leaguedashteamstats.LeagueDashTeamStats(
            measure_type_detailed_defense='Advanced', per_mode_detailed='PerGame'
        ).get_data_frames()[0][['TEAM_NAME', 'OFF_RATING', 'DEF_RATING', 'PACE']]
    except:
        df_eq = pd.DataFrame({'TEAM_NAME': ['Boston Celtics', 'Golden State Warriors'], 'OFF_RATING': [118.5, 115.5], 'DEF_RATING': [110.2, 112.0], 'PACE': [98.5, 101.8]})
    try:
        df_jug = leaguedashplayerstats.LeagueDashPlayerStats(per_mode_detailed='PerGame').get_data_frames()[0]
        df_jug['TEAM_NAME'] = df_jug['TEAM_ABBREVIATION'].map(_ABBR_TO_NAME)
        df_jug = df_jug[['PLAYER_NAME', 'TEAM_ABBREVIATION', 'TEAM_NAME', 'PTS', 'FG3M', 'MIN', 'REB', 'AST']].dropna(subset=['TEAM_NAME'])
        df_jug = df_jug[df_jug['MIN'] > 15]
    except:
        df_jug = pd.DataFrame({'PLAYER_NAME': ['Jayson Tatum'], 'TEAM_ABBREVIATION': ['BOS'], 'TEAM_NAME': ['Boston Celtics'], 'PTS': [27.1], 'FG3M': [3.1], 'MIN': [35.5], 'REB': [8.5], 'AST': [5.0]})
    return df_eq, df_jug

# ============================================================
# RENDERIZAR BANNER (CORREGIDO EL HTML CRUDO)
# ============================================================
def mostrar_banner_vivo():
    partidos = obtener_marcadores_banner()
    if not partidos:
        return 
        
    html = '<div class="floating-live-banner">'
    html += '<div class="floating-live-title">🔴 En Vivo / Próximos</div>'
    
    for p in partidos:
        marcador = "vs"
        if p['scores'] and len(p['scores']) == 2:
            s_local = next((s['score'] for s in p['scores'] if s['name'] == p['local']), '0')
            s_visita = next((s['score'] for s in p['scores'] if s['name'] == p['visita']), '0')
            marcador = f"{s_visita} - {s_local}"
        
        abbr_local = p['local'][:3].upper()
        abbr_visita = p['visita'][:3].upper()
        hora = p['time'][11:16]
        
        # Se genera todo en una sola línea para que Markdown no lo tome como bloque de código
        html += f'<div class="floating-match"><div><div><span class="team-badge">{abbr_visita}</span> {p["visita"].split()[-1]}</div><div style="margin-top: 4px;"><span class="team-badge">{abbr_local}</span> {p["local"].split()[-1]}</div><div class="floating-time">{hora} UTC | {p["deporte"]}</div></div><div class="floating-score">{marcador}</div></div>'
        
    html += '</div>'
    # textwrap.dedent limpia cualquier espacio residual
    st.markdown(textwrap.dedent(html), unsafe_allow_html=True)

# Llamamos al banner
mostrar_banner_vivo()

# ============================================================
# ESCÁNER AUTOMÁTICO DE COMBINADAS
# ============================================================
def escanear_mercado_global():
    mejores_picks = []
    eventos_nba = obtener_cuotas_referencia("basketball_nba")
    for e in eventos_nba:
        h2h = next((m for m in e.get('bookmakers', [{}])[0].get('markets', []) if m['key'] == 'h2h'), None)
        if h2h:
            for o in h2h['outcomes']:
                prob_imp = 1 / o['price']
                prob_real = prob_imp / 1.04 
                c_justa = 1 / prob_real
                c_objetivo = c_justa * 1.05 
                ev = (prob_real * c_objetivo) - 1
                if ev > 0:
                    mejores_picks.append({
                        "Partido": f"{e['away_team']} @ {e['home_team']}",
                        "Fecha": format_fecha(e['commence_time']),
                        "Pick": o['name'],
                        "Deporte": "NBA",
                        "Prob": prob_real,
                        "CuotaObjetivo": c_objetivo,
                        "EV": ev * 100
                    })

    ligas_futbol = ["soccer_epl", "soccer_spain_la_liga", "soccer_uefa_champs_league", "soccer_conmebol_copa_libertadores"]
    for liga in ligas_futbol:
        eventos_f = obtener_cuotas_referencia(liga)
        for e in eventos_f:
            h2h = next((m for m in e.get('bookmakers', [{}])[0].get('markets', []) if m['key'] == 'h2h'), None)
            if h2h:
                margen = sum(1/o['price'] for o in h2h['outcomes'])
                for o in h2h['outcomes']:
                    prob_real = (1 / o['price']) / margen
                    c_justa = 1 / prob_real
                    c_objetivo = c_justa * 1.05
                    ev = (prob_real * c_objetivo) - 1
                    if ev > 0:
                        mejores_picks.append({
                            "Partido": f"{e['away_team']} vs {e['home_team']}",
                            "Fecha": format_fecha(e['commence_time']),
                            "Pick": o['name'],
                            "Deporte": "Fútbol",
                            "Prob": prob_real,
                            "CuotaObjetivo": c_objetivo,
                            "EV": ev * 100
                        })
                        
    df_picks = pd.DataFrame(mejores_picks)
    if df_picks.empty:
        return [], [], []
        
    df_picks = df_picks.sort_values(by="Prob", ascending=False)
    
    def generar_combos(picks_list, max_combos=3):
        if len(picks_list) < 2: return []
        combos = list(itertools.combinations(picks_list, 2))
        combos_evaluados = []
        for c in combos:
            c_cuota = c[0]['CuotaObjetivo'] * c[1]['CuotaObjetivo']
            c_prob = c[0]['Prob'] * c[1]['Prob']
            c_ev = (c_prob * c_cuota) - 1
            combos_evaluados.append({"combo": c, "cuota": c_cuota, "prob": c_prob, "ev": c_ev})
        combos_evaluados.sort(key=lambda x: x['ev'], reverse=True)
        return combos_evaluados[:max_combos]

    nba_picks = df_picks[df_picks['Deporte'] == 'NBA'].head(6).to_dict('records')
    futbol_picks = df_picks[df_picks['Deporte'] == 'Fútbol'].head(6).to_dict('records')
    
    combos_nba = generar_combos(nba_picks)
    combos_futbol = generar_combos(futbol_picks)
    
    combos_mixtas = []
    if nba_picks and futbol_picks:
        for n in nba_picks[:3]:
            for f in futbol_picks[:3]:
                c_cuota = n['CuotaObjetivo'] * f['CuotaObjetivo']
                c_prob = n['Prob'] * f['Prob']
                c_ev = (c_prob * c_cuota) - 1
                combos_mixtas.append({"combo": (n, f), "cuota": c_cuota, "prob": c_prob, "ev": c_ev})
        combos_mixtas.sort(key=lambda x: x['ev'], reverse=True)

    return combos_nba, combos_futbol, combos_mixtas[:3]

# ============================================================
# INTERFAZ
# ============================================================
st.sidebar.title("BetValue Pro")
deporte = st.sidebar.radio("Módulos", ["🏀 NBA", "⚽ Fútbol Global", "🇨🇴 Liga BetPlay", "🧩 Combinadas Automáticas", "📺 Centro de Partidos en Vivo"])
banca = st.sidebar.number_input("Banca Total (COP)", min_value=10000, value=200000, step=10000)

# ============================================================
# 1. NBA
# ============================================================
if deporte == "🏀 NBA":
    st.header("🏀 Baloncesto (NBA)")
    eventos = obtener_cuotas_referencia("basketball_nba")
    
    if not eventos:
        st.warning("No hay partidos disponibles.")
    else:
        opciones = {f"{e['away_team']} @ {e['home_team']} ({format_fecha(e['commence_time'])})": e for e in eventos}
        partido_str = st.selectbox("Selecciona un partido:", list(opciones.keys()))
        evento = opciones[partido_str]
        
        local, visita = evento['home_team'], evento['away_team']
        df_nba, df_jugadores = cargar_metricas_nba()

        d_l = df_nba[df_nba['TEAM_NAME'] == local].iloc[0] if not df_nba[df_nba['TEAM_NAME'] == local].empty else df_nba.iloc[0]
        d_v = df_nba[df_nba['TEAM_NAME'] == visita].iloc[0] if not df_nba[df_nba['TEAM_NAME'] == visita].empty else df_nba.iloc[1]
        
        pace_esp = (d_l['PACE'] + d_v['PACE']) / 2
        proj_pts_l = ((d_l['OFF_RATING'] + d_v['DEF_RATING']) / 2) * (pace_esp / 100)
        proj_pts_v = ((d_v['OFF_RATING'] + d_l['DEF_RATING']) / 2) * (pace_esp / 100)
        proj_total = proj_pts_l + proj_pts_v

        tab_mercados, tab_props = st.tabs(["Mercados Principales", "Player Props"])
        
        with tab_mercados:
            st.subheader(f"{visita} @ {local}")
            bookmaker = evento.get('bookmakers', [{}])[0]
            mercados = bookmaker.get('markets', [])
            h2h = next((m for m in mercados if m['key'] == 'h2h'), None)
            totals = next((m for m in mercados if m['key'] == 'totals'), None)

            col1, col2 = st.columns(2)
            with col1:
                if h2h:
                    st.markdown("#### 🏆 Ganador")
                    o_loc = next((o for o in h2h['outcomes'] if o['name'] == local), None)
                    o_vis = next((o for o in h2h['outcomes'] if o['name'] == visita), None)
                    margen = (1/o_loc['price']) + (1/o_vis['price'])
                    pr_l, pr_v = (1/o_loc['price'])/margen, (1/o_vis['price'])/margen
                    
                    st.markdown(f"**{local}** | Cuota Mín: <span class='fair-odds'>{1/pr_l:.2f}</span>", unsafe_allow_html=True)
                    c_l = st.number_input(f"Cuota BetPlay {local}", value=1/pr_l, step=0.01, key="nba_ml_l")
                    ev_l, k_l = calcular_ev_y_kelly(pr_l, c_l)
                    if ev_l > 0: st.success(f"EV: {ev_l:+.1f}% | ${banca*(k_l/100):,.0f}")
                    
                    st.markdown(f"**{visita}** | Cuota Mín: <span class='fair-odds'>{1/pr_v:.2f}</span>", unsafe_allow_html=True)
                    c_v = st.number_input(f"Cuota BetPlay {visita}", value=1/pr_v, step=0.01, key="nba_ml_v")
                    ev_v, k_v = calcular_ev_y_kelly(pr_v, c_v)
                    if ev_v > 0: st.success(f"EV: {ev_v:+.1f}% | ${banca*(k_v/100):,.0f}")

            with col2:
                if totals:
                    st.markdown("#### 📊 Totales")
                    o_over = next((o for o in totals['outcomes'] if o['name'] == 'Over'), None)
                    o_under = next((o for o in totals['outcomes'] if o['name'] == 'Under'), None)
                    linea = o_over.get('point', 0)
                    st.info(f"Línea Pinnacle: {linea} | Modelo: {proj_total:.1f}")
                    
                    margen_t = (1/o_over['price']) + (1/o_under['price'])
                    pr_o, pr_u = (1/o_over['price'])/margen_t, (1/o_under['price'])/margen_t
                    
                    st.markdown(f"**Over {linea}** | Cuota Mín: <span class='fair-odds'>{1/pr_o:.2f}</span>", unsafe_allow_html=True)
                    c_o = st.number_input("Cuota BetPlay Over", value=1/pr_o, step=0.01, key="nba_ou_o")
                    ev_o, k_o = calcular_ev_y_kelly(pr_o, c_o)
                    if ev_o > 0: st.success(f"EV: {ev_o:+.1f}% | ${banca*(k_o/100):,.0f}")
                    
                    st.markdown(f"**Under {linea}** | Cuota Mín: <span class='fair-odds'>{1/pr_u:.2f}</span>", unsafe_allow_html=True)
                    c_u = st.number_input("Cuota BetPlay Under", value=1/pr_u, step=0.01, key="nba_ou_u")
                    ev_u, k_u = calcular_ev_y_kelly(pr_u, c_u)
                    if ev_u > 0: st.success(f"EV: {ev_u:+.1f}% | ${banca*(k_u/100):,.0f}")

        with tab_props:
            st.markdown("### Player Props (Cálculo Propio)")
            st.info("Las cuotas de props no se pueden obtener gratis de los proveedores. Ingresa la cuota que ves en BetPlay para calcular el valor real.")
            j_local  = df_jugadores[df_jugadores['TEAM_NAME'] == local]
            j_visita = df_jugadores[df_jugadores['TEAM_NAME'] == visita]
            jugadores = pd.concat([j_local.sort_values('MIN', ascending=False).head(5), j_visita.sort_values('MIN', ascending=False).head(5)])
            
            jugador_sel = st.selectbox("Selecciona un Jugador:", jugadores['PLAYER_NAME'].tolist())
            row_j = jugadores[jugadores['PLAYER_NAME'] == jugador_sel].iloc[0]
            
            concepto = st.radio("Concepto:", ["Puntos", "Rebotes", "Asistencias", "Triples"], horizontal=True)
            stat_map = {"Puntos": ("PTS", "PTS"), "Rebotes": ("REB", "REB"), "Asistencias": ("AST", "AST"), "Triples": ("FG3M", "FG3M")}
            col_name = stat_map[concepto][0]
            
            media = float(row_j[col_name])
            linea = st.number_input(f"Línea {concepto} (Promedio: {media:.1f})", value=round(media - 0.5, 1), step=0.5)
            prob, sigma = prob_player_prop(media, linea, stat_type=col_name)
            
            st.markdown(f"**Probabilidad Modelo:** {prob*100:.1f}% | **Cuota Justa:** {1/prob:.2f}")
            c_bp = st.number_input(f"Cuota BetPlay para {jugador_sel} Over {linea}", value=1.85, step=0.01)
            ev, kelly = calcular_ev_y_kelly(prob, c_bp)
            
            if ev > 0:
                st.success(f"🔥 ¡VALOR! EV: {ev:+.2f}% | Apostar: ${banca*(kelly/100):,.0f} COP")
            else:
                st.error(f"❌ No hay valor. EV: {ev:+.2f}%")

# ============================================================
# 2. FÚTBOL GLOBAL
# ============================================================
elif deporte == "⚽ Fútbol Global":
    st.header("⚽ Fútbol - Ligas y Copas")
    
    ligas = {
        "Champions League": "soccer_uefa_champs_league",
        "Europa League": "soccer_uefa_europa_league",
        "Copa Libertadores": "soccer_conmebol_copa_libertadores",
        "Premier League (Inglaterra)": "soccer_epl",
        "La Liga (España)": "soccer_spain_la_liga",
        "Serie A (Italia)": "soccer_italy_serie_a",
        "Bundesliga (Alemania)": "soccer_germany_bundesliga",
        "Ligue 1 (Francia)": "soccer_france_ligue_one",
        "Primeira Liga (Portugal)": "soccer_portugal_primeira_liga",
        "Liga MX (México)": "soccer_mexico_ligamx",
        "MLS (USA)": "soccer_usa_mls"
    }
    
    liga_sel = st.selectbox("Selecciona la Liga o Copa:", list(ligas.keys()))
    eventos = obtener_cuotas_referencia(ligas[liga_sel])
    
    if not eventos:
        st.info(f"No hay partidos programados para {liga_sel} en este momento.")
    else:
        opciones = {f"{e['away_team']} vs {e['home_team']} ({format_fecha(e['commence_time'])})": e for e in eventos}
        partido_str = st.selectbox("Selecciona un partido:", list(opciones.keys()))
        evento = opciones[partido_str]
        
        local, visita = evento['home_team'], evento['away_team']
        st.subheader(f"{visita} vs {local}")
        
        bookmaker = evento.get('bookmakers', [{}])[0]
        mercados = bookmaker.get('markets', [])
        
        tab_h2h, tab_goles, tab_handicap, tab_manual = st.tabs(["Ganador (1X2)", "Goles (O/U)", "Handicap", "Córners/Tarjetas (Manual)"])
        
        with tab_h2h:
            h2h = next((m for m in mercados if m['key'] == 'h2h'), None)
            if h2h:
                o_loc = next((o for o in h2h['outcomes'] if o['name'] == local), None)
                o_vis = next((o for o in h2h['outcomes'] if o['name'] == visita), None)
                o_emp = next((o for o in h2h['outcomes'] if o['name'] == 'Draw'), None)
                
                if o_loc and o_vis and o_emp:
                    p_l, p_v, p_e = 1/o_loc['price'], 1/o_vis['price'], 1/o_emp['price']
                    margen = p_l + p_v + p_e
                    pr_l, pr_v, pr_e = p_l/margen, p_v/margen, p_e/margen
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"**Gana {local}** | Mín: <span class='fair-odds'>{1/pr_l:.2f}</span>", unsafe_allow_html=True)
                        c_l = st.number_input("Cuota BetPlay", value=1/pr_l, step=0.01, key="f_l")
                        ev_l, k_l = calcular_ev_y_kelly(pr_l, c_l)
                        if ev_l > 0: st.success(f"EV: {ev_l:+.1f}%")
                    with col2:
                        st.markdown(f"**Empate** | Mín: <span class='fair-odds'>{1/pr_e:.2f}</span>", unsafe_allow_html=True)
                        c_e = st.number_input("Cuota BetPlay", value=1/pr_e, step=0.01, key="f_e")
                        ev_e, k_e = calcular_ev_y_kelly(pr_e, c_e)
                        if ev_e > 0: st.success(f"EV: {ev_e:+.1f}%")
                    with col3:
                        st.markdown(f"**Gana {visita}** | Mín: <span class='fair-odds'>{1/pr_v:.2f}</span>", unsafe_allow_html=True)
                        c_v = st.number_input("Cuota BetPlay", value=1/pr_v, step=0.01, key="f_v")
                        ev_v, k_v = calcular_ev_y_kelly(pr_v, c_v)
                        if ev_v > 0: st.success(f"EV: {ev_v:+.1f}%")
        
        with tab_goles:
            totals = next((m for m in mercados if m['key'] == 'totals'), None)
            if totals:
                o_over = next((o for o in totals['outcomes'] if o['name'] == 'Over'), None)
                o_under = next((o for o in totals['outcomes'] if o['name'] == 'Under'), None)
                if o_over and o_under:
                    linea_g = o_over.get('point', 2.5)
                    st.markdown(f"#### ⚽ Over/Under Goles ({linea_g})")
                    margen_t = (1/o_over['price']) + (1/o_under['price'])
                    pr_o, pr_u = (1/o_over['price'])/margen_t, (1/o_under['price'])/margen_t
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown(f"**Over {linea_g}** | Mín: <span class='fair-odds'>{1/pr_o:.2f}</span>", unsafe_allow_html=True)
                        c_o = st.number_input("Cuota BetPlay Over", value=1/pr_o, step=0.01, key="f_o")
                        ev_o, k_o = calcular_ev_y_kelly(pr_o, c_o)
                        if ev_o > 0: st.success(f"EV: {ev_o:+.1f}%")
                    with col2:
                        st.markdown(f"**Under {linea_g}** | Mín: <span class='fair-odds'>{1/pr_u:.2f}</span>", unsafe_allow_html=True)
                        c_u = st.number_input("Cuota BetPlay Under", value=1/pr_u, step=0.01, key="f_u")
                        ev_u, k_u = calcular_ev_y_kelly(pr_u, c_u)
                        if ev_u > 0: st.success(f"EV: {ev_u:+.1f}%")
            else:
                st.info("No hay cuotas de Totales para este partido.")
                
        with tab_handicap:
            spreads = next((m for m in mercados if m['key'] == 'spreads'), None)
            if spreads:
                st.markdown("#### ⚖️ Handicap Asiático")
                for o in spreads['outcomes']:
                    prob_imp = 1 / o['price']
                    margen_h = sum(1/x['price'] for x in spreads['outcomes'])
                    prob_real = prob_imp / margen_h
                    c_justa = 1 / prob_real
                    st.markdown(f"**{o['name']} ({o['point']:+})** | Mín: <span class='fair-odds'>{c_justa:.2f}</span>", unsafe_allow_html=True)
                    c_bp = st.number_input(f"Cuota BetPlay {o['name']} {o['point']:+}", value=c_justa, step=0.01, key=f"h_{o['name']}")
                    ev_h, k_h = calcular_ev_y_kelly(prob_real, c_bp)
                    if ev_h > 0: st.success(f"EV: {ev_h:+.1f}%")
            else:
                st.info("No hay cuotas de Handicap para este partido.")
                
        with tab_manual:
            st.markdown("#### 🚩 Córners y Tarjetas (Cálculo Manual)")
            st.info("Las APIs gratuitas no ofrecen cuotas de córners o tarjetas. Usa esta calculadora con Poisson ingresando los promedios que investigues.")
            col1, col2 = st.columns(2)
            with col1:
                tipo_m = st.selectbox("Mercado", ["Córners", "Tarjetas"])
                linea_m = st.number_input("Línea (ej. 9.5)", value=9.5 if tipo_m == "Córners" else 4.5, step=0.5)
            with col2:
                prom_l = st.number_input("Promedio Local", value=5.5 if tipo_m == "Córners" else 2.2)
                prom_v = st.number_input("Promedio Visita", value=4.5 if tipo_m == "Córners" else 2.8)
                cuota_m = st.number_input("Cuota BetPlay", value=1.85, step=0.01)
                
            if st.button("Calcular"):
                lambda_t = prom_l + prom_v
                prob_m = 1 - poisson.cdf(int(linea_m), lambda_t)
                ev_m, k_m = calcular_ev_y_kelly(prob_m, cuota_m)
                st.markdown(f"**Probabilidad Over {linea_m}:** {prob_m*100:.1f}% | **Cuota Justa:** {1/prob_m:.2f}")
                if ev_m > 0: st.success(f"EV: {ev_m:+.1f}% | Apostar: ${banca*(k_m/100):,.0f} COP")
                else: st.error(f"EV: {ev_m:+.1f}% | No hay valor.")

# ============================================================
# 3. LIGA BETPLAY (MANUAL)
# ============================================================
elif deporte == "🇨🇴 Liga BetPlay":
    st.header("🇨🇴 Liga BetPlay (Cálculo Manual)")
    st.info("BetPlay no tiene API pública de fútbol colombiano. Usa esta calculadora con los promedios precargados.")
    
    equipos_col = {
        "Millonarios": {"goles": 1.3, "corners": 5.2},
        "Atlético Nacional": {"goles": 1.5, "corners": 5.8},
        "Junior": {"goles": 1.2, "corners": 4.9},
        "América de Cali": {"goles": 1.1, "corners": 4.5},
        "Santa Fe": {"goles": 1.0, "corners": 4.8},
        "Deportivo Cali": {"goles": 1.2, "corners": 5.0},
        "Medellín": {"goles": 1.3, "corners": 5.1}
    }
    
    col1, col2 = st.columns(2)
    with col1:
        eq_local = st.selectbox("Equipo Local", list(equipos_col.keys()), index=0)
        eq_visita = st.selectbox("Equipo Visitante", list(equipos_col.keys()), index=1)
        mercado = st.selectbox("Mercado", ["Córners Totales", "Goles Totales"])
        
    with col2:
        if mercado == "Córners Totales":
            media_l = st.number_input(f"Proyección Córners {eq_local}", value=equipos_col[eq_local]["corners"], step=0.1)
            media_v = st.number_input(f"Proyección Córners {eq_visita}", value=equipos_col[eq_visita]["corners"], step=0.1)
            linea = st.number_input("Línea BetPlay", value=9.5, step=0.5)
        else:
            media_l = st.number_input(f"Proyección Goles {eq_local}", value=equipos_col[eq_local]["goles"], step=0.1)
            media_v = st.number_input(f"Proyección Goles {eq_visita}", value=equipos_col[eq_visita]["goles"], step=0.1)
            linea = st.number_input("Línea BetPlay", value=2.5, step=0.5)
        cuota_bp = st.number_input("Cuota BetPlay", value=1.85, step=0.01)
        
    if st.button("Calcular Valor"):
        lambda_total = media_l + media_v
        prob = 1 - poisson.cdf(int(linea), lambda_total)
        ev, kelly = calcular_ev_y_kelly(prob, cuota_bp)
        
        st.markdown(f"""
        <div class="metric-box">
            <h3>{eq_local} vs {eq_visita}</h3>
            <p>Proyección Total: <b>{lambda_total:.1f}</b> | Línea: <b>{linea}</b></p>
            <p>Probabilidad: <b>{prob*100:.1f}%</b> | Cuota Justa: <b>{1/prob:.2f}</b></p>
            <h2 style="color: {'#4ade80' if ev > 0 else '#f87171'};">EV: {ev:+.2f}%</h2>
        </div>
        """, unsafe_allow_html=True)

# ============================================================
# 4. COMBINADAS AUTOMÁTICAS
# ============================================================
elif deporte == "🧩 Combinadas Automáticas":
    st.header("🧩 Escáner de Combinadas Inteligentes")
    st.markdown("El sistema escanea el mercado, calcula el valor y te arma las **3 mejores combinadas** por categoría.")
    
    if st.button("🔍 Escanear Mercado y Generar Combinadas"):
        with st.spinner("Buscando valor y generando combinaciones..."):
            combos_nba, combos_futbol, combos_mixtas = escanear_mercado_global()
            
            st.markdown("### 🏀 Mejores Combinadas de NBA")
            if combos_nba:
                for idx, combo_info in enumerate(combos_nba):
                    c = combo_info['combo']
                    texto = "".join([f"<li><b>{pick['Pick']}</b> ({pick['Partido']}) - {pick['Fecha']} | Obj: {pick['CuotaObjetivo']:.2f}</li>" for pick in c])
                    
                    st.markdown(f"""
                    <div class="combo-box">
                        <div class="combo-title">Opción {idx+1} (2 selecciones)</div>
                        <ul>{texto}</ul>
                        <hr style="border-color: #4338ca;">
                        <p><b>Cuota Total Objetivo:</b> {combo_info['cuota']:.2f}</p>
                        <p><b>Probabilidad:</b> {combo_info['prob']*100:.1f}% | <b>EV:</b> <span style="color:#4ade80;">{combo_info['ev']*100:+.2f}%</span></p>
                        <p><b>Inversión Sugerida (Kelly 25%):</b> ${banca * ((combo_info['ev'] / (combo_info['cuota'] - 1)) * 0.25):,.0f} COP</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.write("No hay combinadas NBA viables en este momento.")
                
            st.markdown("### ⚽ Mejores Combinadas de Fútbol")
            if combos_futbol:
                for idx, combo_info in enumerate(combos_futbol):
                    c = combo_info['combo']
                    texto = "".join([f"<li><b>{pick['Pick']}</b> ({pick['Partido']}) - {pick['Fecha']} | Obj: {pick['CuotaObjetivo']:.2f}</li>" for pick in c])
                    
                    st.markdown(f"""
                    <div class="combo-box">
                        <div class="combo-title">Opción {idx+1} (2 selecciones)</div>
                        <ul>{texto}</ul>
                        <hr style="border-color: #4338ca;">
                        <p><b>Cuota Total Objetivo:</b> {combo_info['cuota']:.2f}</p>
                        <p><b>Probabilidad:</b> {combo_info['prob']*100:.1f}% | <b>EV:</b> <span style="color:#4ade80;">{combo_info['ev']*100:+.2f}%</span></p>
                        <p><b>Inversión Sugerida (Kelly 25%):</b> ${banca * ((combo_info['ev'] / (combo_info['cuota'] - 1)) * 0.25):,.0f} COP</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.write("No hay combinadas de fútbol viables en este momento.")

            st.markdown("### 🌟 Mejores Combinadas Mixtas (NBA + Fútbol)")
            if combos_mixtas:
                for idx, combo_info in enumerate(combos_mixtas):
                    c = combo_info['combo']
                    texto = "".join([f"<li><b>{pick['Pick']}</b> ({pick['Partido']}) - {pick['Fecha']} | Obj: {pick['CuotaObjetivo']:.2f}</li>" for pick in c])
                    
                    st.markdown(f"""
                    <div class="combo-box">
                        <div class="combo-title">Opción {idx+1} (1 NBA + 1 Fútbol)</div>
                        <ul>{texto}</ul>
                        <hr style="border-color: #4338ca;">
                        <p><b>Cuota Total Objetivo:</b> {combo_info['cuota']:.2f}</p>
                        <p><b>Probabilidad:</b> {combo_info['prob']*100:.1f}% | <b>EV:</b> <span style="color:#4ade80;">{combo_info['ev']*100:+.2f}%</span></p>
                        <p><b>Inversión Sugerida (Kelly 25%):</b> ${banca * ((combo_info['ev'] / (combo_info['cuota'] - 1)) * 0.25):,.0f} COP</p>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.write("No hay combinadas mixtas viables en este momento.")

# ============================================================
# 5. CENTRO DE PARTIDOS EN VIVO
# ============================================================
elif deporte == "📺 Centro de Partidos en Vivo":
    st.header("📺 Centro de Partidos en Vivo")
    st.markdown("Marcadores en tiempo real y próximos partidos de NBA y las principales ligas de fútbol.")
    
    deportes_vivo = {
        "NBA": "basketball_nba",
        "Premier League": "soccer_epl",
        "La Liga": "soccer_spain_la_liga",
        "Champions League": "soccer_uefa_champs_league",
        "Copa Libertadores": "soccer_conmebol_copa_libertadores"
    }
    
    for nombre, key in deportes_vivo.items():
        with st.expander(f"🔴 {nombre}", expanded=True):
            url = f"https://api.the-odds-api.com/v4/sports/{key}/scores/?apiKey={ODDS_API_KEY}&daysFrom=1"
            try:
                r = requests.get(url, timeout=10)
                eventos_vivo = r.json() if r.status_code == 200 else []
            except:
                eventos_vivo = []
                
            # Filtrar solo los NO terminados
            eventos_activos = [e for e in eventos_vivo if not e.get('completed', False)]
            
            if not eventos_activos:
                st.write("No hay partidos en vivo o programados para hoy.")
                continue
                
            for e in eventos_activos:
                estado = "EN VIVO / PRÓXIMO"
                color_estado = "#ef4444"
                
                scores = e.get('scores')
                if scores and len(scores) == 2:
                    score_home = next((s['score'] for s in scores if s['name'] == e['home_team']), '0')
                    score_away = next((s['score'] for s in scores if s['name'] == e['away_team']), '0')
                    marcador = f"{score_away} - {score_home}"
                else:
                    marcador = "vs"
                
                st.markdown(f"""
                <div class="live-box">
                    <p style="margin:0; font-size:0.9em; color:{color_estado};"><b>{estado}</b> | {format_fecha(e['commence_time'])}</p>
                    <p style="margin:5px 0; font-size:1.1em;">
                        <b>{e['away_team']}</b> <span class="live-score">{marcador}</span> <b>{e['home_team']}</b>
                    </p>
                </div>
                """, unsafe_allow_html=True)