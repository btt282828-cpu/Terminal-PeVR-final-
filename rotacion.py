#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ROTACION - Smart-Money Flow Terminal (version de escritorio)
============================================================
Descarga datos REALES de fin de dia (gratis, sin API key) de:
  1) Stooq  (fuente principal, sin key)
  2) Yahoo / yfinance  (respaldo automatico, sin key)

Calcula la rotacion sectorial estilo RRG (RS-Ratio / RS-Momentum),
detecta giros tempranos, amplitud, apetito de riesgo y un regimen
macro automatico deducido del propio mercado. Genera un panel HTML
con el mismo aspecto del terminal y lo abre en tu navegador.

USO
---
  python rotacion.py

Se ejecuta despues del cierre de Wall Street (datos de fin de dia).
La primera vez instala solas las librerias que falten.

OPCIONAL (macro mas rico): pon tu key gratuita de FRED abajo en CONFIG.
"""

import sys, subprocess, importlib, os, json, math, time, webbrowser, datetime as dt

# ----------------------------------------------------------------------
# CONFIG  (lo unico que quizas quieras tocar)
# ----------------------------------------------------------------------
BENCH = "SPY"                                   # indice de referencia
SECTORS = ["XLK","XLF","XLE","XLV","XLY","XLP","XLI","XLB","XLU","XLRE","XLC"]
# Tematicos / regionales: China, Emergentes, Espacio-Defensa, 7 Magnificos
THEMATIC = ["FXI","EEM","ITA","MAGS","EWG","EWP","COPX","URA","LIT"]   # EWG=Alemania(DAX), EWP=España(IBEX); COPX=cobre, URA=uranio, LIT=litio
# Extra utiles para detectar rotaciones (viajes, semis, banca regional, biotech, mineras oro, software, vivienda, China tech)
EXTRA = ["JETS","SMH","KRE","XBI","GDX","IGV","SOXX","ITB","KWEB","GRID","PAVE","FIW","CGW","HYDR",
         "XRT","XOP","OIH","ARKF","ARKK","CIBR","SKYY","BOTZ","TAN","ICLN","FAN","XME","SIL","SLV","EWJ","INDA","EWZ","VGK","IBIT","DRIV","EWY","MOO","QTUM"]   # ...+ infraestructura de IA: red eléctrica (GRID), construcción (PAVE), agua EE.UU. (FIW), global (CGW) e hidrógeno (HYDR) + Bitcoin (IBIT)
SATELLITES = ["IWM","TLT","GLD","HYG","UUP"]     # para riesgo y regimen macro

# Acciones de agua (componentes de FIW) que CREO disponibles como CFD en XTB.
# OJO: no puedo verificarlo en vivo desde aqui y XTB cambia su catalogo; esto es un
# punto de partida con las large-caps mas liquidas. VERIFICALO tu en el buscador de
# instrumentos de XTB antes de operar. Anade o quita tickers a mano segun lo que veas.
XTB_CFD_AGUA = {"ECL","ROP","AWK","FERG","XYL","A","WAT","IDXX","IEX","PNR","MAS","J","ACM","VLTO"}

# === GRUPOS para organizar los paneles (selector del RRG y bloques de tablas) ===
GRUPO_SECTORES = SECTORS + ["IWM"]                                   # 11 basicos + small caps
GRUPO_SUBSECTORES = ["XBI","KRE","JETS","ITB","ITA","XRT","XOP","OIH"]                 # temas EE.UU. no-IA (biotech, banca regional, viajes, vivienda, defensa)
GRUPO_TECH        = ["SMH","SOXX","IGV","MAGS","ARKF","ARKK","CIBR","SKYY","BOTZ","DRIV","QTUM"]  # tech e innovacion: chips, software, megacaps, fintech, innovacion, ciber, nube, robotica
GRUPO_LIMPIA      = ["TAN","ICLN","FAN","LIT","HYDR"]                               # energia limpia: solar, limpia global, eolica, baterias, hidrogeno
GRUPO_MATERIALES  = ["XME","GDX","COPX","URA","SIL","SLV","MOO"]                    # materiales y metales: mineria, oro, cobre, uranio, plata, agronegocio
GRUPO_IAINFRA     = ["GRID","PAVE","FIW","CGW"]                                     # infraestructura: red electrica, construccion, agua EE.UU., agua global
COMMODITIES = ["COPX","URA","LIT"]
GRUPO_INTERNAC = ["EEM","FXI","KWEB","EWG","EWP","EWJ","INDA","EWZ","VGK","EWY"]    # internacional: emergentes, China, Alemania, Espana, Japon, India, Brasil, Europa, Corea (chivato de semis)
GRUPO_REFUGIO  = ["UUP","TLT","HYG","GLD","IBIT"]                                          # macro / refugio: dolar, bonos largos, credito HY, oro
# === SINTETICOS: cestas fusionadas de sectores interconectados (suben y bajan juntos) ===
# Cada sintetico es un indice equiponderado de sus miembros -> UNA bolita en el RRG que resume el tema.
# Solo para LECTURA (RRG y monitor): no entran en scoring, cartera, candidato ni suelo.
SINTETICOS = {
    "S-FISICO": {"nombre": "Economía física", "corto": "Sint. Física",
                 "members": ["XLI", "XLB", "XME", "COPX", "PAVE", "GRID"],
                 "desc": "industrial + materiales + minería/cobre + infraestructura + red eléctrica"},
    "S-TECH":   {"nombre": "Tecnología amplia", "corto": "Sint. Tech",
                 "members": ["XLK", "SMH", "SOXX", "IGV", "CIBR", "SKYY"],
                 "desc": "tecnología + chips + software + ciber + nube"},
    "S-CICLO":  {"nombre": "Ciclo consumidor", "corto": "Sint. Ciclo",
                 "members": ["XLY", "XRT", "JETS", "ITB", "IWM"],
                 "desc": "consumo discrecional + retail + viajes + vivienda + small caps"},
    "S-DEFENSA": {"nombre": "Refugio defensivo", "corto": "Sint. Defensa",
                  "members": ["XLP", "XLU", "XLV", "GLD", "TLT"],
                  "desc": "básico + utilities + salud + oro + bonos largos"},
    "S-CHINA":  {"nombre": "China total", "corto": "Sint. China",
                 "members": ["FXI", "KWEB"],
                 "desc": "China amplia + China tech (tu tesis en una bolita)"},
}
CARTERA_PESO_MAX = 34   # tope de % por posicion en la cartera semanal; lo que no se reparte va a LIQUIDEZ
# --- SECTORES EXPLOSIVOS: los que mas se mueven cuando rebotan (beta alta). El modo cazador de suelos
#     vigila SOLO estos tras una caida fuerte, para entrar en el giro en vez de estar siempre invertido. ---
SECTORES_EXPLOSIVOS = ["SMH", "SOXX", "XBI", "ARKK", "ARKF", "KWEB", "FXI", "XME", "COPX", "GDX",
                       "URA", "SLV", "TAN", "IBIT", "QTUM", "LABU", "MAGS", "IGV", "KRE", "TNA"]
# etiqueta legible del "porque son explosivos"
EXPLOSIVO_TIPO = {
    "SMH": "chips", "SOXX": "chips", "MAGS": "megacaps tech", "IGV": "software", "QTUM": "cuántica",
    "ARKK": "innovación", "ARKF": "fintech", "XBI": "biotech", "LABU": "biotech x3",
    "KWEB": "China tech", "FXI": "China", "XME": "metales", "COPX": "cobre", "GDX": "oro mineras",
    "URA": "uranio", "SLV": "plata", "TAN": "solar", "IBIT": "bitcoin", "KRE": "banca regional", "TNA": "small caps x3",
}
                        # (regla anti-anomalia: si el filtro de flujo deja 1-2 supervivientes, no les cae el 100%)
# --- Chequeo de COHERENCIA SECTORIAL: si un ETF entra en cartera por su fuerza como bloque pero su
#     tema dominante esta DEBILITANDOSE/REZAGADO en el mercado US, se avisa (no se veta: tu decides).
#     Mapa: ETF -> (tema legible, [ETFs-US espejo de ese tema]). Solo para internacionales/tematicos. ---
COHERENCIA_TEMA = {
    "EWY":  ("semiconductores", ["SMH", "SOXX"]),          # Corea = Samsung + SK Hynix
    "EWT":  ("semiconductores", ["SMH", "SOXX"]),          # Taiwan = TSMC (por si se anade)
    "INDA": ("tecnología", ["XLK", "IGV"]),                # India = mucho IT services
    "KWEB": ("tecnología china", ["XLK"]),
    "FXI":  ("financiero/China", ["XLF"]),
    "EWG":  ("industrial", ["XLI"]),                        # Alemania = industria/autos
    "EWJ":  ("financiero/industrial", ["XLF", "XLI"]),     # Japon = value, no tech
    "EWP":  ("financiero", ["XLF"]),                        # Espana = bancos
    "VGK":  ("financiero/industrial", ["XLF", "XLI"]),
    "EWZ":  ("materiales/energía", ["XME", "XLE"]),         # Brasil = commodities
    "SMH":  ("semiconductores", ["SMH"]),
    "SOXX": ("semiconductores", ["SMH"]),
    "IGV":  ("software", ["IGV"]),
    "DRIV": ("automoción/tech", ["XLK", "XLY"]),
    "QTUM": ("tecnología", ["XLK"]),
}
GRUPO = {}
for _s in GRUPO_SECTORES:    GRUPO[_s] = "sector"
for _s in GRUPO_SUBSECTORES: GRUPO[_s] = "subsector"
for _s in GRUPO_TECH:        GRUPO[_s] = "tech"
for _s in GRUPO_LIMPIA:      GRUPO[_s] = "limpia"
for _s in GRUPO_MATERIALES:  GRUPO[_s] = "materiales"
for _s in GRUPO_IAINFRA:     GRUPO[_s] = "iainfra"
for _s in GRUPO_INTERNAC:    GRUPO[_s] = "internac"
for _s in GRUPO_REFUGIO:     GRUPO[_s] = "refugio"
for _s in SINTETICOS:        GRUPO[_s] = "sintetico"
GRUPO_NOMBRE = {"sector": "Sectores", "subsector": "Subsectores EE.UU.", "tech": "Tech e innovación", "limpia": "Energía limpia", "materiales": "Materiales y metales", "iainfra": "IA infraestructura", "internac": "Internacional", "refugio": "Macro / refugio", "sintetico": "Sintéticos"}
GRUPO_ORDEN = ("sector", "subsector", "tech", "limpia", "materiales", "iainfra", "internac", "refugio", "sintetico")

# Clasificacion en 3 grupos para los paneles (selector del RRG y bloques de las tablas)
GROUPS = {
    "sector":        ["XLK","XLF","XLE","XLV","XLY","XLP","XLI","XLB","XLU","XLRE","XLC","IWM"],
    "subsector":     ["SMH","SOXX","IGV","XBI","KRE","JETS","ITB","MAGS","ITA"],
    "internacional": ["EEM","FXI","KWEB","EWG","EWP","TLT","HYG","UUP","GLD","GDX","COPX","URA","LIT","IBIT"],
}
GROUP_LABEL = {"sector": "Sectores", "subsector": "Subsectores EE.UU.", "internacional": "Internacional y macro"}
GROUP_OF = {t: g for g, lst in GROUPS.items() for t in lst}
def group_of(sym):
    return GROUP_OF.get(sym, "subsector")
WEEKS = 70                                       # semanas de historico a usar
TAIL = 8                                         # longitud de la estela del RRG
RRG_SOLO_SECTORES = False                        # True = en el RRG solo los 11 sectores SPDR (mas limpio)
TOPUP_YAHOO = True                               # rellenar la ultima barra que falte con Yahoo (frescura); util en local, en la nube puede limitar
DATA_PRIMARY = "yahoo"                            # fuente principal: "yahoo" (mas fresco; Stooq no responde en algunas IPs/regiones) o "stooq". La otra queda de respaldo
# --- Acciones lideres por sector (fuerza relativa estilo RS Rating 1-99) ---
STOCK_LEADERS = True                             # añade el panel de acciones lideres (descarga mas datos)
LEADERS_TOP_N = 6                                # cuantas acciones mostrar por sector
LEADERS_MIN_RS = 90                              # umbral de "lider" (percentil)
# Universo para calcular el percentil RS:
#   "sp500"  = las ~500 del S&P 500 (percentil de mercado real; mas lento; por defecto)
#   "sector" = ~164 acciones de SECTOR_STOCKS (mas rapido)
RS_UNIVERSE = "sp500"
SP500_FALLBACK = ["AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","AVGO","TSLA","BRK-B","JPM","LLY","V",
    "UNH","XOM","MA","COST","HD","PG","JNJ","ORCL","ABBV","NFLX","BAC","KO","CRM","CVX","MRK","AMD","PEP",
    "TMO","WFC","ADBE","LIN","CSCO","ACN","MCD","ABT","DHR","GE","TXN","DIS","INTU","QCOM","CAT","VZ","AMGN",
    "PM","IBM","NOW","CMCSA","UNP","SPGI","RTX","PFE","HON","GS","LOW","T","COP","ISRG","BKNG","NEE","UBER",
    "MS","BLK","AXP","SCHW","ETN","C","TJX","ADP","DE","BSX","MDT","GILD","LMT","SYK","VRTX","REGN","CB",
    "MU","PLD","ADI","MMC","SBUX","PANW","BA","SO","AMAT","KLAC","LRCX","DUK","CEG","SHW","ICE","WM","ANET",
    "CRWD","CDNS","SNPS","MRVL","NKE","FCX","NEM","CL","TGT","ORLY","CMG","MCO","APH","FTNT","WELL","EQIX",
    "AON","CME","PNC","USB","TFC","COF","AIG","MET","PRU","AFL","ALL","TRV","BK","ITW","TT","CMI","ROP","CARR",
    "OTIS","GEV","PCAR","PWR","AME","FAST","ODFL","CTAS","RSG","VRSK","EFX","URI","NSC","EMR","GD","FDX","PH",
    "MDLZ","MO","STZ","SYY","KR","ADM","HSY","KDP","MNST","CHD","CLX","K","MKC","TAP","HRL","KMB","GIS","KHC",
    "VLO","MPC","PSX","OXY","KMI","DVN","OKE","HAL","BKR","FANG","TRGP","WMB","SLB","EOG","CTRA","EQT",
    "ELV","CI","HUM","CNC","MOH","CVS","BDX","EW","ZBH","BAX","DXCM","IDXX","IQV","A","MTD","WAT","HOLX","ALGN",
    "STE","RVTY","COO","ZTS","DGX","LH","WST","TFX","HSIC","XRAY","MRNA","BIIB","INCY","RMD","BMY","GEHC",
    "GM","F","ROST","YUM","HLT","AZO","RCL","CCL","NCLH","DHI","LEN","NVR","PHM","MGM","LVS","WYNN","APTV",
    "LULU","TSCO","DRI","DPZ","GRMN","EXPE","POOL","BBY","ULTA","KMX","DECK","RL","TPR","WHR","MHK","MAR",
    "EA","TTWO","WBD","OMC","IPG","LYV","FOXA","FOX","NWSA","MTCH","PARA","CHTR","TMUS","CMCSA","VZ","DIS",
    "INTC","TXN","QCOM","AMAT","MCHP","MPWR","ON","GLW","HPQ","HPE","DELL","WDC","STX","NTAP","KEYS","CDW",
    "TYL","FSLR","ENPH","TER","SWKS","QRVO","ZBRA","TRMB","PTC","ANSS","AKAM","JNPR","FFIV","GEN","NXPI",
    "BRK-B","SPG","DLR","O","PSA","CCI","VICI","EXR","AVB","EQR","INVH","MAA","ESS","UDR","ARE","VTR","DOC",
    "IRM","SBAC","REG","KIM","FRT","HST","CPT","BXP","AMT",
    "VMC","MLM","PPG","ALB","IFF","IP","PKG","AVY","BALL","AMCR","CF","MOS","FMC","EMN","CE","LYB","STLD","NUE",
    "DOW","DD","CTVA","APD","ECL",
    "D","VST","SRE","EXC","XEL","ED","PEG","WEC","ES","AEE","DTE","PPL","FE","CMS","CNP","ATO","NI","LNT",
    "EVRG","AES","PNW","NRG","AEP",
    "GD","NOC","FDX","UPS","CSX","ADP","EMR","TT","CMI","ROP","PAYX","BR","EXPD","CHRW","DAL","UAL","LUV",
    "TDG","GWW","JCI","PNR","ALLE","NDSN","ROK","SNA","SWK","TXT","MAS","BLDR","AXON","LHX","LDOS","J","DOV","XYL","IR",
    "AMP","TROW","BEN","IVZ","WTW","ACGL","HIG","CINF","L","NDAQ","MKTX","CBOE","FIS","FI","GPN","PYPL","SYF","DFS",
    "FITB","HBAN","RF","CFG","KEY","MTB","NTRS","STT","PFG","PGR","AFL"]
SECTOR_STOCKS = {
    "XLK":  ["AAPL","MSFT","NVDA","AVGO","ORCL","CRM","AMD","ADBE","ACN","CSCO","INTC","IBM","QCOM","NOW","TXN"],
    "XLF":  ["BRK-B","JPM","V","MA","BAC","WFC","GS","AXP","MS","SPGI","BLK","C","SCHW","CB","PGR"],
    "XLE":  ["XOM","CVX","COP","SLB","EOG","MPC","PSX","WMB","OXY","VLO","KMI","DVN"],
    "XLV":  ["LLY","UNH","JNJ","ABBV","MRK","TMO","ABT","ISRG","DHR","PFE","AMGN","BMY","GILD","VRTX","CVS"],
    "XLY":  ["AMZN","TSLA","HD","MCD","BKNG","LOW","NKE","SBUX","TJX","CMG","ORLY","MAR","GM","F"],
    "XLP":  ["COST","WMT","PG","KO","PEP","PM","MDLZ","CL","MO","TGT","KMB","GIS","KHC"],
    "XLI":  ["GE","CAT","RTX","HON","UNP","BA","DE","UBER","ETN","LMT","UPS","ADP","NOC","CSX","EMR"],
    "XLB":  ["LIN","SHW","FCX","ECL","NEM","APD","CTVA","DOW","NUE","DD","VMC","MLM"],
    "XLU":  ["NEE","SO","DUK","CEG","AEP","D","VST","SRE","EXC","XEL","ED","PEG"],
    "XLRE": ["PLD","AMT","EQIX","WELL","SPG","DLR","O","PSA","CCI","CBRE","VICI","EXR"],
    "XLC":  ["META","GOOGL","NFLX","DIS","TMUS","T","VZ","CMCSA","CHTR","EA","TTWO","WBD"],
    "SMH":  ["NVDA","AVGO","AMD","QCOM","TXN","MU","LRCX","AMAT","KLAC","ADI","MRVL","NXPI"],
    "IGV":  ["MSFT","ORCL","CRM","NOW","ADBE","PANW","CRWD","INTU","SNPS","CDNS","FTNT","WDAY","DDOG","TEAM"],
    "FIW":  ["AWK","ROP","XYL","WAT","FERG","A","VLTO","PNR","MLI","IDXX","ECL","IEX","J","MAS","WMS","STN","CNM","WTS","ACM","TTEK","BMI","ITRI","FELE","MWA","ZWS"],
    "XBI":  ["VRTX","REGN","GILD","ALNY","EXEL","UTHR","INSM","NBIX","ARWR","BEAM","ALKS","TGTX","KRYS","INCY","IONS","BMRN","SRPT","HALO"],
    "KRE":  ["TFC","FITB","RF","HBAN","KEY","CFG","MTB","WBS","ZION","EWBC","WAL","FHN","CFR","ONB","PB"],
    "JETS": ["DAL","UAL","AAL","LUV","ALK","SKYW","ALGT","JBLU","BA","BKNG","EXPE","ABNB"],
    "ITB":  ["DHI","LEN","NVR","PHM","TOL","KBH","MTH","TMHC","BLDR","SHW","MAS","LOW","HD","MHK"],
    "ITA":  ["RTX","BA","LMT","GD","NOC","GE","TDG","LHX","HWM","AXON","HEI","TXT","CW","HII","LDOS"],
    # Red electrica (GRID): grandes de referencia + las pequenas/medianas del tema (POWL, AMSC, MYRG, ITRI, IESC, PRIM, AZZ)
    "GRID": ["ETN","PWR","VRT","HUBB","NVT","GNRC","ITRI","AMSC","POWL","MYRG","PRIM","IESC","AZZ"],
}
FRED_API_KEY = ""                                # DEJAR VACIO: la key va en los Secrets de GitHub (FRED_API_KEY), NO aqui (repo publico)
ISM_MANUAL = 54.0                                # ISM manufacturas (no esta limpio en FRED gratis): actualizalo a mano el 1er dia habil de cada mes. Ult.: 54.0 (mayo-2026)
# --- Analisis con IA (opcional): comentario automatico en el panel ---
ANTHROPIC_API_KEY = ""                           # opcional: https://console.anthropic.com (de pago por uso)
AI_MODEL = "claude-haiku-4-5"                    # modelo del comentario corto (editable segun tu cuenta)
# --- IA AUTOMATICA en Modo Claude: al ejecutar el terminal, se lanza el prompt MAESTRO con tus datos ---
IA_AUTO = True                                   # ejecutar automaticamente el prompt maestro en cada build (si hay API key)
IA_AUTO_EXTRA = ["sectorial","flujos","liderazgo","ocultas","ciclo","insiders","narrativas","multifactor"]  # TODOS los prompts se auto-ejecutan (deja [] para solo el maestro; cada uno suma tiempo y coste)
IA_AUTO_MODEL = "claude-sonnet-4-6"              # modelo del analisis largo. Alternativas: "claude-opus-4-6" (mejor y mas caro), "claude-haiku-4-5" (mas barato)
IA_WEB_SEARCH = True                             # permitir a la IA buscar en la web (13F, VIX, earnings...); suma coste por busqueda
IA_MAX_TOKENS = 2000                             # longitud maxima de cada respuesta
# --- Proveedor de la IA automatica ---
# "anthropic"     -> API de Anthropic (pago por uso, la unica con busqueda web integrada aqui)
# "openai_compat" -> CUALQUIER API compatible OpenAI: Gemini (tier GRATUITO), DeepSeek, OpenRouter, Groq...
#                    Ejemplo Gemini gratis: key gratuita en https://aistudio.google.com/apikey
IA_PROVIDER = "anthropic"                        # PRECONFIGURADO en Anthropic (pago por uso, con busqueda web en vivo). Solo falta tu key en anthropic_key.txt
IA_COMPAT_BASE = "https://generativelanguage.googleapis.com/v1beta/openai/"   # URL base del proveedor compatible
IA_COMPAT_MODEL = "gemini-2.0-flash"                                          # modelo del proveedor compatible
IA_COMPAT_KEY = ""                               # key del proveedor compatible (o variable de entorno IA_COMPAT_KEY)
# --- Biblioteca de prompts (los 9 de Pedro): el maestro se auto-ejecuta; el resto, copiables o via IA_AUTO_EXTRA ---
IA_PROMPTS = [
    ("sectorial", "🕰 Rotación sectorial — 30 años de precursores",
     "Analiza los últimos 30 años y encuentra qué indicadores (tipos de interés, inflación, ISM, PMI, curva de tipos, desempleo, beneficios empresariales, dólar y petróleo) han anticipado las rotaciones entre tecnología, financieras, industriales, energía, consumo, salud y utilities."),
    ("flujos", "💸 Flujos institucionales",
     "Detecta qué sectores están recibiendo entradas de dinero institucional durante las últimas cuatro semanas comparándolo con los últimos cinco años."),
    ("liderazgo", "🏁 Liderazgo antes de que se vea",
     "¿Qué industrias están mostrando fortaleza relativa frente al S&P 500 antes de que el mercado general las reconozca?"),
    ("ocultas", "🕵️ Rotaciones ocultas",
     "Busca acciones que estén rompiendo máximos de 52 semanas mientras el sector todavía no aparece entre los mejores del S&P 500."),
    ("ciclo", "🕐 Ciclo económico",
     "Según los datos macro actuales, ¿en qué fase del ciclo económico está Estados Unidos y qué sectores suelen liderar históricamente esa fase?"),
    ("insiders", "🐋 Insiders y grandes fondos",
     "Cruza compras de insiders, posiciones de hedge funds y cambios en las carteras de Berkshire Hathaway, Bridgewater, Pershing Square y otros grandes gestores para detectar posibles rotaciones."),
    ("narrativas", "🗣 Narrativas emergentes",
     "¿Qué temas empiezan a aparecer cada vez más en las conferencias de resultados (earnings calls) antes de que el mercado los descuente?"),
    ("multifactor", "🧮 Ranking multifactor",
     "Construye un ranking semanal de sectores utilizando fortaleza relativa, beneficios revisados al alza, momentum, volumen institucional y valoración."),
    ("gestor", "🎖 GESTOR DE HEDGE FUND MACRO (el maestro)",
     "Actúa como un gestor de un hedge fund macro. Analiza diariamente datos macroeconómicos de EE. UU., flujos institucionales, fortaleza relativa de sectores, revisiones de beneficios, mercado de bonos, dólar, VIX, materias primas y amplitud de mercado. Identifica qué sectores tienen mayor probabilidad de liderar durante las próximas 2 a 8 semanas y explica por qué. Asigna una probabilidad a cada escenario y señala qué datos invalidarían esa hipótesis."),
]

def ia_data_block(snap, fecha):
    """Bloque de datos + reglas de la casa que se inyecta a CADA prompt (auto o copiado)."""
    return ("\n\n=== DATOS DE MI TERMINAL PeVR (cierre " + str(fecha) + ") ===\n" + str(snap) +
            "\n\nInstrucciones: usa estos datos de mi terminal como base primaria (RRG, flujo CMF/OBV, scoring, régimen). "
            "Si el prompt necesita datos que NO están aquí (13F, insiders, earnings calls, VIX, revisiones de beneficios, series de 30 años), "
            "búscalos en la web y cita la fuente de cada dato. Cuando mi terminal y tu análisis diverjan, señálalo explícitamente: "
            "mi regla es que el flujo confirma y la narrativa propone. Sé concreto y accionable, con probabilidades cuando sea posible, "
            "y termina siempre con qué datos invalidarían tu conclusión. No es asesoramiento; yo decido.")
# --- Avisos automaticos (opcional). Rellena uno de los dos ---
TELEGRAM_TOKEN = ""                              # token del bot de Telegram (via @BotFather)
TELEGRAM_CHAT_ID = ""                            # tu chat id (via @userinfobot)
WEBHOOK_URL = ""                                 # alternativa: webhook de Discord/Slack
# (en GitHub se pueden poner como Secrets; ver README)
BACKTEST = True                                  # calcular el backtest de la estrategia
# --- Optimizaciones de la estrategia ---
TREND_FILTER = True                              # solo invertir si el S&P > su media de 40 semanas (~200d); si no, liquidez
TREND_MA_WEEKS = 40                              # media para el filtro de tendencia del mercado
MAX_POSICIONES = 7                               # tope de posiciones (las N de mayor impulso); 0 = sin tope -> prioriza los subsectores fuertes
PESO = "volatilidad"                             # reparto: "igual" | "volatilidad" (inversa, mas a lo estable) | "impulso"
BUFFER = 1.0                                     # histeresis: entra si fuerza>100+BUFFER y sale si <100-BUFFER (menos latigazos)
# --- Plan de liquidez / entrada escalonada (guia: caidas del S&P 500 desde maximos) ---
CASH_PLAN = [(5, 30), (10, 30), (20, 40)]        # (caida % desde maximo, % de cartera a desplegar)
DD_THRESHOLDS = [2.5, 5, 10, 20]                 # umbrales para la tabla de caidas
DD_GAP_PP = 0.5                                   # los cubos grandes (>=10%) saltan a partir de (umbral - esto): capta el hueco nocturno del futuro/CFD que el SPY no registra en su sesion de contado (p.ej. -10% salta a partir de -9.5%)
CARTERA_CAPITAL = 1000                           # € a repartir en la "cartera de la semana" (Lider+Mejorando)
CARTERA_DUAL_MOMENTUM = True                     # la cartera exige tambien momentum ABSOLUTO positivo (no entra en lo que sube vs S&P pero pierde dinero)
# --- ETFs apalancados (Direxion, salvo nota); para la "via apalancada" de la pantalla Operativa ---
# Verificado 24-jun-2026. OJO: decay diario en mercados laterales = su mayor riesgo. Verifica disponibilidad en tu broker.
LEVERAGED = {
    "XLK": ("TECL", "x3"), "XLF": ("FAS", "x3"), "XLE": ("ERX", "x2"), "XLV": ("CURE", "x3"),
    "XLY": ("WANT", "x3"), "XLI": ("DUSL", "x3"), "XLU": ("UTSL", "x3"), "XLRE": ("DRN", "x3"),
    "SMH": ("SOXL", "x3"), "SOXX": ("SOXL", "x3"), "XBI": ("LABU", "x3"), "KRE": ("DPST", "x3"),
    "ITB": ("NAIL", "x3"), "ITA": ("DFEN", "x3"), "JETS": ("TPOR", "x3"), "GDX": ("NUGT", "x2"),
    "FXI": ("YINN", "x3"), "IWM": ("TNA", "x3"),
}
# --- Cesto sintetico (pantalla Operativa): las mas fuertes NO extendidas de cada subsector en compra ---
SINT_MIN_RS = 50      # percentil minimo de fuerza relativa para entrar al cesto
SINT_MAX_HI = 90      # % del maximo de 52s por encima del cual se considera "extendida" (fuera del cesto)
SINT_TOP = 5          # tope de acciones en el cesto
SINT_MIN_N = 2        # si pasan menos de estas, avisa (cesto demasiado fino)
CARTERA_SCORE_MIN = 3                            # la cartera no entra en ETFs con scoring < este valor (0 = desactivado). 3 = fuera solo los "evitar" (<=2); 4 = solo "comprar" (estricto, muy concentrado). La distribución oculta SIEMPRE se excluye aparte.
CARTERA_AVISA_TENDENCIA = True                   # True = la cartera NO expulsa a los que están bajo su media de 40 semanas, pero les pone una etiqueta de aviso "⚠ rebote bajo tendencia, mira el gráfico" (tú decides con el gráfico). False = sin aviso.
CARTERA_LIDER_PRIMERO = True                      # True = la cartera prioriza los LÍDER (flujo confirmado) antes que los MEJORANDO, y dentro de cada grupo ordena por impulso. Evita que un rebote acelerado (Mejorando) le quite el sitio a un líder confirmado. False = ordena solo por impulso (puede colar rebotes por delante de líderes).
SALIDA_MA_SEMANAS = 10                            # media móvil semanal para la señal de SALIDA (stop de tendencia). 10 = rápida (protege más plusvalía, algún latigazo) · 20 = media · 30 = lenta (aguanta toda la tendencia pero devuelve más arriba). Cuando el precio CIERRA el viernes por debajo de esta media, es señal de salir.
SALIDA_BANDA_K = 1.0                              # banda anti-latigazo = K × volatilidad semanal del propio ETF (26s). Cerrar bajo la media DENTRO de la banda = solo aviso (1ª semana); hace falta confirmación (2ª semana) o ruptura clara (fuera de la banda) para SALIR. Sube K (1.5) si aún te da latigazos; bájalo (0.5) si te saca tarde.
SALIDA_STOP_K = 2.5                               # stop duro estilo chandelier: pico de 12 semanas − K × volatilidad. Si el precio cae por debajo, SALIR aunque la media aún no lo confirme (protege de desplomes rápidos que la media tarda en ver).
CARTERA_EXIGE_FLUJO = True                        # True = la cartera excluye a los que tienen el dinero SALIENDO de verdad (CMF < -0.05, mismo umbral que todo el panel; el flujo PLANO entre -0.05 y +0.05 NO expulsa). Asi Cartera y Operativa cuentan la misma historia sin echar a sectores sanos con flujo plano (XLF/XLV). False = la cartera entra solo por impulso.

# === LISTA DE VIGILANCIA (pestaña "Vigilancia") ===
# Acciones que vigilas / tienes y crees que a largo plazo lo haran bien. El terminal te dice su FASE y si empieza a ACUMULAR (dinero entrando) antes de la siguiente subida.
WATCHLIST = ["RKLB", "PCT", "OPEN", "OKLO", "QUBT", "UBER", "AA", "AMBA", "AUR"]
WATCH_NAMES = {"RKLB": "Rocket Lab", "PCT": "PureCycle", "OPEN": "Opendoor", "OKLO": "Oklo (nuclear)",
               "QUBT": "Quantum Computing", "UBER": "Uber", "AA": "Alcoa", "AMBA": "Ambarella", "AUR": "Aurora Innovation"}

# === TU CARTERA REAL (para el "Plan de rotacion de mi cartera") ===
# Cada linea: ("TICKER", "BROKER", importe_en_euros). Acepta ETFs (XLF), acciones (MS), apalancados (TQQQ, SOXL) y los de Europa (EWG, EWP).
# Si dejas la lista vacia, el panel no aparece. Pegame capturas de XTB/Robinhood/DEGIRO y te las convierto a estas lineas.
MI_CARTERA = [
    # Formato: ("TICKER", "BROKER", euros_de_EXPOSICION_actual, apalancamiento_del_producto, "tipo")
    # - En acciones/ETFs al contado: euros = valor actual de la posicion, apalancamiento 1.
    # - En CFDs: euros = valor NOCIONAL mostrado por XTB (la exposicion real), apalancamiento 1 (ya es nocional).
    # - En productos de reset diario (2x/3x/5x): euros = valor de la posicion y el apalancamiento del PRODUCTO,
    #   porque su variacion diaria es N veces la del indice.
    # Extraida de capturas del 04-jul-2026. Los sufijos -CFD/-ETF/-ETC/-PERP/-2X/-3L/-5L se ignoran al mapear.
    #
    # ============ XTB (~7.172 EUR equity · suma de posiciones ~9.682 EUR por el nocional de los CFD) ============
    ("RKLB",            "XTB", 612, 1, "etf"),      # Rocket Lab (+611%)
    ("R2K-UCITS",       "XTB", 1095, 1, "etf"),     # SPDR Russell 2000 US Small Cap UCITS
    ("OPEN",            "XTB", 130, 1, "etf"),      # Opendoor (4 posiciones consolidadas: 128.13+0.81+0.46+0.40)
    ("AA",              "XTB", 294, 1, "etf"),      # Alcoa
    ("ARKG-CFD",        "XTB", 149, 1, "cfd"),      # Genomic Revolution CFD
    ("CTVA-CFD",        "XTB", 223, 1, "cfd"),      # Corteva CFD
    ("DRTS",            "XTB", 92, 1, "etf"),       # Alpha Tau Medical
    ("XLV-CFD",         "XTB", 285, 1, "cfd"),      # Health Care Select Sector CFD
    ("PAK-ETF",         "XTB", 163, 1, "etf"),      # MSCI Pakistan Swap (+31.7%)
    ("CCL",             "XTB", 214, 1, "etf"),      # Carnival
    ("TSLA",            "XTB", 133, 1, "etf"),      # Tesla
    ("U-CFD",           "XTB", 254, 1, "cfd"),      # Unity Software CFD
    ("ERO",             "XTB", 227, 1, "etf"),      # Ero Copper
    ("SEDG",            "XTB", 91, 1, "etf"),       # SolarEdge
    ("AAPL-CFD",        "XTB", 268, 1, "cfd"),      # Apple CFD
    ("STOXX600-CONSTR", "XTB", 186, 1, "etf"),      # iShares STOXX Europe 600 Construction & Materials
    ("GLD-ETC",         "XTB", 41, 1, "etf"),       # iShares Physical Gold (+63.8%)
    ("RDW",             "XTB", 113, 1, "etf"),      # Redwire
    ("AUR",             "XTB", 202, 1, "etf"),      # Aurora Innovation
    ("DAX-2X",          "XTB", 469, 2, "etf_lev"),  # DAX Daily 2x Long (reset diario)
    ("MAS",             "XTB", 72, 1, "etf"),       # Masco
    ("MSCI-CHINA",      "XTB", 328, 1, "etf"),      # Xtrackers MSCI China ETF
    ("XLU-CFD",         "XTB", 199, 1, "cfd"),      # Utilities Select Sector CFD
    ("VNM-ETF",         "XTB", 104, 1, "etf"),      # Xtrackers FTSE Vietnam Swap
    ("BCP",             "XTB", 18, 1, "etf"),       # Millennium BCP
    ("DHI-CFD",         "XTB", 416, 1, "cfd"),      # DR Horton CFD
    ("TOI",             "XTB", 50, 1, "etf"),       # Oncology Institute
    ("FSLR",            "XTB", 101, 1, "etf"),      # First Solar
    ("SOFI",            "XTB", 100, 1, "etf"),      # SoFi
    ("SHOP",            "XTB", 48, 1, "etf"),       # Shopify
    ("MTW",             "XTB", 39, 1, "etf"),       # Manitowoc
    ("AMBA",            "XTB", 97, 1, "etf"),       # Ambarella
    ("SGL",             "XTB", 22, 1, "etf"),       # SGL Carbon
    ("VST",             "XTB", 145, 1, "etf"),      # Vistra Energy
    ("SPCE",            "XTB", 23, 1, "etf"),       # Virgin Galactic
    ("CRSP-CFD",        "XTB", 105, 1, "cfd"),      # CRISPR CFD (-40%)
    ("FERG-CFD",        "XTB", 202, 1, "cfd"),      # Ferguson CFD (agua)
    ("OKLO-CFD",        "XTB", 182, 1, "cfd"),      # Oklo CFD (-20%)
    ("MSCI-INDIA",      "XTB", 276, 1, "etf"),      # iShares MSCI India
    ("UBER-CFD",        "XTB", 195, 1, "cfd"),      # Uber CFD (-34.5%)
    ("CHINA-TECH-ETF",  "XTB", 63, 1, "etf"),       # UBS Solactive China Technology
    ("U",               "XTB", 76, 1, "etf"),       # Unity Software accion
    ("LEU",             "XTB", 55, 1, "etf"),       # Centrus Energy (-45%)
    ("OKLO",            "XTB", 43, 1, "etf"),       # Oklo accion (-51%)
    ("QUBT",            "XTB", 55, 1, "etf"),       # Quantum Computing (-47%)
    ("MP-CFD",          "XTB", 187, 1, "cfd"),      # MP Materials CFD (-116% sobre margen)
    ("MSCI-CHINA-TECH", "XTB", 530, 1, "etf"),      # iShares MSCI China Tech
    ("MSCI-CHINA-CFD",  "XTB", 534, 1, "cfd"),      # iShares MSCI China CFD (-59.8%)
    ("TMC",             "XTB", 124, 1, "etf"),      # TMC the metals company (-35.7%)
    ("WWR",             "XTB", 53, 1, "etf"),       # Westwater (-60.3%)
    #
    # ============ ROBINHOOD (~1.573 EUR) — USD convertido a ~0.874 EUR/USD ============
    ("BTC-PERP",  "Robinhood", 28, 1, "perp"),      # perpetuo BTCUSD Largo 5x, nocional 0.00051 BTC
    ("TNA",       "Robinhood", 542, 3, "etf_lev"),  # 8.526 uds
    ("TQQQ",      "Robinhood", 256, 3, "etf_lev"),
    ("LABU",      "Robinhood", 115, 3, "etf_lev"),
    ("DPST",      "Robinhood", 102, 3, "etf_lev"),
    ("FAS",       "Robinhood", 97, 3, "etf_lev"),
    ("RETL",      "Robinhood", 82, 3, "etf_lev"),
    ("CURE",      "Robinhood", 66, 3, "etf_lev"),   # salud 3x
    ("CCJ",       "Robinhood", 57, 1, "etf"),       # Cameco
    ("AAL",       "Robinhood", 48, 1, "etf"),       # American Airlines
    ("HOOG",      "Robinhood", 33, 1, "etf"),       # Hooglund
    ("SPCX-PVT",  "Robinhood", 5, 1, "etf"),        # SpaceX (privada, token)
    ("OPAI-PVT",  "Robinhood", 6, 1, "etf"),        # OpenAI (privada, token)
    ("KRE",       "Robinhood", 1, 1, "etf"),
    ("SOL",       "Robinhood", 91, 1, "cripto"),    # Solana
    ("CRIPTO-RESTO", "Robinhood", 65, 1, "cripto"), # GRAM+XRP+ETH+AVNT+BTC+RENDER+EURC+ONDO+USDC (polvo)
    #
    # ============ DEGIRO (equity ~1.906 EUR · las posiciones suman ~2.262: revisa si hay efectivo NEGATIVO) ============
    ("AMRQ",   "DEGIRO", 102, 1, "etf"),            # Amaroq (minera oro Groenlandia)
    ("MNST",   "DEGIRO", 428, 1, "etf"),            # Monster Beverage
    ("NAS",    "DEGIRO", 78, 1, "etf"),             # Norwegian Air Shuttle
    ("PCT",    "DEGIRO", 479, 1, "etf"),            # PureCycle
    ("UBER",   "DEGIRO", 65, 1, "etf"),             # Uber accion
    ("TLT-5L", "DEGIRO", 269, 5, "bono_lev"),       # Leverage Shares 5x Long 20+Y Treasury
    ("R2K-UCITS", "DEGIRO", 767, 1, "etf"),         # SPDR Russell 2000 UCITS
    ("SLV-3L", "DEGIRO", 74, 3, "plata_lev"),       # WisdomTree Silver 3x Daily
]
# --- Mapa de alias -> ETF de referencia del terminal (para que el plan de rotacion pueda evaluar cada posicion) ---
ALIAS2ETF = {
    # XTB
    "RKLB": "ITA", "R2K-UCITS": "IWM", "OPEN": "ITB", "AA": "XME", "ARKG": "XBI", "CTVA": "MOO",
    "DRTS": "XBI", "CCL": "JETS", "U": "IGV", "ERO": "COPX", "SEDG": "TAN",
    "STOXX600-CONSTR": "VGK", "GLD": "GLD", "RDW": "ITA", "AUR": "BOTZ", "DAX-2X": "EWG",
    "MAS": "ITB", "MSCI-CHINA": "FXI", "VNM": None, "BCP": "VGK", "DHI": "ITB", "TOI": "XLV",
    "FSLR": "TAN", "SOFI": "ARKF", "SHOP": "IGV", "MTW": "XLI", "AMBA": "SMH", "SGL": "XLB",
    "VST": "XLU", "SPCE": "ITA", "CRSP": "XBI", "FERG": "FIW", "OKLO": "URA",
    "MSCI-INDIA": "INDA", "UBER": "XLY", "CHINA-TECH-ETF": "KWEB", "LEU": "URA", "QUBT": "QTUM",
    "MP": "XME", "MSCI-CHINA-TECH": "KWEB", "MSCI-CHINA-CFD": "FXI", "TMC": "XME", "WWR": "URA",
    "PAK": None,
    # Robinhood
    "RETL": "XRT", "CCJ": "URA", "AAL": "JETS", "SOL": "IBIT", "BTC": "IBIT",
    # DEGIRO
    "AMRQ": "GDX", "NAS": "JETS", "PCT": "XLB", "MNST": "XLP", "TLT": "TLT", "SLV": "SLV",
}
# --- Nombres legibles de las posiciones de MI_CARTERA (para el tooltip de tickers) ---
CARTERA_NOMBRES = {
    "RKLB": "Rocket Lab (espacio)", "R2K-UCITS": "SPDR Russell 2000 US Small Cap UCITS", "OPEN": "Opendoor Technologies",
    "AA": "Alcoa (aluminio)", "ARKG-CFD": "ARK Genomic Revolution (CFD)", "CTVA-CFD": "Corteva Agriscience (CFD)",
    "DRTS": "Alpha Tau Medical", "XLV-CFD": "Health Care Select Sector (CFD)", "PAK-ETF": "MSCI Pakistan Swap",
    "CCL": "Carnival (cruceros)", "TSLA": "Tesla", "U-CFD": "Unity Software (CFD)", "U": "Unity Software",
    "ERO": "Ero Copper (cobre)", "SEDG": "SolarEdge", "AAPL-CFD": "Apple (CFD)",
    "STOXX600-CONSTR": "STOXX Europe 600 Construcción y Materiales", "GLD-ETC": "iShares Physical Gold",
    "RDW": "Redwire (espacio)", "AUR": "Aurora Innovation (conducción autónoma)", "DAX-2X": "DAX Daily 2x Long",
    "MAS": "Masco (construcción)", "MSCI-CHINA": "Xtrackers MSCI China UCITS", "XLU-CFD": "Utilities Select Sector (CFD)",
    "VNM-ETF": "Xtrackers FTSE Vietnam Swap", "BCP": "Millennium BCP", "DHI-CFD": "DR Horton (CFD, vivienda)",
    "TOI": "Oncology Institute", "FSLR": "First Solar", "SOFI": "SoFi Technologies", "SHOP": "Shopify",
    "MTW": "Manitowoc (grúas)", "AMBA": "Ambarella (semis visión)", "SGL": "SGL Carbon", "VST": "Vistra Energy",
    "SPCE": "Virgin Galactic", "CRSP-CFD": "CRISPR Therapeutics (CFD)", "FERG-CFD": "Ferguson (CFD, agua)",
    "OKLO-CFD": "Oklo (CFD, nuclear)", "OKLO": "Oklo (nuclear)", "MSCI-INDIA": "iShares MSCI India",
    "UBER-CFD": "Uber (CFD)", "UBER": "Uber", "CHINA-TECH-ETF": "UBS Solactive China Technology",
    "LEU": "Centrus Energy (uranio)", "QUBT": "Quantum Computing Inc", "MP-CFD": "MP Materials (CFD, tierras raras)",
    "MSCI-CHINA-TECH": "iShares MSCI China Tech UCITS", "MSCI-CHINA-CFD": "iShares MSCI China (CFD)",
    "TMC": "TMC the metals company", "WWR": "Westwater Resources",
    "BTC-PERP": "Perpetuo BTC/USD 5x largo", "TNA": "Small caps Russell 2000 x3", "TQQQ": "Nasdaq-100 x3",
    "LABU": "Biotech x3", "DPST": "Banca regional x3", "FAS": "Financieras x3", "RETL": "Retail x3",
    "CURE": "Salud x3", "CCJ": "Cameco (uranio)", "AAL": "American Airlines", "HOOG": "Hooglund",
    "SPCX-PVT": "SpaceX (token privado)", "OPAI-PVT": "OpenAI (token privado)", "SOL": "Solana",
    "CRIPTO-RESTO": "Resto cripto (polvo)", "AMRQ": "Amaroq Minerals (oro Groenlandia)", "MNST": "Monster Beverage",
    "NAS": "Norwegian Air Shuttle", "PCT": "PureCycle Technologies", "TLT-5L": "Treasury 20+ años x5 largo",
    "SLV-3L": "Plata x3 diario",
}
# --- Datos de margen por broker (para el stress-test; actualizalos cuando cambien) ---
BROKER_INFO = {
    # equity = valor de la cuenta EUR · margen_libre = capital disponible · nivel_margen = % que muestra el broker (equity/margen requerido)
    # stopout = nivel de margen al que el broker EMPIEZA A CERRARTE posiciones el solo
    "XTB":       {"equity": 7172, "margen_libre": 5.94, "nivel_margen": 104.87, "stopout": 50},
    "Robinhood": {"equity": 1573, "margen_libre": None, "nivel_margen": None,   "stopout": None},
    "DEGIRO":    {"equity": 1906, "margen_libre": None, "nivel_margen": None,   "stopout": None},
}
STRESS_DD = [-5, -10, -20]                       # escenarios de caida del S&P para el stress-test
# beta aproximada frente al S&P por TIPO de activo (choque de 1 dia; orientativa, no exacta)
STRESS_BETA = {"etf": 1.0, "etf_lev": 1.0, "cfd": 1.0, "cesta": 1.0, "perp": 1.8, "cripto": 1.8,
               "bono_lev": -0.2, "plata_lev": 0.8}
# --- Senal contraria 0/3 (tu estadistica: 65% de acierto a 4 semanas, +2.2% de media; muestra 70 sem = IN-SAMPLE) ---
CONTRARIAN_ON = True                             # activa el modulo de senal contraria (ledger fuera-de-muestra + tamano sugerido)
CONTRARIAN_SIZE_PCT = 2.0                        # % de cartera por senal mientras la muestra fuera-de-muestra sea corta (<20 casos)
CONTRARIAN_MAX_SIGS = 3                          # maximo de senales simultaneas (tope de exposicion contraria = SIZE x MAX)
CONTRARIAN_HORIZON_W = 4                         # horizonte de evaluacion en semanas (el de tu estadistica)

# --- Indicador Pine v6 para TradingView: el MISMO flujo (CMF + distribucion oculta) del terminal ---
PINE_SCRIPT = '''//@version=6
indicator("Flujo PeVR — CMF + distribución oculta", shorttitle="Flujo PeVR", overlay=false)

// === Ajustes (mismos umbrales que el terminal ROTACION) ===
lenCMF   = input.int(20, "Longitud del CMF", minval=2)
lenOBV   = input.int(20, "Media del OBV", minval=2)
lookDiv  = input.int(13, "Velas para la divergencia precio/flujo", minval=4)
umbral   = input.float(0.05, "Umbral CMF (±)", step=0.01)
verOBV   = input.bool(true, "Mostrar OBV vs su media (normalizado)")

// === CMF (Chaikin Money Flow) ===
mfm = high == low ? 0.0 : ((2 * close - low - high) / (high - low))
mfv = mfm * volume
cmf = math.sum(mfv, lenCMF) / math.sum(volume, lenCMF)

// === OBV y su media ===
obv   = ta.obv
obvMa = ta.sma(obv, lenOBV)

// === Distribución oculta: el precio SUBE pero el dinero SALE ===
precioSube = close > close[lookDiv]
dineroSale = cmf < -umbral or (obv < obvMa and cmf < 0)
distOculta = precioSube and dineroSale

// === Acumulación oculta: el precio CAE pero el dinero ENTRA ===
acumOculta = close < close[lookDiv] and cmf > umbral and obv > obvMa

// === Pintado ===
colCmf = cmf > umbral ? color.new(#2FD08A, 0) : cmf < -umbral ? color.new(#F4607A, 0) : color.new(#93A4BC, 40)
plot(cmf, "CMF", style=plot.style_columns, color=colCmf)
hline(0, "Cero", color=color.new(#93A4BC, 60))
hline(0.05, "+0.05 (entra dinero)", color=color.new(#2FD08A, 70), linestyle=hline.style_dotted)
hline(-0.05, "-0.05 (sale dinero)", color=color.new(#F4607A, 70), linestyle=hline.style_dotted)

obvRel = verOBV ? (obv - obvMa) / (ta.stdev(obv, 100) + 1e-9) * 0.05 : na
plot(obvRel, "OBV vs media (escalado)", color=color.new(#4CC2E0, 25), linewidth=1)

plotshape(distOculta, "Distribución oculta", style=shape.triangledown, location=location.top, color=color.new(#F4B740, 0), size=size.tiny)
plotshape(acumOculta, "Acumulación oculta", style=shape.triangleup, location=location.bottom, color=color.new(#4CC2E0, 0), size=size.tiny)
bgcolor(distOculta ? color.new(#F4B740, 88) : acumOculta ? color.new(#4CC2E0, 92) : na)

// === Alertas ===
alertcondition(distOculta, "Flujo PeVR: Distribución oculta", "{{ticker}}: el precio sube pero el dinero SALE (distribución oculta)")
alertcondition(acumOculta, "Flujo PeVR: Acumulación oculta", "{{ticker}}: el precio cae pero el dinero ENTRA (acumulación)")
alertcondition(ta.crossover(cmf, 0.05), "Flujo PeVR: CMF cruza +0.05", "{{ticker}}: el dinero empieza a ENTRAR (CMF > +0.05)")
alertcondition(ta.crossunder(cmf, -0.05), "Flujo PeVR: CMF cruza -0.05", "{{ticker}}: el dinero empieza a SALIR (CMF < -0.05)")
'''
MEAN_REVERSION = True                            # calcula la rentabilidad media anual (10a) y la del año (YTD) de cada ETF -> panel "margen vs su media" (descarga ~10a por ETF, algo mas lento; pon False para desactivar)
# Vehiculos apalancados x3 por activo (informativo; MUY arriesgados, ver avisos)
LEV3X = {"SPY":"SPXL/UPRO", "QQQ":"TQQQ", "MAGS":"TQQQ", "XLK":"TECL", "XLF":"FAS",
         "XLE":"ERX", "XLV":"CURE", "XLI":"DUSL", "XLB":"—", "XLU":"UTSL", "XLRE":"DRN",
         "XLY":"WANT", "XLP":"—", "XLC":"—", "IWM":"TNA", "FXI":"YINN", "EEM":"EDC",
         "ITA":"DFEN", "GLD":"—", "TLT":"TMF", "SMH":"SOXL", "KRE":"DPST", "XBI":"LABU",
         "GDX":"NUGT", "JETS":"—", "IGV":"TECL*", "SOXX":"SOXL", "ITB":"NAIL", "KWEB":"CWEB*"}
# Empresa lider (mayor posicion) de cada ETF — ORIENTATIVO, cambia con el tiempo
TOP_HOLDING = {
    "XLK":"NVDA / MSFT / AAPL", "XLF":"BRK.B / JPM", "XLE":"XOM / CVX", "XLV":"LLY / UNH",
    "XLY":"AMZN / TSLA", "XLP":"COST / WMT", "XLI":"GE / CAT", "XLB":"LIN / SHW",
    "XLU":"NEE / SO", "XLRE":"PLD / AMT", "XLC":"META / GOOGL", "IWM":"muy diversificado",
    "MAGS":"los 7 (AAPL,MSFT,NVDA...)", "FXI":"BABA / Tencent", "EEM":"TSM / Tencent",
    "ITA":"GE Aero / RTX / BA", "JETS":"aerolineas + BKNG", "SMH":"NVDA / TSM / AVGO",
    "KRE":"banca regional (div.)", "XBI":"biotech equiponderado", "GDX":"NEM / AEM",
    "IGV":"MSFT / CRM / ORCL",
    "SOXX":"NVDA / AVGO / AMD", "ITB":"DHI / LEN / NVR", "KWEB":"BABA / Tencent / PDD",
    "EWG":"SAP / Siemens / Allianz", "EWP":"Iberdrola / Inditex / Santander",
    "COPX":"Freeport / Antofagasta / Ivanhoe", "URA":"Cameco / Kazatomprom / NexGen", "LIT":"Albemarle / SQM / Ganfeng",
    "GRID":"Eaton / Quanta / GE Vernova", "PAVE":"Eaton / Trane / Quanta",
    "FIW":"Ferguson / Xylem / Veralto", "CGW":"American Water / Veolia / Xylem",
    "HYDR":"Plug Power / Bloom / ITM Power",
}
SITE_DIR = "site"                                # carpeta que publica GitHub Pages
STATIC_DIR = "static"                            # iconos, manifest, service worker
OUTPUT_HTML = os.path.join(SITE_DIR, "index.html")
CACHE_DIR = "cache_rotacion"
# ----------------------------------------------------------------------

NAMES = {
    "SPY":("S&P 500","Indice (referencia)","bench"),
    "XLK":("Technology","Tecnologia","ciclico"),
    "XLF":("Financials","Financiero","ciclico"),
    "XLE":("Energy","Energia","sensible"),
    "XLV":("Health Care","Salud","defensivo"),
    "XLY":("Cons. Discretionary","Consumo discrecional","ciclico"),
    "XLP":("Cons. Staples","Consumo basico","defensivo"),
    "XLI":("Industrials","Industrial","ciclico"),
    "XLB":("Materials","Materiales","sensible"),
    "XLU":("Utilities","Servicios publicos","defensivo"),
    "XLRE":("Real Estate","Inmobiliario","sensible"),
    "XLC":("Comm. Services","Comunicaciones","ciclico"),
    "IWM":("Russell 2000","Small caps","ciclico"),
    "TLT":("20Y Treasuries","Bonos largos","defensivo"),
    "GLD":("Gold","Oro","defensivo"),
    "IBIT":("iShares Bitcoin Trust","Bitcoin (ETF)","especulativo"),
    "HYG":("High Yield","Credito HY","ciclico"),
    "UUP":("US Dollar","Dolar","macro"),
    "FXI":("China Large-Cap","China","ciclico"),
    "EEM":("Emerging Markets","Emergentes","ciclico"),
    "ITA":("Aerospace & Defense","Espacio y defensa","ciclico"),
    "MAGS":("Magnificent 7","7 Magnificos","ciclico"),
    "JETS":("Airlines / Travel","Viajes y aerolineas","ciclico"),
    "SMH":("Semiconductors","Semiconductores","ciclico"),
    "KRE":("Regional Banks","Banca regional","ciclico"),
    "XBI":("Biotech","Biotecnologia","ciclico"),
    "GDX":("Gold Miners","Mineras de oro","sensible"),
    "IGV":("Software","Software","ciclico"),
    "SOXX":("Semiconductors (iShares)","Semis (iShares)","ciclico"),
    "ITB":("Home Construction","Construccion / vivienda","ciclico"),
    "KWEB":("China Internet","China tecnologica","ciclico"),
    "EWG":("Germany (DAX proxy)","Alemania / DAX","ciclico"),
    "EWP":("Spain (IBEX proxy)","España / IBEX 35","ciclico"),
    "COPX":("Copper Miners","Cobre (mineras)","ciclico"),
    "URA":("Uranium","Uranio","ciclico"),
    "LIT":("Lithium & Battery","Litio y baterías","ciclico"),
    "GRID":("Smart Grid Infra","Red eléctrica (IA)","ciclico"),
    "PAVE":("US Infrastructure","Infraestructura EE.UU. (IA)","ciclico"),
    "FIW":("US Water","Agua EE.UU. (IA)","ciclico"),
    "CGW":("Global Water","Agua global (IA)","ciclico"),
    "HYDR":("Global Hydrogen","Hidrógeno (IA/energía)","ciclico"),
    "XRT":("Retail (SPDR)","Retail / consumo minorista","ciclico"),
    "XOP":("Oil & Gas E&P","Petróleo y gas (E&P)","sensible"),
    "OIH":("Oil Services","Servicios petroleros","sensible"),
    "ARKF":("Fintech Innovation","Fintech (ARK)","ciclico"),
    "ARKK":("ARK Innovation","Innovación (ARK)","ciclico"),
    "CIBR":("Cybersecurity","Ciberseguridad","ciclico"),
    "SKYY":("Cloud Computing","Nube (cloud)","ciclico"),
    "BOTZ":("Robotics & AI","Robótica e IA","ciclico"),
    "TAN":("Solar","Solar","ciclico"),
    "ICLN":("Clean Energy","Energía limpia global","ciclico"),
    "FAN":("Wind Energy","Eólica","ciclico"),
    "XME":("Metals & Mining","Minería y metales","sensible"),
    "SIL":("Silver Miners","Mineras de plata","sensible"),
    "SLV":("Silver","Plata","sensible"),
    "EWJ":("Japan","Japón","ciclico"),
    "INDA":("India","India","ciclico"),
    "EWZ":("Brazil","Brasil","ciclico"),
    "VGK":("Europe","Europa","ciclico"),
    "EURUSD":("Euro / Dolar","EUR/USD","macro"),
    "DRIV":("Global X Autonomous & EV — señal del tema automoción innovadora; en España se compra vía WisdomTree WCAR UCITS","Automoción innov.","tech"),
    "EWY":("iShares MSCI South Korea — el chivato asiático de los semis (Samsung + SK Hynix)","Corea del Sur","internac"),
    "MOO":("VanEck Agribusiness — agro y alimentación (el hogar natural de tu Corteva)","Agronegocio","materiales"),
    "QTUM":("Defiance Quantum — computación cuántica (el hogar natural de tu QUBT)","Computación cuántica","tech"),
    "S-FISICO":("Sintético economía física (XLI+XLB+XME+COPX+PAVE+GRID)","Sint. Física","sintetico"),
    "S-TECH":("Sintético tecnología amplia (XLK+SMH+SOXX+IGV+CIBR+SKYY)","Sint. Tech","sintetico"),
    "S-CICLO":("Sintético ciclo consumidor (XLY+XRT+JETS+ITB+IWM)","Sint. Ciclo","sintetico"),
    "S-DEFENSA":("Sintético refugio defensivo (XLP+XLU+XLV+GLD+TLT)","Sint. Defensa","sintetico"),
    "S-CHINA":("Sintético China total (FXI+KWEB)","Sint. China","sintetico"),
}
QUAD = {
    "leading":  ("Lider","#2FD08A","Liderazgo confirmado"),
    "weakening":("Debilitandose","#F4B740","Riesgo de recogida de beneficios"),
    "lagging":  ("Rezagado","#F4607A","Evitar / infraponderar"),
    "improving":("Mejorando","#4CC2E0","Acumulacion temprana"),
}

# ----------------------------------------------------------------------
# Bootstrap de dependencias
# ----------------------------------------------------------------------
def ensure(pkg, imp=None, optional=False):
    try:
        return importlib.import_module(imp or pkg)
    except ImportError:
        print(f"  Instalando {pkg} ...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", pkg])
            return importlib.import_module(imp or pkg)
        except Exception as e:
            if optional:
                print(f"  (Aviso) No se pudo instalar {pkg}: {e}")
                return None
            raise

print("Preparando librerias...")
pd = ensure("pandas")
yf = ensure("yfinance", optional=True)
requests = ensure("requests")
import pandas as pd  # noqa
from io import StringIO

# ----------------------------------------------------------------------
# Descarga de datos (Stooq -> Yahoo -> cache)
# ----------------------------------------------------------------------
def fetch_stooq(sym, start, end):
    """Descarga OHLCV diario directamente de Stooq (sin libreria intermedia)."""
    url = f"https://stooq.com/q/d/l/?s={sym.lower()}.us&i=d"
    try:
        r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        txt = r.text
        if not txt or "Close" not in txt.splitlines()[0]:
            return None
        df = pd.read_csv(StringIO(txt))
        if "Date" not in df.columns or "Close" not in df.columns or len(df) < 30:
            return None
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date").sort_index()
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        out = df[cols].copy()
        return out[out.index >= pd.Timestamp(start)]
    except Exception:
        return None

def fetch_yahoo(sym, start, end):
    if yf is None:
        return None
    try:
        df = yf.download(sym, start=start, end=end + dt.timedelta(days=1), interval="1d",
                         progress=False, auto_adjust=True)
        if df is None or len(df) < 30:
            return None
        if hasattr(df.columns, "nlevels") and df.columns.nlevels > 1:
            df.columns = df.columns.get_level_values(0)
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in df.columns]
        return df[cols].sort_index()
    except Exception:
        return None

def cache_path(sym):
    return os.path.join(CACHE_DIR, f"{sym}.csv")

def save_cache(sym, dframe):
    os.makedirs(CACHE_DIR, exist_ok=True)
    dframe.to_csv(cache_path(sym))

def load_cache(sym):
    p = cache_path(sym)
    if os.path.exists(p):
        try:
            return pd.read_csv(p, index_col=0, parse_dates=True).sort_index()
        except Exception:
            return None
    return None

# El seguimiento NO va en la cache (la cache es desechable y se borra para liberar espacio o forzar datos frescos).
# Va en su propia carpeta, con nombre de "no me borres", y se hace copia de seguridad en cada guardado.
SEGUIMIENTO_DIR = "historico_seguimiento_NO_BORRAR"
TRACK_FILE = os.path.join(SEGUIMIENTO_DIR, "track_record.json")
TRACK_BAK = os.path.join(SEGUIMIENTO_DIR, "track_record.bak.json")
_OLD_TRACK = os.path.join(CACHE_DIR, "track_record.json")          # ubicacion antigua (dentro de la cache)
try:
    # migracion: si tienes histórico en la cache vieja y aun no en la nueva, lo traslado para no perderlo
    if os.path.exists(_OLD_TRACK) and not os.path.exists(TRACK_FILE):
        os.makedirs(SEGUIMIENTO_DIR, exist_ok=True)
        import shutil as _sh
        _sh.copy2(_OLD_TRACK, TRACK_FILE)
except Exception:
    pass

def semana_trading(fecha):
    """Etiqueta de SEMANA DE TRADING: la ventana sabado..viernes, nombrada por el viernes que la cierra.
    Lun/mar/mie/jue/vie de la misma semana -> misma etiqueta. Sabado/domingo -> la semana que viene.
    Evita el bug de que el lunes (nueva semana ISO) creara un registro distinto al viernes anterior."""
    try:
        d = pd.Timestamp(fecha)
        wd = d.weekday()               # 0=lun..6=dom
        if wd == 5:                    # sabado
            friday = d + pd.Timedelta(days=6)
        elif wd == 6:                  # domingo
            friday = d + pd.Timedelta(days=5)
        else:                          # lun..vie -> el viernes de esta misma semana
            friday = d + pd.Timedelta(days=(4 - wd))
        return friday.strftime("%G-W%V")
    except Exception:
        return str(fecha)


def update_track_record(basket, px_now, datestr, marked=None):
    # Guarda un snapshot por semana ISO {week, date, basket, marked, px:{ticker:cierre}} y devuelve el historico ordenado.
    # px_now debe incluir los tickers del basket + SPY/QQQ/IWM. Asi cada semana puede valorar la cesta de la anterior.
    os.makedirs(SEGUIMIENTO_DIR, exist_ok=True)
    recs = []
    if os.path.exists(TRACK_FILE):
        try:
            with open(TRACK_FILE, "r", encoding="utf-8") as fh:
                recs = json.load(fh)
        except Exception:
            # si el principal está corrupto, intento recuperar desde la copia de seguridad
            try:
                with open(TRACK_BAK, "r", encoding="utf-8") as fh:
                    recs = json.load(fh)
            except Exception:
                recs = []
    wk = semana_trading(datestr)
    px_clean = {k: float(v) for k, v in px_now.items() if v is not None and v == v}
    ya_existe = any(r.get("week") == wk for r in recs)
    # Solo se GRABA una cesta nueva cuando la semana ha cerrado (viernes o fin de semana).
    # Entre semana (lun-jue) se observa pero NO se registra: evita abrir una semana a medias con datos provisionales.
    try:
        _hoy_wd = dt.date.today().weekday()   # 0=lun..6=dom
    except Exception:
        _hoy_wd = 4
    if not ya_existe and _hoy_wd < 4:
        print(f"  TRACK: semana {wk} aun en curso (hoy es {['lunes','martes','miercoles','jueves','viernes','sabado','domingo'][_hoy_wd]}). "
              "No se graba hasta el cierre del VIERNES — entre semana solo se observa.")
        recs.sort(key=lambda r: r.get("week", ""))
        return recs
    if ya_existe:
        # NO sobrescribir: el registro de la semana se CONGELA con el primer build (idealmente el viernes).
        # Re-ejecutar a media semana no debe mover la fecha/precio de entrada ni la cesta registrada.
        try:
            dia = pd.Timestamp(datestr).strftime("%A")
        except Exception:
            dia = str(datestr)
        print(f"  TRACK: la semana {wk} ya esta registrada (congelada). Re-ejecucion en {dia} NO la altera — solo el primer cierre de la semana cuenta.")
        recs.sort(key=lambda r: r.get("week", ""))
        return recs
    snap = {"week": wk, "date": str(datestr), "basket": list(basket), "marked": list(marked or []), "px": px_clean}
    recs.append(snap)
    recs.sort(key=lambda r: r.get("week", ""))
    try:
        with open(TRACK_FILE, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=0)
        with open(TRACK_BAK, "w", encoding="utf-8") as fh:        # copia de seguridad
            json.dump(recs, fh, ensure_ascii=False, indent=0)
    except Exception:
        pass
    return recs

def pct_desde_entrada(recs, sym, key, cur_week, in_now, cur_px, df=None):
    """% desde el inicio de la RACHA continua actual de sym en recs[key] (reinicia si sale y vuelve).
       in_now = si esta en el set esta semana; cur_px = precio actual. Devuelve (pct, semanas) o None.
       Robusto a HUECOS: si una semana de la racha no guardo precio, sigue buscando hacia atras el
       precio valido mas antiguo (antes se quedaba en cur_px y daba 0% — el bug de CIBR/KRE)."""
    if not in_now or not cur_px or cur_px <= 0:
        return None
    timeline = []
    for r in sorted(recs or [], key=lambda r: r.get("week", "")):
        if r.get("week") == cur_week:
            continue
        timeline.append((r.get("week"), sym in r.get(key, []), (r.get("px", {}) or {}).get(sym)))
    timeline.append((cur_week, True, cur_px))            # semana actual (aun no persistida)
    entry_px, entry_wk, weeks = cur_px, cur_week, 0
    for wk, inset, px in reversed(timeline):
        if inset:
            if px and px > 0:
                entry_px = px                            # sigue actualizando: acaba en el mas antiguo de la racha
                entry_wk = wk
            weeks += 1
        else:
            break
    # fallback: si el precio de entrada quedo igual al actual por huecos, recuperarlo de la serie diaria
    if df is not None and entry_wk and entry_px == cur_px and weeks > 1 and sym in getattr(df, "columns", []):
        try:
            s = df[sym].dropna()
            import pandas as _pd
            wkstart = _pd.Timestamp(entry_wk.split("/")[0]) if "/" in str(entry_wk) else None
            # entry_wk viene como ISO week "%G-W%V"; convertimos a fecha del viernes de esa semana
            import datetime as _dt
            yr, wk2 = str(entry_wk).split("-W")
            monday = _dt.date.fromisocalendar(int(yr), int(wk2), 1)
            friday = monday + _dt.timedelta(days=4)
            idx = s.index.searchsorted(_pd.Timestamp(friday))
            if 0 <= idx < len(s):
                entry_px = float(s.iloc[idx])
        except Exception:
            pass
    if not entry_px or entry_px <= 0:
        return None
    return ((cur_px / entry_px - 1) * 100, weeks)


def compute_track_perf(recs, benches=("SPY", "QQQ", "IWM"), ew_universe=None):
    # A partir de los snapshots, retorno semanal de la cesta del sistema (equiponderada) vs benchmarks
    # y vs una cesta de TODOS los sectores equiponderada (ew_universe), y acumulado encadenado.
    if not recs or len(recs) < 2:
        return None
    ew_universe = list(ew_universe) if ew_universe else list(SECTORS)
    weeks = []
    cum = {"sys": 1.0, "ew": 1.0}
    for b in benches:
        cum[b] = 1.0
    for i in range(len(recs) - 1):
        a, b = recs[i], recs[i + 1]
        pxa, pxb = a.get("px", {}), b.get("px", {})
        bk = [t for t in a.get("basket", []) if t in pxa and t in pxb and pxa[t]]
        if not bk:
            continue
        sysret = sum((pxb[t] / pxa[t] - 1.0) for t in bk) / len(bk)
        row = {"week": b["week"], "date": b["date"], "basket": a.get("basket", []), "sys": sysret, "bench": {}}
        cum["sys"] *= (1.0 + sysret)
        row["cum_sys"] = cum["sys"] - 1.0
        # cesta de TODOS los sectores equiponderada (referencia: ¿la selección bate a tenerlo todo por igual?)
        ewbk = [t for t in ew_universe if t in pxa and t in pxb and pxa[t]]
        if ewbk:
            ewret = sum((pxb[t] / pxa[t] - 1.0) for t in ewbk) / len(ewbk)
            row["ew"] = ewret
            cum["ew"] *= (1.0 + ewret)
        else:
            row["ew"] = None
        row["cum_ew"] = cum["ew"] - 1.0
        for bm in benches:
            if bm in pxa and bm in pxb and pxa[bm]:
                r = pxb[bm] / pxa[bm] - 1.0
                row["bench"][bm] = r
                cum[bm] *= (1.0 + r)
            row[f"cum_{bm}"] = cum[bm] - 1.0
        weeks.append(row)
    if not weeks:
        return None
    return {"weeks": weeks, "cum": {k: cum[k] - 1.0 for k in cum},
            "pending": {"week": recs[-1]["week"], "date": recs[-1]["date"], "basket": recs[-1].get("basket", [])},
            "n": len(weeks)}

def topup_recent(sym, d, end):
    # rellena con Yahoo las barras mas recientes que Stooq aun no tenga (frescura del ultimo dia).
    # devuelve (dataframe, n_barras_anyadidas)
    if not TOPUP_YAHOO or yf is None or d is None or d.empty:
        return d, 0
    try:
        last = d.index[-1]
        y = yf.download(sym, start=(last - dt.timedelta(days=4)),
                        end=end + dt.timedelta(days=1), interval="1d",
                        progress=False, auto_adjust=True)
        if y is None or y.empty:
            return d, 0
        if hasattr(y.columns, "nlevels") and y.columns.nlevels > 1:
            y.columns = y.columns.get_level_values(0)
        cols = [c for c in ["Open", "High", "Low", "Close", "Volume"] if c in y.columns]
        newer = y[cols][y.index > last]
        if newer.empty:
            return d, 0
        d = pd.concat([d, newer]).sort_index()
        d = d[~d.index.duplicated(keep="last")]
        return d, len(newer)
    except Exception:
        return d, 0

def get_ohlcv(sym, start, end):
    pairs = ([(fetch_yahoo, "yahoo"), (fetch_stooq, "stooq")] if DATA_PRIMARY == "yahoo"
             else [(fetch_stooq, "stooq"), (fetch_yahoo, "yahoo")])
    for fn, nm in pairs:
        d = fn(sym, start, end)
        if d is not None and len(d) >= 30:
            save_cache(sym, d)
            return d, nm
    c = load_cache(sym)
    if c is not None:
        return c, "cache"
    return None, "—"

def to_weekly_close(series):
    # ultimo cierre disponible de cada semana, etiquetado por el VIERNES de esa semana (consistente entre
    # simbolos) PERO sin pasar de HOY: asi la semana en curso queda en UNA sola fila alineada y con fecha
    # real (no un viernes futuro), aunque Yahoo de a unos el viernes y a otros solo el jueves.
    s = series.dropna()
    if s.empty:
        return s
    last = s.groupby(s.index.to_period("W-FRI")).tail(1).copy()
    fri = last.index.to_period("W-FRI").to_timestamp(how="end").normalize()
    hoy = pd.Timestamp(dt.date.today())
    last.index = fri.where(fri <= hoy, hoy)   # la semana en curso se etiqueta HOY, no su viernes futuro
    return last

def download_all():
    end = dt.date.today()
    start = end - dt.timedelta(days=int(WEEKS * 7 * 1.6) + 60)
    symbols = [BENCH] + SECTORS + SATELLITES + THEMATIC + EXTRA
    weekly = {}
    daily = {}
    sources = {}
    print(f"\nDescargando {len(symbols)} simbolos (OHLCV diario)...")
    for sym in symbols:
        d, src = get_ohlcv(sym, start, end)
        if d is None or "Close" not in d.columns:
            print(f"  {sym:5s}  sin datos")
            sources[sym] = "—"
            continue
        if src == "stooq":   # intentar refrescar el ultimo dia con Yahoo
            d, added = topup_recent(sym, d, end)
            if added:
                src = "stooq+yf"
                save_cache(sym, d)
        daily[sym] = d
        weekly[sym] = to_weekly_close(d["Close"])
        sources[sym] = src
        print(f"  {sym:5s}  {src:9s}  {len(weekly[sym])} semanas  ult {weekly[sym].index[-1].date()}")
        time.sleep(0.25)   # cortesia con la fuente
    # alinear: union de fechas + ffill para que un solo simbolo rezagado no arrastre a todos
    df = pd.DataFrame(weekly).sort_index()
    if df.shape[1] > 0:
        min_obs = max(30, int(0.7 * df.shape[0]))
        df = df.dropna(axis=1, thresh=min_obs)
    df = df.ffill().dropna()
    if len(df) > WEEKS:
        df = df.iloc[-WEEKS:]
    used = [v for v in sources.values() if v not in ("—",)]
    if used and not any("stooq" in v for v in used):
        print("  AVISO: Stooq no respondio en ninguna descarga (probable LIMITE DIARIO de Stooq por su IP, "
              "agravado por el universo de ~500 acciones). Se ha usado Yahoo. El cupo se restablece al dia siguiente; "
              "puedes bajar RS_UNIVERSE a 'sector' o poner DATA_PRIMARY='yahoo'.")
    return df, daily, sources

# ----------------------------------------------------------------------
# Motor RRG
# ----------------------------------------------------------------------
def rolling_z(s, win):
    m = s.rolling(win).mean()
    sd = s.rolling(win).std(ddof=0).replace(0, 1e-9)
    return (s - m) / sd

def add_sinteticos(df):
    """Construye los indices SINTETICOS: para cada cesta, cada miembro se rebasea a 100 en el
    primer punto comun y se promedia (equiponderado, rebalanceo implicito semanal). El resultado
    es UNA serie por tema que entra al RRG como una bolita mas — el pulso del bloque entero."""
    for key, cfg in SINTETICOS.items():
        try:
            members = [m for m in cfg["members"] if m in df.columns]
            if len(members) < 2:
                continue
            sub = df[members].dropna()
            if len(sub) < 20:
                continue
            comp = (sub / sub.iloc[0]).mean(axis=1) * 100.0
            df[key] = comp.reindex(df.index)
        except Exception:
            continue
    return df


def compute_rrg(df):
    bench = df[BENCH]
    n = len(df)
    smooth_span = max(4, min(10, n // 6))
    z_win = max(8, min(26, n // 2))
    mom_span = max(4, min(10, n // 7))
    z_win2 = max(6, min(20, n // 3))
    SCALE = 2.4
    out = {}
    for sym in df.columns:
        if sym == BENCH:
            continue
        rs = df[sym] / bench
        smooth = rs.ewm(span=smooth_span).mean()
        ratio = (100 + SCALE * rolling_z(smooth, z_win)).clip(86, 114)
        mom_in = ratio - ratio.ewm(span=mom_span).mean()
        mom = (100 + SCALE * rolling_z(mom_in, z_win2)).clip(86, 114)
        d = pd.DataFrame({"ratio": ratio, "mom": mom}).dropna()
        if len(d) < 2:
            continue
        tail = d.iloc[-TAIL:]
        tail_dates = [ix.strftime("%d %b") for ix in tail.index]
        last = d.iloc[-1]; prev = d.iloc[-2]
        sma20 = df[sym].rolling(min(20, n - 1)).mean().iloc[-1]
        spark = rs.iloc[-min(24, len(rs)):].tolist()
        rel1 = float(rs.iloc[-1] / rs.iloc[-2] - 1) * 100 if len(rs) >= 2 else 0.0
        rel4 = float(rs.iloc[-1] / rs.iloc[-5] - 1) * 100 if len(rs) >= 5 else 0.0
        out[sym] = {
            "ratio": float(last["ratio"]), "mom": float(last["mom"]),
            "dmom": float(last["mom"] - prev["mom"]),
            "quad": quad_of(last["ratio"], last["mom"]),
            "pquad": quad_of(prev["ratio"], prev["mom"]),
            "tail": [[float(r.ratio), float(r.mom)] for r in tail.itertuples()],
            "tail_dates": tail_dates,
            "trend": bool(df[sym].iloc[-1] > sma20),
            "group": NAMES.get(sym, ("", "", ""))[2],
            "spark": [float(x) for x in spark],
            "rel1": round(rel1, 1), "rel4": round(rel4, 1),
            "ratio_series": ratio.reindex(df.index).tolist(),   # alineadas al indice (None al inicio)
            "mom_series": mom.reindex(df.index).tolist(),
        }
    return out

def quad_of(ratio, mom):
    if ratio >= 100 and mom >= 100: return "leading"
    if ratio >= 100 and mom < 100:  return "weakening"
    if ratio < 100 and mom < 100:   return "lagging"
    return "improving"

def build_alerts(rrg):
    out = []
    for s, d in rrg.items():
        q, p = d["quad"], d["pquad"]
        if q == "weakening" and p == "leading":
            out.append((s, "warn", "Pierde liderazgo -> posible recogida de beneficios. Ajusta stop / reduce."))
        elif q == "improving" and p == "lagging":
            out.append((s, "in", "Entra flujo -> acumulacion temprana. Vigilar para sobreponderar."))
        elif q == "leading" and p == "improving":
            out.append((s, "lead", "Liderazgo confirmado -> tendencia relativa al alza."))
        elif q == "lagging" and p == "weakening":
            out.append((s, "down", "Ruptura a la baja -> infraponderar / evitar."))
        elif q == "leading" and d["dmom"] < -1.2:
            out.append((s, "warn", "Impulso enfriandose dentro del liderazgo -> primera senal de aviso."))
    order = {"warn": 0, "in": 1, "down": 2, "lead": 3}
    return sorted(out, key=lambda x: order[x[1]])

def breadth_risk(rrg):
    syms = list(rrg.keys())
    if not syms:
        return {"leaders": 0, "uptrend": 0}, {"score": 0, "label": "Neutral"}
    leaders = round(100 * sum(1 for s in syms if rrg[s]["ratio"] >= 100) / len(syms))
    uptrend = round(100 * sum(1 for s in syms if rrg[s]["trend"]) / len(syms))
    off = [rrg[s]["ratio"] for s in syms if rrg[s]["group"] in ("ciclico", "sensible")]
    deff = [rrg[s]["ratio"] for s in syms if rrg[s]["group"] == "defensivo"]
    avg = lambda a: sum(a) / len(a) if a else 100
    score = avg(off) - avg(deff)
    label = "Risk-ON" if score > 1.5 else "Risk-OFF" if score < -1.5 else "Neutral"
    return {"leaders": leaders, "uptrend": uptrend}, {"score": round(score, 1), "label": label}

# ----------------------------------------------------------------------
# Flujo de dinero por volumen (OBV + Acumulacion/Distribucion)
# ----------------------------------------------------------------------
import numpy as np

def _trend(values, win=20):
    """Tendencia de una serie: cuantas desv. tipicas se mueve a lo largo de la ventana."""
    y = pd.Series(values).dropna().values
    if len(y) < 5:
        return 0.0
    y = y[-win:]
    sd = y.std() or 1.0
    z = (y - y.mean()) / sd
    x = np.arange(len(z))
    b = np.polyfit(x, z, 1)[0]
    return float(b * len(z))

def compute_volume_flow(daily, only=None):
    out = {}
    for sym, d in daily.items():
        if only is not None:
            if sym != only:
                continue
        elif sym == BENCH:
            continue
        if not {"Close", "Volume"}.issubset(d.columns):
            continue
        dd = d.dropna(subset=["Close", "Volume"]).copy()
        if len(dd) < 30:
            continue
        close = dd["Close"]; vol = dd["Volume"].astype(float)
        obv = (np.sign(close.diff().fillna(0)) * vol).cumsum()
        cmf = 0.0
        if {"High", "Low"}.issubset(dd.columns):
            hi, lo = dd["High"], dd["Low"]
            rng = (hi - lo).replace(0, np.nan)
            mfm = (((close - lo) - (hi - close)) / rng).fillna(0)
            mfv = mfm * vol
            adl = mfv.cumsum()
            win = min(20, len(dd))                      # CMF de 20 sesiones (Chaikin Money Flow)
            vsum = vol.iloc[-win:].sum()
            cmf = float(mfv.iloc[-win:].sum() / vsum) if vsum else 0.0
        else:
            adl = obv
        # OBV vs su propia media (EMA ~50 sesiones = 10 semanas): tendencia y cruce reciente
        obv_ema = obv.ewm(span=50, min_periods=10).mean()
        obv_above = bool(obv.iloc[-1] > obv_ema.iloc[-1]) if obv_ema.notna().any() else False
        obv_cross = False
        if len(obv) > 7 and obv_ema.notna().iloc[-7]:
            obv_cross = bool(obv.iloc[-1] > obv_ema.iloc[-1] and obv.iloc[-7] <= obv_ema.iloc[-7])
        obv_t, adl_t, price_t = _trend(obv), _trend(adl), _trend(close)
        flow = (obv_t + adl_t) / 2
        # volumen relativo: volumen de hoy vs su media de 20 sesiones (>1.3x = ruptura con volumen)
        vol20 = float(vol.iloc[-20:].mean()) if len(vol) >= 20 else float(vol.mean())
        vol_rel = round(float(vol.iloc[-1]) / vol20, 2) if vol20 > 0 else 1.0
        vol_rel5 = round(float(vol.iloc[-5:].mean()) / vol20, 2) if (vol20 > 0 and len(vol) >= 5) else vol_rel   # volumen medio 5 sesiones vs 20 (atencion suavizada, menos ruido que 1 dia)
        vol_break = bool(vol_rel >= 1.3 and close.iloc[-1] > close.iloc[-2])   # ruptura al alza con volumen
        diverg = None
        if price_t > 0.5 and flow < -0.5 and cmf < -0.05:
            diverg = "distribucion oculta"   # precio sube pero sale dinero (CMF claramente negativo) -> aviso
        elif price_t < -0.5 and flow > 0.5 and cmf > 0.05:
            diverg = "acumulacion oculta"     # precio baja pero entra dinero (CMF claramente positivo) -> temprano
        # margen anti-confusion: si el CMF esta pegado a cero (-0.05..+0.05), NO se marca divergencia
        # (dos indicadores discrepando con dinero neto ~0 es ruido, no senal)
        # etiqueta de flujo derivada DIRECTAMENTE del CMF (el mismo numero de las tablas), para que todo el
        # panel diga lo mismo: nunca "Neutro" en un sitio y "-0.06" en otro. El OBV/ADL se sigue usando aparte
        # para la 'distribucion oculta' (diverg), que es la senal fuerte.
        label = "Acumulacion" if cmf > 0.05 else "Distribucion" if cmf < -0.05 else "Neutro"
        out[sym] = {"flow": round(flow, 2), "label": label, "diverg": diverg,
                    "cmf": round(cmf, 3), "cmf_pos": bool(cmf > 0),
                    "obv_above": obv_above, "obv_cross": obv_cross,
                    "vol_rel": vol_rel, "vol_break": vol_break, "vol_rel5": vol_rel5,
                    "obv_spark": obv.iloc[-min(40, len(obv)):].tolist()}
    return out

# ----------------------------------------------------------------------
# Heatmap de fuerza relativa temporal (sector vs indice en varios plazos)
# ----------------------------------------------------------------------
def compute_heatmap(daily):
    # Para cada ETF: su rendimiento MENOS el del indice en 1 sem / 1 mes / 3 meses / 6 meses.
    # Verde = bate al mercado; rojo = lo hace peor. Rojo largo + verde corto = rotacion temprana.
    if BENCH not in daily:
        return None
    bench = daily[BENCH]["Close"].dropna()
    wins = [("1 sem", 5), ("1 mes", 21), ("3 meses", 63), ("6 meses", 126)]

    def ret(s, n):
        s = s.dropna()
        if len(s) <= n:
            return None
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    rows = []
    for sym in SECTORS + THEMATIC + EXTRA:
        if sym not in daily or "Close" not in daily[sym]:
            continue
        s = daily[sym]["Close"]
        vals = []
        for _, n in wins:
            r, b = ret(s, n), ret(bench, n)
            vals.append(None if (r is None or b is None) else round((r - b) * 100, 1))
        short_pos = any(v is not None and v > 0 for v in vals[:2])
        long_neg = any(v is not None for v in vals[2:]) and all((v is None or v < 0) for v in vals[2:])
        rows.append({"sym": sym, "vals": vals, "turning": short_pos and long_neg})
    rows.sort(key=lambda r: (not r["turning"], -(r["vals"][1] if r["vals"][1] is not None else -999)))
    return {"cols": [w[0] for w in wins], "rows": rows}

def compute_probabilities(df, rrg, fwd=4):
    # Base historica honesta: para cada ETF y semana, cuenta cuantas senales ESTRUCTURALES
    # cumplia (0-3: precio>media40, RS-momentum>=100, momentum absoluto 3m>0) y mira el
    # retorno a 'fwd' semanas vista. Agrega: % de veces que subio y retorno medio por nivel.
    buckets = {0: [], 1: [], 2: [], 3: []}
    for sym in [c for c in df.columns if c in rrg]:
        s = df[sym]
        if len(s) < 40 + fwd:
            continue
        sma = s.rolling(40).mean()
        abs13 = s / s.shift(13) - 1
        mser = pd.Series(rrg[sym]["mom_series"], index=df.index)
        fwd_ret = s.shift(-fwd) / s - 1
        for i in range(40, len(s) - fwd):
            if pd.isna(sma.iloc[i]) or pd.isna(abs13.iloc[i]) or pd.isna(fwd_ret.iloc[i]):
                continue
            m = mser.iloc[i]
            if m is None or m != m:
                continue
            sc = int(s.iloc[i] > sma.iloc[i]) + int(m >= 100) + int(abs13.iloc[i] > 0)
            buckets[sc].append(float(fwd_ret.iloc[i]))
    stats = {}
    for sc, rets in buckets.items():
        if rets:
            n = len(rets)
            stats[sc] = {"n": n, "pup": round(100 * sum(1 for r in rets if r > 0) / n),
                         "avg": round(100 * sum(rets) / n, 1)}
        else:
            stats[sc] = {"n": 0, "pup": None, "avg": None}
    return {"stats": stats, "fwd": fwd, "weeks": len(df)}

def compute_mean_reversion(symbols):
    # Rentabilidad media anual (CAGR ~10a) vs lo que lleva en el año (YTD). Contexto de extension, NO senal.
    if not MEAN_REVERSION:
        return {}
    out = {}
    start = dt.date.today() - dt.timedelta(days=365 * 11)
    y0 = pd.Timestamp(dt.date(dt.date.today().year, 1, 1))
    for sym in symbols:
        try:
            d, _ = get_ohlcv(sym, start, dt.date.today())
            if d is None or "Close" not in d.columns:
                continue
            c = d["Close"].dropna()
            if len(c) < 250:
                continue
            yrs = (c.index[-1] - c.index[0]).days / 365.25
            if yrs < 1.5:
                continue
            cagr = ((c.iloc[-1] / c.iloc[0]) ** (1.0 / yrs) - 1.0) * 100
            cy = c[c.index >= y0]
            ytd = ((c.iloc[-1] / cy.iloc[0] - 1.0) * 100) if len(cy) > 1 else None
            out[sym] = {"cagr": round(float(cagr), 1),
                        "ytd": round(float(ytd), 1) if ytd is not None else None,
                        "yrs": round(yrs, 1),
                        "margen": round(float(cagr - ytd), 1) if ytd is not None else None}
        except Exception:
            continue
    return out

def compute_early(df, rrg):
    # Zona de ENTRADA TEMPRANA: impulso girándose al alza pero AÚN SIN EXTENDER.
    # Pilla el principio del movimiento (abajo-izquierda del RRG que empieza a curvarse),
    # antes de que sea un líder caro. Filtros: impulso acelerando, fuerza baja, poco estirado.
    rows = []
    for sym in SECTORS + THEMATIC + EXTRA:
        if sym not in df.columns or sym not in rrg:
            continue
        s = df[sym].dropna()
        if len(s) < 16:
            continue
        sma = s.rolling(min(40, len(s))).mean().iloc[-1]
        ext = float(s.iloc[-1] / sma - 1) * 100               # extensión sobre su media de 40s (%)
        ratio = float(rrg[sym]["ratio"]); mom = float(rrg[sym]["mom"])
        mser = [x for x in rrg[sym].get("mom_series", []) if x is not None]
        accel = float(mser[-1] - mser[-5]) if len(mser) >= 5 else 0.0   # aceleración del impulso (4 sem)
        early = (accel > 0) and (mom >= 99) and (ratio <= 101) and (ext <= 6)
        if early:
            score = accel * 1.0 + max(0.0, 101 - ratio) * 0.5 + max(0.0, 6 - ext) * 0.3
            rows.append({"sym": sym, "ratio": round(ratio, 1), "mom": round(mom, 1),
                         "accel": round(accel, 1), "ext": round(ext, 1),
                         "quad": rrg[sym]["quad"], "score": score})
    rows.sort(key=lambda r: -r["score"])
    return rows

def compute_mi_cartera_plan(holdings, rrg, scores, flow, chosen, df=None):
    # Compara TU cartera real con las señales y da acciones concretas por posicion.
    if not holdings:
        return None
    universe = set(SECTORS + THEMATIC + EXTRA + SATELLITES)
    # acciones -> su ETF de sector
    stock2etf = {}
    for etf, sts in SECTOR_STOCKS.items():
        for st in sts:
            stock2etf.setdefault(st.upper(), etf)
    # apalancados -> su subyacente (prefiriendo lo que seguimos)
    lev2base = {}
    for base, lev in LEV3X.items():
        for l in lev.replace("*", "").split("/"):
            l = l.strip().upper()
            if l and (l not in lev2base or base in universe):
                lev2base[l] = base

    def resolve(t):
        t = t.upper()
        # limpiar sufijos de instrumento: AAPL-CFD -> AAPL, GLD-ETC -> GLD, TLT-5L -> TLT...
        base_t = t
        for suf in ("-CFD", "-ETF", "-ETC", "-PERP", "-PVT", "-5L", "-3L", "-2X"):
            if base_t.endswith(suf):
                base_t = base_t[: -len(suf)]
                break
        # 1) alias explicito (acciones/ETFs UCITS mapeados a su ETF de referencia del terminal)
        for key in (t, base_t):
            if key in ALIAS2ETF:
                al = ALIAS2ETF[key]
                if al is None:
                    return None, "no seguido"
                return al, ("vía alias" if al != key else "ETF")
        # 2) universo directo, apalancados y acciones de SECTOR_STOCKS
        for key in (t, base_t):
            if key in universe:
                return key, "ETF"
            if key in lev2base:
                return lev2base[key], "apalancado"
            if key in stock2etf:
                return stock2etf[key], "acción"
        return None, "no seguido"

    sc_map = {r["sym"]: r for r in scores} if scores else {}
    rows = []
    held_bases = set()
    for row in holdings:
        tk, broker, eur = row[0], row[1], row[2]
        tipo = row[4] if len(row) >= 5 else "etf"
        if tipo == "cesta":
            rows.append({"tk": tk, "broker": broker, "eur": eur, "base": None, "kind": "cesta",
                         "act": "detallar", "col": "#5B8CFF",
                         "why": "cesta agregada: pega las posiciones una a una en MI_CARTERA para evaluarlas."})
            continue
        base, kind = resolve(tk)
        if base is None or base not in rrg:
            rows.append({"tk": tk, "broker": broker, "eur": eur, "base": None, "kind": kind,
                         "act": "no seguido", "col": "#5E708A",
                         "why": "no está en el universo del panel; el tool no puede evaluarlo."})
            continue
        held_bases.add(base)
        quad = rrg[base]["quad"]
        sc = sc_map.get(base, {}).get("score")
        distrib = sc_map.get(base, {}).get("distrib", False)
        qn = QUAD.get(quad, (quad, "#888"))[0]
        if distrib:
            act, col, why = "VENDER / ROTAR", "#F4607A", f"distribución oculta (sale dinero) en {base}."
        elif quad == "lagging" or (sc is not None and sc <= 2):
            act, col, why = "VENDER / ROTAR", "#F4607A", f"{base} en {qn}" + (f", scoring {sc}/5" if sc is not None else "") + " → fuera."
        elif quad == "weakening":
            act, col, why = "REDUCIR / VIGILAR", "#F4B740", f"{base} en {qn}: impulso girándose, recoger beneficios / poner stop."
        elif quad in ("leading", "improving") and (sc is None or sc >= 3):
            act, col, why = "MANTENER", "#2FD08A", f"{base} en {qn}" + (f", scoring {sc}/5" if sc is not None else "") + ": sigue fuerte."
        else:
            act, col, why = "VIGILAR", "#9FB0C8", f"{base} en {qn}, scoring {sc}/5."
        via = "" if (base == tk.upper()) else f" (vía {base})"
        # --- VEREDICTO DE CORTE vs AGUANTE + trampa de esperanza ---
        # ¿Cuánto ha caído esta posición desde su máximo reciente? ¿El flujo aún sale (trampa) o ya frena (base)?
        corte = None
        f = (flow or {}).get(base, {}) or {}
        cmf = f.get("cmf")
        dd_pos = None
        if df is not None and base in getattr(df, "columns", []):
            try:
                ser = df[base].dropna()
                if len(ser) >= 10:
                    dd_pos = float(ser.iloc[-1] / ser.iloc[-min(52, len(ser)):].max() * 100) - 100
            except Exception:
                dd_pos = None
        _sale = (cmf is not None and cmf < -0.05)
        _frena = (cmf is not None and cmf >= -0.05)
        if act.startswith("VENDER") or act.startswith("REDUCIR"):
            if _sale and dd_pos is not None and dd_pos <= -8:
                corte = ("trampa", "#F4607A", f"⛔ El sistema dice CORTAR: cae {dd_pos:.0f}% y el dinero SIGUE saliendo (CMF {cmf:+.2f}). "
                         "Aguantar aquí es «esperar a recuperar» — la trampa de esperanza que hace grandes las pérdidas pequeñas.")
            elif _frena and dd_pos is not None and dd_pos <= -8:
                corte = ("base", "#F4B740", f"⚠ Señal de salida PERO el flujo ha dejado de sangrar (CMF {cmf:+.2f}) tras caer {dd_pos:.0f}%. "
                         "Zona de posible suelo: si vas a darle margen, ponle un stop concreto — no lo dejes «a ver si sube».")
            elif _sale:
                corte = ("trampa", "#F4607A", f"El dinero sale (CMF {cmf:+.2f}) — la señal de salida está confirmada por flujo.")
        rows.append({"tk": tk, "broker": broker, "eur": eur, "base": base, "kind": kind,
                     "act": act, "col": col, "why": why, "quad": qn, "sc": sc, "via": via,
                     "dd_pos": dd_pos, "cmf": cmf, "corte": corte})
    # ROTAR HACIA: lo que recomienda la cartera y aún no tienes
    rec = []
    for s, d in (chosen or []):
        if s not in held_bases:
            sc = sc_map.get(s, {}).get("score")
            rec.append({"sym": s, "quad": QUAD.get(d["quad"], (d["quad"], "#888"))[0], "sc": sc})
    total = sum(r[2] for r in holdings if isinstance(r[2], (int, float)))
    return {"rows": rows, "rotar_hacia": rec, "total": total,
            "n_vender": sum(1 for r in rows if r["act"].startswith("VENDER")),
            "n_mantener": sum(1 for r in rows if r["act"] == "MANTENER")}


def compute_apalancamiento(holdings, broker_info):
    """Consolida la exposicion REAL (importe x apalancamiento) de los 3 brokers y simula
    el impacto de caidas del S&P (STRESS_DD) sobre el equity de cada broker.
    Aproximacion de choque de 1 dia: perdida = importe x apalancamiento x beta_tipo x caida.
    OJO: los productos de reset diario en un tramo de varios dias con volatilidad pierden MAS
    que esto (decay); el escenario es el suelo optimista, no el pesimista."""
    if not holdings:
        return None
    rows, por_broker = [], {}
    for row in holdings:
        tk, broker, eur = row[0], row[1], row[2]
        lev = row[3] if len(row) >= 4 else 1
        tipo = row[4] if len(row) >= 5 else "etf"
        if not isinstance(eur, (int, float)) or eur <= 0:
            continue
        beta = STRESS_BETA.get(tipo, 1.0)
        expo = eur * lev
        stress = {dd: eur * lev * beta * (dd / 100.0) for dd in STRESS_DD}
        rows.append({"tk": tk, "broker": broker, "eur": eur, "lev": lev, "tipo": tipo,
                     "beta": beta, "expo": expo, "stress": stress})
        b = por_broker.setdefault(broker, {"eur": 0.0, "expo": 0.0,
                                           "stress": {dd: 0.0 for dd in STRESS_DD}})
        b["eur"] += eur
        b["expo"] += expo
        for dd in STRESS_DD:
            b["stress"][dd] += stress[dd]
    tot_eur = sum(b["eur"] for b in por_broker.values()) or 1.0
    tot_expo = sum(b["expo"] for b in por_broker.values())
    tot_stress = {dd: sum(b["stress"][dd] for b in por_broker.values()) for dd in STRESS_DD}
    # por broker: equity tras el choque y, si hay datos de margen, el nivel de margen estimado
    brokers = []
    for name, b in por_broker.items():
        info = (broker_info or {}).get(name, {}) or {}
        equity = info.get("equity") or b["eur"]
        esc = {}
        for dd in STRESS_DD:
            loss = b["stress"][dd]
            eq_after = equity + loss
            nivel = info.get("nivel_margen")
            # aprox.: el margen requerido no cambia -> el nivel cae en proporcion al equity
            nivel_after = (nivel * eq_after / equity) if (nivel and equity) else None
            stopout = info.get("stopout")
            estado = "ok"
            pct_loss = (loss / equity * 100) if equity else 0
            if nivel_after is not None and stopout is not None:
                if nivel_after <= stopout:
                    estado = "STOP-OUT"
                elif nivel_after <= stopout * 1.6:
                    estado = "margin call"
                elif nivel_after <= 100:
                    estado = "sin margen libre"
            elif eq_after <= 0 or pct_loss <= -95:
                estado = "cuenta a cero"
            elif pct_loss <= -70:
                estado = "riesgo de liquidación"       # perpetuos/apalancados: el broker liquida mucho antes de llegar aqui
            elif pct_loss <= -45:
                estado = "pérdida severa"
            esc[dd] = {"loss": loss, "eq_after": eq_after, "pct": (loss / equity * 100 if equity else 0),
                       "nivel_after": nivel_after, "estado": estado}
        brokers.append({"broker": name, "eur": b["eur"], "expo": b["expo"],
                        "lev_ef": (b["expo"] / equity if equity else 0),
                        "equity": equity, "info": info, "esc": esc})
    brokers.sort(key=lambda x: -x["expo"])
    tot_equity = sum(x["equity"] for x in brokers) or tot_eur
    return {"rows": rows, "brokers": brokers, "tot_eur": tot_equity, "tot_expo": tot_expo,
            "lev_ef": tot_expo / tot_equity, "tot_stress": tot_stress}


def compute_candidato(cartera_syms, leaders, flow, scores, rrg):
    """De los ETFs que ESTAN en la cartera de la semana, analiza sus acciones (fuerza relativa,
    aceleracion, fase, extension) y elige UN candidato por sector + UN top absoluto.
    Criterio cuantitativo, sin discrecion: el sistema elige, tu solo ejecutas (o no)."""
    if not cartera_syms or not leaders:
        return None
    sc_map = {r["sym"]: r for r in (scores or [])}
    per = []
    for etf in cartera_syms:
        rows = leaders.get(etf) or []
        best, best_pts, razones = None, -1e9, []
        for r in rows:
            rs = r.get("rs") or 0
            hi = r.get("hi") or 0
            drs = r.get("drs") if r.get("drs") is not None else 0
            ph = r.get("phase")
            if rs < 55 or ph == "baja":
                continue                                  # ni debiles ni cayendo
            pts = float(rs)                               # base: percentil de fuerza (1-99)
            pts += min(max(drs, -25), 25) * 1.2           # aceleracion 3m del percentil
            pts += {"sube": 12, "base": 8}.get(ph, 0)     # fase sana suma
            if ph == "distrib":
                pts -= 14                                  # techo formandose resta
            if hi > 92:
                pts -= (hi - 92) * 2.0                     # extendida sobre maximos: peor entrada
            if hi < 55:
                pts -= (55 - hi) * 0.5                     # demasiado hundida: cuchillo cayendo
            if pts > best_pts:
                best_pts, best = pts, r
        if not best:
            continue
        par = sc_map.get(etf, {}) or {}
        f = (flow or {}).get(etf, {}) or {}
        cmf = f.get("cmf")
        etf_boost = (par.get("score") or 0) * 3.0
        if cmf is not None and cmf > 0.05:
            etf_boost += 10
        if par.get("distrib"):
            etf_boost -= 30
        why = []
        why.append(f"RS {best['rs']}")
        if best.get("drs"):
            why.append(f"acelera {best['drs']:+d}")
        pe, pl, _pc = PHASE_INFO.get(best.get("phase"), ("", "?", ""))
        why.append(f"fase {pe} {pl}")
        why.append(f"{best['hi']}% del max 52s")
        if par.get("score") is not None:
            why.append(f"ETF {etf} {par['score']}/5")
        if cmf is not None:
            why.append("flujo del sector " + ("entra" if cmf > 0.05 else "sale" if cmf < -0.05 else "plano"))
        per.append({"etf": etf, "stock": best, "pts": round(best_pts, 1),
                    "tot": round(best_pts + etf_boost, 1), "score_etf": par.get("score"),
                    "cmf": cmf, "why": " · ".join(why)})
    if not per:
        return None
    per.sort(key=lambda x: -x["tot"])
    return {"per": per, "top": per[0]}


# --- SENAL CONTRARIA 0/3: ledger fuera-de-muestra + tamano sugerido ---
CONTRA_FILE = os.path.join(SEGUIMIENTO_DIR, "senales_contrarias.json")
CONTRA_BAK = os.path.join(SEGUIMIENTO_DIR, "senales_contrarias.bak.json")
WIRE_FILE = os.path.join(SEGUIMIENTO_DIR, "senales_wire.json")
WIRE_BAK = os.path.join(SEGUIMIENTO_DIR, "senales_wire.bak.json")

def update_wire_ledger(items, close_date):
    """Persiste las senales del wire por fecha de CIERRE (idempotente: re-ejecutar el mismo dia
    sobreescribe ese dia, no duplica). Solo guarda senales con activo concreto (sym)."""
    os.makedirs(SEGUIMIENTO_DIR, exist_ok=True)
    recs = []
    if os.path.exists(WIRE_FILE):
        try:
            with open(WIRE_FILE, "r", encoding="utf-8") as fh:
                recs = json.load(fh)
        except Exception:
            try:
                with open(WIRE_BAK, "r", encoding="utf-8") as fh:
                    recs = json.load(fh)
            except Exception:
                recs = []
    d = str(close_date)
    recs = [r for r in recs if r.get("date") != d]
    for it in (items or []):
        if it.get("sym"):
            recs.append({"date": d, "tag": it["tag"], "sym": it["sym"], "dir": int(it.get("dir", 0))})
    dates = sorted({r["date"] for r in recs})[-60:]
    keep = set(dates)
    recs = [r for r in recs if r["date"] in keep]
    try:
        with open(WIRE_FILE, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=0)
        with open(WIRE_BAK, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=0)
    except Exception:
        pass
    return recs

def analyze_wire_persistence(recs, k=8):
    """Linea de tiempo de las ultimas k sesiones por senal (tag+activo): racha final en la misma
    direccion, recurrencia y contradicciones. Un dia es ruido; tres seguidos en la misma direccion
    es un patron confirmandose; direcciones alternas es mercado de dos caras."""
    if not recs:
        return None
    dates = sorted({r["date"] for r in recs})[-k:]
    if len(dates) < 2:
        return None
    idx = {d: i for i, d in enumerate(dates)}
    sigs = {}
    for r in recs:
        if r["date"] not in idx:
            continue
        key = (r.get("tag"), r.get("sym"))
        sigs.setdefault(key, [None] * len(dates))[idx[r["date"]]] = int(r.get("dir", 0))
    out = []
    for (tag, sym), tl in sigs.items():
        pres = [v for v in tl if v is not None]
        if not pres:
            continue
        streak, dcur = 0, None
        for v in reversed(tl):
            if v is None:
                break
            if dcur is None:
                dcur = v
            if v == dcur:
                streak += 1
            else:
                break
        contradice = (len(tl) >= 2 and tl[-1] is not None and tl[-2] is not None and tl[-1] != tl[-2])
        ndirs = len(set(pres))
        if streak >= 3:
            verd, lvl = f"CONFIRMÁNDOSE — {streak} sesiones seguidas", "alta"
        elif contradice:
            verd, lvl = "⚠ contradice la sesión anterior — ruido", "ruido"
        elif ndirs > 1 and len(pres) >= 2:
            verd, lvl = "dos direcciones — mercado indeciso", "ruido"
        elif streak == 2:
            verd, lvl = "2 sesiones — a una de confirmar", "media"
        elif len(pres) >= 3:
            verd, lvl = f"recurrente ({len(pres)}/{len(dates)})", "media"
        else:
            verd, lvl = "puntual — sin validez aún", "baja"
        out.append({"tag": tag, "sym": sym, "tl": tl, "streak": streak, "n": len(pres),
                    "verd": verd, "lvl": lvl, "today": tl[-1] is not None,
                    "dir": tl[-1] if tl[-1] is not None else pres[-1], "contradice": contradice})
    out.sort(key=lambda x: (not x["today"], -x["streak"], -x["n"]))
    return {"dates": dates, "sigs": out[:14]}


def compute_contrarian(rrg, scores, flow):
    """Detecta las senales contrarias de esta semana: activos con 0-1/3 senales estructurales
    (los mas machacados), giro VERTICAL del impulso y flujo que NO sale. Es tu patron 0/3."""
    _sc3 = {}
    for r in (scores or []):
        _sc3[r["sym"]] = sum(1 for _, v in r["parts"][:3] if v)
    sigs = []
    for s, d in rrg.items():
        if s == BENCH:
            continue
        tail = d.get("tail") or []
        if len(tail) < 5:
            continue
        r_now, m_now = tail[-1]
        r_prev, m_prev = tail[-4]
        dmom, drat = m_now - m_prev, r_now - r_prev
        abajo = (d["quad"] == "lagging") or (r_now <= 96.5 and m_now <= 102)
        if not abajo or dmom < 1.5:
            continue
        vert = dmom / max(0.6, abs(drat))
        if vert < 1.8:
            continue
        n3 = _sc3.get(s)
        if n3 is None or n3 > 1:
            continue                                       # solo 0/3 y 1/3: lo dormido de verdad
        cmf = ((flow or {}).get(s, {}) or {}).get("cmf")
        if cmf is not None and cmf < -0.05:
            continue                                       # si el dinero SALE, ni contraria ni nada
        sigs.append({"sym": s, "n3": n3, "vert": round(vert, 1), "dmom": round(dmom, 1), "cmf": cmf})
    sigs.sort(key=lambda x: (x["n3"], -x["vert"]))
    return sigs[:CONTRARIAN_MAX_SIGS]

def update_contrarian_ledger(sigs, px_now, datestr, df):
    """Persiste las senales de esta semana y evalua las que ya maduraron (>= horizonte).
    Esto construye la estadistica FUERA DE MUESTRA: la unica que valida de verdad tu 64%."""
    os.makedirs(SEGUIMIENTO_DIR, exist_ok=True)
    recs = []
    if os.path.exists(CONTRA_FILE):
        try:
            with open(CONTRA_FILE, "r", encoding="utf-8") as fh:
                recs = json.load(fh)
        except Exception:
            try:
                with open(CONTRA_BAK, "r", encoding="utf-8") as fh:
                    recs = json.load(fh)
            except Exception:
                recs = []
    try:
        wk = pd.Timestamp(datestr).strftime("%G-W%V")
    except Exception:
        wk = str(datestr)
    have = {(r.get("week"), r.get("sym")) for r in recs}
    for s in (sigs or []):
        key = (wk, s["sym"])
        px = px_now.get(s["sym"])
        if key not in have and px:
            recs.append({"week": wk, "date": str(datestr), "sym": s["sym"], "px": float(px),
                         "n3": s["n3"], "vert": s["vert"]})
    recs.sort(key=lambda r: (r.get("week", ""), r.get("sym", "")))
    try:
        with open(CONTRA_FILE, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=0)
        with open(CONTRA_BAK, "w", encoding="utf-8") as fh:
            json.dump(recs, fh, ensure_ascii=False, indent=0)
    except Exception:
        pass
    # evaluacion de las maduras con las series semanales
    outs = []
    for r in recs:
        sym = r.get("sym")
        if sym not in df.columns:
            continue
        s = df[sym].dropna()
        try:
            d0 = pd.Timestamp(r.get("date"))
        except Exception:
            continue
        i = int(s.index.searchsorted(d0))
        if i >= len(s):
            continue
        if i + CONTRARIAN_HORIZON_W < len(s):
            ret = float(s.iloc[i + CONTRARIAN_HORIZON_W] / s.iloc[i] - 1.0)
            outs.append({"sym": sym, "week": r.get("week"), "ret": ret})
    stats = None
    if outs:
        wins = sum(1 for o in outs if o["ret"] > 0)
        rets = [o["ret"] for o in outs]
        avg = sum(rets) / len(rets)
        wl = [x for x in rets if x > 0]
        ll = [-x for x in rets if x <= 0]
        avg_w = (sum(wl) / len(wl)) if wl else 0.0
        avg_l = (sum(ll) / len(ll)) if ll else 0.0
        p = wins / len(outs)
        kelly = (p - (1 - p) / (avg_w / avg_l)) if (avg_w > 0 and avg_l > 0) else None
        stats = {"n": len(outs), "wins": wins, "winrate": round(100 * p),
                 "avg": round(100 * avg, 2), "avg_w": round(100 * avg_w, 2),
                 "avg_l": round(100 * avg_l, 2),
                 "kelly4": (round(max(0.0, kelly) / 4 * 100, 1) if kelly is not None else None)}
    return {"recs": recs, "stats": stats, "week": wk}


def compute_scores(df, rrg, daily, flow):
    # Puntuacion 0-5 por ETF (deliverable para decidir en 5 min):
    #  +1 precio > su SMA de 40 semanas | +1 RS-momentum subiendo (vs SPY)
    #  +1 momentum absoluto 3m > 0 | +1 OBV por encima de su media | +1 CMF > 0
    rows = []
    for sym in SECTORS + THEMATIC + EXTRA:
        if sym not in df.columns or sym not in rrg:
            continue
        s = df[sym].dropna()
        if len(s) < 16:
            continue
        sma = s.rolling(min(40, len(s))).mean().iloc[-1]
        price_above = bool(s.iloc[-1] > sma)
        rs_rising = bool(rrg[sym]["mom"] >= 100)
        n = min(13, len(s) - 1)
        abs_mom = float(s.iloc[-1] / s.iloc[-1 - n] - 1)
        abs_pos = bool(abs_mom > 0)
        f = flow.get(sym, {})
        diverg = f.get("diverg")
        distrib = (diverg == "distribucion oculta")     # precio sube pero el dinero sale
        obv_ok = bool(f.get("obv_above")) and not distrib  # no se puntua "entra dinero" si hay distribucion
        cmf_ok = bool(f.get("cmf_pos"))
        parts = [("precio>SMA40", price_above), ("RS subiendo", rs_rising),
                 ("mom.abs>0", abs_pos), ("OBV>media", obv_ok), ("CMF>0", cmf_ok)]
        score = sum(1 for _, v in parts if v)
        rows.append({"sym": sym, "score": score, "parts": parts, "distrib": distrib, "above_sma": price_above,
                     "obv_cross": bool(f.get("obv_cross")), "abs_mom": round(abs_mom * 100, 1)})
    rows.sort(key=lambda r: (-r["score"], -r["abs_mom"]))
    return rows

def heatmap_color(v):
    if v is None:
        return "background:#141A26;color:#3A4658"
    x = max(-1.0, min(1.0, v / 8.0))
    if x >= 0:
        return f"background:rgba(47,208,138,{0.12 + 0.78*x:.2f});color:#06140C"
    return f"background:rgba(244,96,122,{0.12 + 0.78*(-x):.2f});color:#1A0608"


# ----------------------------------------------------------------------
# Backtest causal: sobreponderar Lider+Mejorando vs comprar y mantener el indice
# ----------------------------------------------------------------------
def backtest(df, rrg, hold=("leading", "improving"), trend=None, max_pos=None, weight=None, buffer=None):
    trend = TREND_FILTER if trend is None else trend
    max_pos = MAX_POSICIONES if max_pos is None else max_pos
    weight = PESO if weight is None else weight
    buffer = BUFFER if buffer is None else buffer
    idx = list(df.index)
    rets = df.pct_change()
    bench_ret = rets[BENCH].tolist()
    sectors = list(rrg.keys())
    R = {s: rrg[s]["ratio_series"] for s in sectors}
    M = {s: rrg[s]["mom_series"] for s in sectors}
    ok = lambda v: v is not None and v == v
    # filtro de tendencia del mercado: S&P vs su media de TREND_MA_WEEKS
    spy = df[BENCH]
    ma = spy.rolling(min(TREND_MA_WEEKS, len(spy)), min_periods=5).mean().tolist()
    spyl = spy.tolist()
    # volatilidad movil (13s) para el peso por volatilidad inversa
    vol = {s: rets[s].rolling(13, min_periods=4).std().tolist() for s in sectors}
    held = set()   # para la histeresis
    eq_s, eq_b = [1.0], [1.0]; wins = weeks = 0; in_mkt = 0
    for i in range(1, len(idx)):
        br = bench_ret[i] if bench_ret[i] == bench_ret[i] else 0.0
        bull = not (trend and ok(ma[i-1]) and spyl[i-1] < ma[i-1])
        chosen = []
        if bull:
            for s in sectors:
                rr, mm = R[s][i-1], M[s][i-1]
                if not (ok(rr) and ok(mm)):
                    held.discard(s); continue
                q = quad_of(rr, mm)
                strong = q in hold and rr > 100 + buffer and mm > 100 - buffer
                weak = not (q in hold) or rr < 100 - buffer or mm < 100 - buffer
                if strong:
                    held.add(s)
                elif weak:
                    held.discard(s)
                if s in held:
                    chosen.append(s)
            # tope: las de mayor impulso
            if max_pos and len(chosen) > max_pos:
                chosen = sorted(chosen, key=lambda s: -(M[s][i-1] or 0))[:max_pos]
        if chosen:
            ws = {}
            for s in chosen:
                if weight == "volatilidad":
                    v = vol[s][i-1] if ok(vol[s][i-1]) and vol[s][i-1] > 1e-6 else 0.02
                    ws[s] = 1.0 / v
                elif weight == "impulso":
                    ws[s] = max(0.1, (M[s][i-1] or 100) - 99)
                else:
                    ws[s] = 1.0
            tot = sum(ws.values()) or 1.0
            r = 0.0
            for s in chosen:
                ri = rets[s].iloc[i]
                r += (ws[s] / tot) * (ri if ri == ri else 0.0)
            in_mkt += 1
        else:
            r = 0.0   # liquidez (mercado bajista o nada elegido)
        eq_s.append(eq_s[-1] * (1 + r))
        eq_b.append(eq_b[-1] * (1 + br))
        weeks += 1
        if r > br:
            wins += 1
    def mdd(curve):
        peak = curve[0]; worst = 0.0
        for v in curve:
            peak = max(peak, v); worst = min(worst, v / peak - 1)
        return worst * 100
    return {
        "eq_s": eq_s, "eq_b": eq_b, "dates": [str(d.date()) for d in idx],
        "tot_s": round((eq_s[-1] - 1) * 100, 1), "tot_b": round((eq_b[-1] - 1) * 100, 1),
        "mdd_s": round(mdd(eq_s), 1), "mdd_b": round(mdd(eq_b), 1),
        "winrate": int(round(100 * wins / max(weeks, 1))), "weeks": weeks,
        "exposure": int(round(100 * in_mkt / max(weeks, 1))),
    }


# ----------------------------------------------------------------------
# Caidas del S&P 500: frecuencia anual, probabilidad y plan de liquidez
# ----------------------------------------------------------------------
def compute_seasonality(close, ahead=5):
    # Estacionalidad por MEDIA-QUINCENA (1H = dias 1-15, 2H = 16-fin de mes) sobre el historico largo.
    # Para el periodo actual y los proximos: % de años con retorno positivo y retorno medio.
    s = close.dropna()
    if s is None or len(s) < 252 * 8:
        return None
    d = pd.DataFrame({"c": s})
    d["year"] = d.index.year
    d["month"] = d.index.month
    d["half"] = np.where(d.index.day <= 15, 1, 2)
    grp = d.groupby(["year", "month", "half"])["c"]
    ret = (grp.last() / grp.first() - 1).reset_index()
    stats = {}
    for (m, h), g in ret.groupby(["month", "half"]):
        vals = g["c"].dropna().values
        if len(vals) >= 5:
            stats[(m, h)] = {"avg": round(100 * float(vals.mean()), 2),
                             "pup": int(round(100 * float((vals > 0).mean()))), "n": int(len(vals))}
    mes = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    today = dt.date.today()
    m, h = today.month, (1 if today.day <= 15 else 2)
    rows = []
    for k in range(ahead + 1):
        st = stats.get((m, h))
        rows.append({"label": f"{'1ª' if h == 1 else '2ª'} mitad de {mes[m-1]}",
                     "now": k == 0, "pup": st["pup"] if st else None, "avg": st["avg"] if st else None,
                     "n": st["n"] if st else 0})
        if h == 1:
            h = 2
        else:
            h = 1; m = 1 if m == 12 else m + 1
    return {"rows": rows, "years": int(s.index.year.nunique())}


def _fetch_long(stooq_sym, etf_fallback, yahoo_sym):
    """Historia LARGA de un indice (Stooq -> ETF -> Yahoo). Devuelve (close, fuente, hl) donde hl=High/Low o None."""
    start = dt.date.today() - dt.timedelta(days=365 * 60)
    try:
        r = requests.get(f"https://stooq.com/q/d/l/?s={stooq_sym}&i=d", timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        df = pd.read_csv(StringIO(r.text))
        if "Close" in df.columns and len(df) > 1000:
            df["Date"] = pd.to_datetime(df["Date"])
            df = df.set_index("Date").sort_index()
            hl = df[["High", "Low"]] if {"High", "Low"}.issubset(df.columns) else None
            return df["Close"], stooq_sym.upper(), hl
    except Exception:
        pass
    if etf_fallback:
        d, _ = get_ohlcv(etf_fallback, start, dt.date.today())
        if d is not None and "Close" in d.columns:
            hl = d[["High", "Low"]] if {"High", "Low"}.issubset(d.columns) else None
            return d["Close"].sort_index(), etf_fallback, hl
    if yf is not None:
        try:
            g = yf.download(yahoo_sym, start=start, progress=False, auto_adjust=False)   # sin ajustar: % de caída fieles al índice real
            c = g["Close"]
            if hasattr(c, "columns"):
                c = c.iloc[:, 0]
            hl = None
            if {"High", "Low"}.issubset(g.columns):
                h, l = g["High"], g["Low"]
                if hasattr(h, "columns"):
                    h = h.iloc[:, 0]
                if hasattr(l, "columns"):
                    l = l.iloc[:, 0]
                hl = pd.DataFrame({"High": h, "Low": l}).dropna()
            return c.dropna().sort_index(), yahoo_sym, hl
        except Exception:
            pass
    return None, "—", None

def fetch_long_close():
    """Historia LARGA del S&P 500 para estadistica de caidas."""
    return _fetch_long("^spx", "SPY", "^GSPC")

def drawdown_stats(close, thresholds, hl=None):
    close = close.dropna()
    if len(close) < 250:
        return None, None
    years = sorted(set(close.index.year))
    cur_year = dt.date.today().year
    today_md = (dt.date.today().month, dt.date.today().day)

    def count(peak_src, trough_src):
        counts = {t: {y: 0 for y in years} for t in thresholds}
        rest_hit = {t: set() for t in thresholds}
        roll_peak = peak_src.rolling(252, min_periods=20).max()   # pico de las ~52 semanas previas (pico reciente), no el maximo historico
        in_ev = {t: False for t in thresholds}
        for date, p in peak_src.items():
            peak = roll_peak.loc[date]
            if peak is None or peak != peak or peak <= 0:
                continue
            dd = (trough_src.loc[date] / peak - 1) * 100
            in_window = (date.month, date.day) >= today_md
            for t in thresholds:
                eff = (t - DD_GAP_PP) if t >= 10 else t   # cubos grandes (>=10%) captan el hueco nocturno del futuro/CFD
                if not in_ev[t] and dd <= -eff:
                    in_ev[t] = True
                    counts[t][date.year] += 1
                elif in_ev[t] and dd > -eff / 2.0:
                    in_ev[t] = False
                if dd <= -eff and in_window and date.year < cur_year:
                    rest_hit[t].add(date.year)
        return counts, rest_hit

    basis = "cierre"
    counts, rest_hit = count(close, close)
    if hl is not None and {"High", "Low"}.issubset(hl.columns):
        hh = hl["High"].reindex(close.index).ffill().dropna()
        ll = hl["Low"].reindex(close.index).ffill().dropna()
        idx = hh.index.intersection(ll.index)
        if len(idx) > 250:
            counts, rest_hit = count(hh.loc[idx], ll.loc[idx])   # intradía: pico=máx de High, caída con Low
            basis = "intradía"
    complete = [y for y in years if y < cur_year]
    last20 = [y for y in complete if y >= cur_year - 20]
    def stats(t, yrs):
        if not yrs:
            return 0.0, 0
        vals = [counts[t][y] for y in yrs]
        return round(sum(vals) / len(yrs), 1), int(round(100 * sum(1 for v in vals if v >= 1) / len(yrs)))
    out = {}
    for t in thresholds:
        a20, p20 = stats(t, last20)
        af, pf = stats(t, complete)
        rest = int(round(100 * len(rest_hit[t] & set(complete)) / len(complete))) if complete else 0
        out[t] = {"avg20": a20, "prob20": p20, "avgfull": af, "probfull": pf,
                  "ytd": counts[t].get(cur_year, 0), "rest": rest}
    meta = {"start": years[0], "end": years[-1], "n20": len(last20), "nfull": len(complete),
            "cur_year": cur_year, "basis": basis}
    return out, meta

def fetch_fear_greed():
    """Indice Fear & Greed de CNN (0-100, sentimiento contrario). Devuelve dict o None si falla."""
    try:
        r = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                         timeout=20, headers={
                             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                           "(KHTML, like Gecko) Chrome/123.0 Safari/537.36",
                             "Accept": "application/json"})
        fg = r.json().get("fear_and_greed", {})
        sc = fg.get("score")
        if sc is None:
            return None
        def _g(k):
            v = fg.get(k)
            return round(float(v)) if v is not None else None
        return {"score": round(float(sc)), "rating": (fg.get("rating") or "").strip(),
                "prev": _g("previous_close"), "week": _g("previous_1_week"),
                "month": _g("previous_1_month"), "year": _g("previous_1_year")}
    except Exception:
        return None

def cash_plan(close):
    close = close.dropna()
    peak = float(close.cummax().iloc[-1])
    last = float(close.iloc[-1])
    rungs = []
    for thr, pct in CASH_PLAN:
        level = peak * (1 - thr / 100)
        rungs.append({"thr": thr, "pct": pct, "level": round(level, 2), "hit": last <= level})
    return {"peak": round(peak, 2), "last": round(last, 2), "dd": round((last / peak - 1) * 100, 1), "rungs": rungs}

def fetch_fx():
    """EUR/USD avanzado para la cobertura divisa (Stooq -> Yahoo)."""
    c = None
    try:
        r = requests.get("https://stooq.com/q/d/l/?s=eurusd&i=d", timeout=20,
                         headers={"User-Agent": "Mozilla/5.0"})
        df = pd.read_csv(StringIO(r.text))
        if "Close" in df.columns and len(df) > 60:
            df["Date"] = pd.to_datetime(df["Date"])
            c = df.set_index("Date")["Close"].sort_index()
    except Exception:
        c = None
    if c is None and yf is not None:
        try:
            g = yf.download("EURUSD=X", period="3y", progress=False)["Close"]
            if hasattr(g, "columns"):
                g = g.iloc[:, 0]
            c = g.dropna()
        except Exception:
            c = None
    if c is None or len(c) < 60:
        return None
    last = float(c.iloc[-1])
    ma50 = float(c.rolling(min(50, len(c))).mean().iloc[-1])
    ma200 = float(c.rolling(min(200, len(c))).mean().iloc[-1])
    def roc(k):
        return round(float(c.iloc[-1] / c.iloc[-min(k, len(c) - 1)] - 1) * 100, 1) if len(c) > k else None
    win = c.iloc[-min(252, len(c)):]
    hi52, lo52 = float(win.max()), float(win.min())
    pos = round(100 * (last - lo52) / ((hi52 - lo52) or 1e-9))   # 0=minimo 52s, 100=maximo 52s
    cross = "alcista (50>200)" if ma50 > ma200 else "bajista (50<200)"
    # fuerza de tendencia del euro: combinacion de posicion vs medias y momentum
    score = (last > ma50) + (last > ma200) + (ma50 > ma200) + (roc(65) or 0 > 0)
    return {"last": round(last, 4), "ma50": round(ma50, 4), "ma200": round(ma200, 4),
            "roc1m": roc(22), "roc3m": roc(65), "roc6m": roc(130),
            "hi52": round(hi52, 4), "lo52": round(lo52, 4), "pos": pos, "cross": cross,
            "above50": last > ma50, "above200": last > ma200, "strong": score >= 3,
            "spark": [float(x) for x in c.iloc[-min(160, len(c)):].tolist()]}

# ----------------------------------------------------------------------
# Acciones lideres por sector (RS Rating 1-99, estilo IBD/O'Neil)
# ----------------------------------------------------------------------
def fetch_stock_universe():
    print(f"\n[Universo RS: '{RS_UNIVERSE}']")
    if RS_UNIVERSE == "sp500":
        closes = fetch_sp500_universe()
        if len(closes) >= 150:
            # Asegurar que TODAS las acciones de SECTOR_STOCKS (las de agua de FIW incluidas) entren
            # en el ranking aunque NO sean del S&P 500 (p.ej. MLI Mueller) o falten en la lista (p.ej. FERG).
            # Sin esto, esas acciones no tienen percentil y desaparecen del panel.
            extra = sorted({t for lst in SECTOR_STOCKS.values() for t in lst if t not in closes})
            if extra:
                print(f"  +{len(extra)} acciones de SECTOR_STOCKS fuera del S&P (incluye agua FIW: MLI, FERG, etc.)...")
                start = dt.date.today() - dt.timedelta(days=500)
                for t in extra:
                    try:
                        d, _ = get_ohlcv(t, start, dt.date.today())
                        if d is not None and "Close" in d.columns and len(d) > 200:
                            closes[t] = d["Close"].dropna()
                    except Exception:
                        pass
                    time.sleep(0.15)
            return closes
        print("  (S&P 500 insuficiente; uso la lista por sectores)")
    tickers = sorted({t for lst in SECTOR_STOCKS.values() for t in lst})
    start = dt.date.today() - dt.timedelta(days=500)
    closes = {}
    print(f"\nDescargando {len(tickers)} acciones para el ranking de lideres...")
    for i, t in enumerate(tickers):
        d, _ = get_ohlcv(t, start, dt.date.today())
        if d is not None and "Close" in d.columns and len(d) > 200:
            closes[t] = d["Close"].dropna()
        if (i + 1) % 20 == 0:
            print(f"  ...{i + 1}/{len(tickers)}")
        time.sleep(0.15)
    print(f"  acciones con datos: {len(closes)}")
    return closes

def sp500_tickers():
    for url in ("https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv",
                "https://datahub.io/core/s-and-p-500-companies/r/constituents.csv"):
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            df = pd.read_csv(StringIO(r.text))
            col = "Symbol" if "Symbol" in df.columns else df.columns[0]
            ts = [str(t).strip().upper().replace(".", "-") for t in df[col].dropna()]
            ts = list(dict.fromkeys(ts))
            if len(ts) > 400:
                print(f"  lista S&P 500 obtenida: {len(ts)} valores")
                return ts
        except Exception:
            continue
    print(f"  (no pude bajar la lista del S&P; uso respaldo de {len(set(SP500_FALLBACK))})")
    return list(dict.fromkeys(SP500_FALLBACK))

def _yf_batch_closes(tickers):
    closes = {}
    if yf is None:
        return closes
    for i in range(0, len(tickers), 80):
        chunk = tickers[i:i + 80]
        try:
            data = yf.download(chunk, period="2y", interval="1d", progress=False,
                               auto_adjust=True, threads=True)
            if data is None or len(data) == 0:
                continue
            if isinstance(data.columns, pd.MultiIndex):
                cl = data["Close"]
            else:
                cl = data[["Close"]].rename(columns={"Close": chunk[0]})
            for t in cl.columns:
                s = cl[t].dropna()
                if len(s) > 200:
                    closes[str(t)] = s
        except Exception:
            continue
        time.sleep(0.4)
    return closes

def fetch_sp500_universe():
    tickers = sp500_tickers()
    print(f"\nDescargando el S&P 500 ({len(tickers)} acciones) para el RS...")
    closes = _yf_batch_closes(tickers)
    print(f"  via yfinance: {len(closes)}")
    # completar lo que falte por la via fiable (Stooq/Yahoo individual)
    missing = [t for t in tickers if t not in closes]
    if missing:
        print(f"  completando {len(missing)} por descarga individual (tarda un poco)...")
        start = dt.date.today() - dt.timedelta(days=500)
        for i, t in enumerate(missing):
            d, _ = get_ohlcv(t, start, dt.date.today())
            if d is not None and "Close" in d.columns and len(d) > 200:
                closes[t] = d["Close"].dropna()
            time.sleep(0.12)
            if (i + 1) % 50 == 0:
                print(f"    ...{i + 1}/{len(missing)}")
    print(f"  acciones del S&P con datos: {len(closes)}")
    return closes

def _phase(s, drs):
    """Clasifica la FASE de una accion (modelo de 4 fases) con su propia serie de precios.
    base = lateral abajo acumulando · sube = tendencia alcista sana · distrib = lateral arriba (techo) ·
    baja = bajando · lateral = medio sin sesgo. Usa media 30 semanas + posicion en rango 52s + aceleracion RS."""
    try:
        s = s.dropna()
    except Exception:
        return None
    if s is None or len(s) < 170:
        return None
    price = float(s.iloc[-1])
    win = s.iloc[-252:]
    hi = price / (float(win.max()) or 1e-9) * 100
    lo = float(win.min())
    pos = (price - lo) / (((float(win.max()) - lo)) or 1e-9) * 100
    ma = s.rolling(150).mean()                 # media 30 semanas (~150 sesiones)
    if pd.isna(ma.iloc[-1]):
        ma = s.rolling(50).mean()
    ma_now = float(ma.iloc[-1])
    j = -21 if len(ma.dropna()) > 21 else 0
    ma_past = float(ma.dropna().iloc[j]) if len(ma.dropna()) else ma_now
    ma_slope = (ma_now / ma_past - 1) if ma_past else 0.0
    above = price > ma_now
    d = drs or 0
    if (not above) and ma_slope < -0.002:
        return "baja"
    if above and ma_slope > 0.002:
        if hi >= 88 and d <= 0:                 # arriba pero el impulso ya no acompaña = techo
            return "distrib"
        return "sube"
    if hi >= 85:                                # plana pegada a maximos = distribucion
        return "distrib"
    if pos <= 50:                               # plana en la parte baja = acumulacion
        return "base"
    return "lateral"


# fase -> (emoji, etiqueta, color)
PHASE_INFO = {
    "base":    ("🟦", "base/acumulación", "#5AA9E6"),
    "sube":    ("🟢", "subiendo",         "#2FD08A"),
    "distrib": ("🟠", "distribución",     "#F4B740"),
    "baja":    ("🔴", "cayendo",          "#F4607A"),
    "lateral": ("⚪", "lateral",          "#9FB0C8"),
}


def compute_rs_leaders(stock_close):
    OFF = 65   # ~3 meses (dias de bolsa) para medir la aceleracion del percentil
    def score_at(s, off):
        end = len(s) - 1 - off
        if end < 252:
            return None
        f = lambda k: float(s.iloc[end] / s.iloc[end - k] - 1)
        return 2 * f(63) + f(126) + f(189) + f(252)
    perf, perf_then, hi52 = {}, {}, {}
    for sym, s in stock_close.items():
        s = s.dropna()
        if len(s) < 260:
            continue
        sc = score_at(s, 0)
        if sc is None:
            continue
        perf[sym] = sc
        hi52[sym] = round(float(s.iloc[-1] / s.iloc[-252:].max()) * 100)
        st = score_at(s, OFF)
        if st is not None:
            perf_then[sym] = st
    if len(perf) < 5:
        return None, 0
    order = sorted(perf.items(), key=lambda kv: kv[1])
    n = len(order)
    rs = {sym: int(round(1 + 98 * i / (n - 1))) for i, (sym, _) in enumerate(order)}
    # percentil de hace 3 meses (mismo metodo) para la aceleracion
    rs_then = {}
    if len(perf_then) >= 5:
        ot = sorted(perf_then.items(), key=lambda kv: kv[1])
        nt = len(ot)
        rs_then = {sym: int(round(1 + 98 * i / (nt - 1))) for i, (sym, _) in enumerate(ot)}
    out = {}
    for sec, stocks in SECTOR_STOCKS.items():
        rows = []
        for st in stocks:
            if st in rs:
                drs = (rs[st] - rs_then[st]) if st in rs_then else None
                rows.append({"sym": st, "rs": rs[st], "hi": hi52.get(st, 0), "drs": drs,
                             "phase": _phase(stock_close.get(st), drs)})
        rows.sort(key=lambda x: -x["rs"])
        if rows:
            out[sec] = rows
    # amplitud REAL del sector: % de sus acciones por encima de su media de 50 sesiones (detecta falso liderazgo)
    breadth = {}
    for sec, stocks in SECTOR_STOCKS.items():
        above = tot = 0
        for st in stocks:
            s = stock_close.get(st)
            if s is None:
                continue
            s = s.dropna()
            if len(s) < 55:
                continue
            tot += 1
            if float(s.iloc[-1]) > float(s.iloc[-50:].mean()):
                above += 1
        if tot >= 3:
            breadth[sec] = {"pct": round(100 * above / tot), "n": tot}
    return out, n, breadth


# ----------------------------------------------------------------------
def pct_change(df, sym, weeks=13):
    if sym not in df.columns or len(df) <= weeks:
        return None
    return float(df[sym].iloc[-1] / df[sym].iloc[-1 - weeks] - 1) * 100

def detect_regime(df, rrg, risk, fred_sig=None):
    sig = {
        "Bonos (TLT)": pct_change(df, "TLT"),
        "Credito HY (HYG)": pct_change(df, "HYG"),
        "Oro (GLD)": pct_change(df, "GLD"),
        "Dolar (UUP)": pct_change(df, "UUP"),
        "Apetito riesgo": risk["score"],
    }
    tlt = sig["Bonos (TLT)"] or 0          # <0 => tipos al alza
    hyg = sig["Credito HY (HYG)"] or 0
    gld = sig["Oro (GLD)"] or 0
    uup = sig["Dolar (UUP)"] or 0
    rk = risk["score"]
    scores = {
        "reflacion":   (tlt < -1) * 2 + (rk > 1) * 2 + (hyg > 0) * 1 + (uup < 1) * 1,
        "goldilocks":  (rk > 1) * 2 + (gld < 2) * 1 + (hyg > 0) * 1 + (-2 < tlt < 2) * 1,
        "riskoff":     (rk < -1) * 2 + (hyg < -1) * 2 + (gld > 1) * 1 + (tlt > 1) * 1 + (uup > 1) * 1,
        "estanflacion":(gld > 3) * 2 + (tlt < -1) * 1 + (rk < 0) * 1,
        "pivote":      (tlt > 2) * 2 + (uup < -1) * 1 + (rrg.get("XLK", {}).get("quad") in ("leading", "improving")) * 1,
    }
    # señales macro reales de FRED (si hay key): tienen mas peso que las de mercado
    if fred_sig:
        curve = fred_sig.get("curve_chg", 0) or 0     # pendiente 2s10s, +=empinando
        y10 = fred_sig.get("dgs10_chg", 0) or 0       # tipo 10A, +=al alza
        hyo = fred_sig.get("hy_chg", 0) or 0          # diferencial HY, +=stress de credito
        scores["reflacion"] += (y10 > 0) * 2 + (curve > 0) * 1
        scores["riskoff"] += (hyo > 0.2) * 3 + (curve < 0) * 1
        scores["pivote"] += (y10 < 0) * 2 + (curve > 0.1) * 1
        scores["estanflacion"] += (y10 < 0 and gld > 2) * 1
    best = max(scores, key=scores.get)
    labels = {
        "reflacion": "Reflacion / tipos al alza",
        "goldilocks": "Goldilocks / desinflacion",
        "riskoff": "Risk-off / desaceleracion",
        "estanflacion": "Estanflacion / shock de oferta",
        "pivote": "Pivote dovish / recortes Fed",
    }
    favor = {
        "reflacion": ["XLF","XLE","XLI","XLB","IWM"], "goldilocks": ["XLK","XLY","XLC","IWM"],
        "riskoff": ["XLP","XLU","XLV","GLD","TLT"], "estanflacion": ["XLE","XLB","GLD"],
        "pivote": ["XLRE","XLU","XLK","GLD","IWM"],
    }
    hurt = {
        "reflacion": ["XLU","XLRE","TLT","XLK"], "goldilocks": ["XLP","XLU","GLD"],
        "riskoff": ["XLY","XLK","IWM","HYG","XLE"], "estanflacion": ["XLY","XLK","TLT","XLF"],
        "pivote": ["XLF"],
    }
    sig = {k: (round(v, 1) if v is not None else None) for k, v in sig.items()}
    return {"id": best, "label": labels[best], "favor": favor[best], "hurt": hurt[best], "sig": sig}

def conviction(rrg, regime):
    buy, avoid = [], []
    for s, d in rrg.items():
        if d["quad"] in ("improving", "leading") and s in regime["favor"]:
            buy.append(s)
        if d["quad"] in ("weakening", "lagging") and s in regime["hurt"]:
            avoid.append(s)
    return buy, avoid

# ----------------------------------------------------------------------
# FRED opcional (macro real) + avisos automaticos
# ----------------------------------------------------------------------
def _fred_key():
    """Resuelve la key de FRED: variable de entorno (Secret de GitHub / entorno del PC) ->
    archivo local 'clave_fred*' junto al script o en la carpeta actual (NO se sube; esta en .gitignore)
    -> constante FRED_API_KEY. Tolerante con Windows: acepta clave_fred.txt.txt, BOM y comillas."""
    k = os.environ.get("FRED_API_KEY", "") or FRED_API_KEY
    if k:
        return k.strip()
    import glob
    try:
        here = os.path.dirname(os.path.abspath(__file__))
    except Exception:
        here = os.getcwd()
    seen = []
    for d in (here, os.getcwd()):
        if d and d not in seen:
            seen.append(d)
    for d in seen:
        try:
            for p in sorted(glob.glob(os.path.join(d, "clave_fred*"))):
                try:
                    with open(p, "r", encoding="utf-8-sig") as f:   # utf-8-sig quita el BOM de Notepad
                        v = f.read().strip().strip('"').strip("'").strip()
                    if v:
                        return v
                except Exception:
                    continue
        except Exception:
            continue
    return ""

def fetch_fred():
    """Devuelve (panel_para_mostrar, señales_para_el_regimen) o (None, None)."""
    key = _fred_key()
    if not key:
        return None, None
    series = {"DGS10": "Tipo 10A (%)", "T10Y2Y": "Pendiente 2s10s",
              "BAMLH0A0HYM2": "Diferencial HY (OAS)", "DFII10": "Tipo real 10A (%)"}
    out = {}
    raw = {}
    for sid, lab in series.items():
        try:
            url = ("https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={sid}&api_key={key}&file_type=json"
                   "&sort_order=desc&limit=70")
            r = requests.get(url, timeout=15).json()
            obs = [o for o in r.get("observations", []) if o["value"] not in (".", "")]
            if not obs:
                continue
            last = float(obs[0]["value"])
            prev = float(obs[min(13, len(obs) - 1)]["value"])
            out[lab] = {"last": round(last, 2), "chg": round(last - prev, 2)}
            raw[sid] = {"last": last, "chg": last - prev}
        except Exception:
            continue
    if not out:
        return None, None
    sig = {
        "dgs10_chg": raw.get("DGS10", {}).get("chg", 0),
        "curve_chg": raw.get("T10Y2Y", {}).get("chg", 0),
        "hy_chg": raw.get("BAMLH0A0HYM2", {}).get("chg", 0),
        "hy_last": raw.get("BAMLH0A0HYM2", {}).get("last", 0),
    }
    return out, sig

def fetch_macro():
    """Descarga macro de FRED (empleo, inflacion, PCE, blandos) y calcula nivel + direccion.
    Defensivo: sin key o si falla una serie, la salta. Devuelve dict {sid: {...}} o None."""
    key = _fred_key()
    if not key:
        return None
    def _obs(sid, limit=90):
        try:
            url = ("https://api.stlouisfed.org/fred/series/observations"
                   f"?series_id={sid}&api_key={key}&file_type=json&sort_order=desc&limit={limit}")
            r = requests.get(url, timeout=15).json()
            return [float(o["value"]) for o in r.get("observations", []) if o["value"] not in (".", "")]
        except Exception:
            return []
    def _yoy(v, per=12):
        return (v[0] / v[per] - 1.0) * 100 if len(v) > per and v[per] else None
    m = {}
    # INFLACION (indices -> YoY y direccion del YoY a 6 meses)
    for sid, lab in (("PCEPILFE", "PCE subyacente"), ("CPILFESL", "IPC subyacente")):
        v = _obs(sid)
        yoy = _yoy(v)
        yoy6 = _yoy(v[6:]) if len(v) > 18 else None
        if yoy is not None:
            m[sid] = {"lab": lab, "val": round(yoy, 2), "unit": "% i.a.",
                      "dir": round(yoy - yoy6, 2) if yoy6 is not None else 0.0, "kind": "hard", "goodup": False}
    # EMPLEO
    pay = _obs("PAYEMS")
    if len(pay) > 4:
        chg3 = (pay[0] - pay[3]) / 3.0
        m["PAYEMS"] = {"lab": "Nóminas (prom. 3m)", "val": round(chg3, 0), "unit": "k/mes",
                       "dir": round((pay[0] - pay[1]) - (pay[3] - pay[4]), 0), "kind": "hard", "goodup": True}
    un = _obs("UNRATE")
    if len(un) > 3:
        m["UNRATE"] = {"lab": "Paro", "val": round(un[0], 2), "unit": "%",
                       "dir": round(un[0] - un[3], 2), "kind": "hard", "goodup": False}
    cl = _obs("ICSA", limit=60)
    if len(cl) > 8:
        m4, p4 = sum(cl[0:4]) / 4.0, sum(cl[4:8]) / 4.0
        m["ICSA"] = {"lab": "Paro semanal (4s)", "val": round(m4 / 1000, 0), "unit": "k",
                     "dir": round((m4 - p4) / 1000, 1), "kind": "soft", "goodup": False}
    # CRECIMIENTO
    ip = _obs("INDPRO")
    yoy_ip = _yoy(ip)
    if yoy_ip is not None:
        yoy_ip6 = _yoy(ip[6:]) if len(ip) > 18 else None
        m["INDPRO"] = {"lab": "Prod. industrial", "val": round(yoy_ip, 2), "unit": "% i.a.",
                       "dir": round(yoy_ip - yoy_ip6, 2) if yoy_ip6 is not None else 0.0, "kind": "hard", "goodup": True}
    # BLANDOS (lideres)
    um = _obs("UMCSENT")
    if len(um) > 3:
        m["UMCSENT"] = {"lab": "Confianza consumidor", "val": round(um[0], 1), "unit": "",
                        "dir": round(um[0] - um[3], 1), "kind": "soft", "goodup": True}
    cu = _obs("T10Y2Y", limit=70)
    if len(cu) > 13:
        m["T10Y2Y"] = {"lab": "Curva 2s10s", "val": round(cu[0], 2), "unit": "pp",
                       "dir": round(cu[0] - cu[13], 2), "kind": "soft", "goodup": True}
    hy = _obs("BAMLH0A0HYM2", limit=70)
    if len(hy) > 13:
        m["HY"] = {"lab": "Spread HY (riesgo)", "val": round(hy[0], 2), "unit": "pp",
                   "dir": round(hy[0] - hy[13], 2), "kind": "soft", "goodup": False}
    return m or None

def compute_macro_regime(m, ism):
    """Reloj de inversion: cruza direccion de CRECIMIENTO x direccion de INFLACION -> cuadrante + playbook.
    Las probabilidades son GRUESAS (base-rate del regimen), nunca una prediccion."""
    if not m:
        return None
    # eje INFLACION
    infl_dir, n = 0.0, 0
    for sid in ("PCEPILFE", "CPILFESL"):
        if sid in m:
            infl_dir += m[sid]["dir"]; n += 1
    infl_dir = infl_dir / n if n else 0.0
    # banda muerta mas ancha (±0.20pp): solo "subiendo/bajando" si la senal es CLARA; evita que el regimen
    # baile entre sobrecalentamiento y goldilocks por rozar la frontera con cada dato/revision de FRED.
    infl_up = infl_dir > 0.20
    infl_down = infl_dir < -0.20
    infl_weak = not infl_up and not infl_down          # senal de inflacion ambigua / en transicion
    infl_lbl = "subiendo" if infl_up else ("bajando" if infl_down else "plana (en transición)")
    # eje CRECIMIENTO (compuesto blandos + hard; ISM pesa doble)
    g, gmax = 0, 0
    if ism is not None:
        gmax += 2; g += (2 if ism >= 53 else (1 if ism >= 50 else (-1 if ism >= 47 else -2)))
    if "INDPRO" in m:
        gmax += 1; g += (1 if (m["INDPRO"]["val"] > 0 and m["INDPRO"]["dir"] >= 0) else (-1 if (m["INDPRO"]["val"] < 0 or m["INDPRO"]["dir"] < -0.2) else 0))
    if "ICSA" in m:
        gmax += 1; g += (1 if m["ICSA"]["dir"] < 0 else (-1 if m["ICSA"]["dir"] > 5 else 0))
    if "UMCSENT" in m:
        gmax += 1; g += (1 if m["UMCSENT"]["dir"] > 0 else (-1 if m["UMCSENT"]["dir"] < -2 else 0))
    if "PAYEMS" in m:
        gmax += 1; g += (1 if m["PAYEMS"]["val"] > 100 else (-1 if m["PAYEMS"]["val"] < 50 else 0))
    if "T10Y2Y" in m:
        gmax += 1; g += (1 if m["T10Y2Y"]["dir"] > 0.05 else 0)
    grow_up = g > 0
    grow_lbl = "acelerando" if g > 0 else ("desacelerando" if g < 0 else "estable")
    # cuadrante del reloj de inversion
    if grow_up and not infl_up:
        quad, label = "recuperacion", "Recuperación / reflación temprana"
        favor, hurt = ["XLK", "XLY", "XLF", "IWM", "XLC", "SMH"], ["XLP", "XLU", "TLT", "GLD"]
    elif grow_up and infl_up:
        quad, label = "sobrecalentamiento", "Sobrecalentamiento"
        favor, hurt = ["XLE", "XLB", "XLF", "COPX", "GLD"], ["TLT", "XLK", "XLY"]
    elif (not grow_up) and infl_up:
        quad, label = "estanflacion", "Estanflación / shock de oferta"
        favor, hurt = ["XLE", "GLD", "XLP", "XLU", "GDX"], ["XLY", "IWM", "XLK", "SMH"]
    else:
        quad, label = "desinflacion", "Desinflación / desaceleración"
        favor, hurt = ["TLT", "XLU", "XLP", "XLV", "GLD"], ["XLE", "XLB", "IWM", "XLF"]
    # probabilidades GRUESAS (transparentes): cuanto mas clara la senal, mas peso al caso base
    conf = abs(g) / max(gmax, 1)
    base = 0.45 + 0.20 * conf
    rest = 1 - base
    bull, bear = (rest * 0.6, rest * 0.4) if g >= 0 else (rest * 0.4, rest * 0.6)
    pr = {"base": round(base * 100), "bull": round(bull * 100), "bear": round(bear * 100)}
    return {"quad": quad, "label": label, "favor": favor, "hurt": hurt,
            "grow_lbl": grow_lbl, "infl_lbl": infl_lbl, "grow_up": grow_up, "infl_up": infl_up,
            "g": g, "gmax": gmax, "conf": conf, "pr": pr, "infl_weak": infl_weak}

def notify(text):
    """Envia el resumen a Telegram y/o a un webhook (Discord/Slack). Devuelve True si envio algo."""
    sent = False
    tok = os.environ.get("TELEGRAM_TOKEN") or TELEGRAM_TOKEN
    chat = os.environ.get("TELEGRAM_CHAT_ID") or TELEGRAM_CHAT_ID
    if tok and chat:
        try:
            requests.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                          data={"chat_id": chat, "text": text}, timeout=15)
            sent = True
        except Exception:
            pass
    hook = os.environ.get("WEBHOOK_URL") or WEBHOOK_URL
    if hook:
        try:
            requests.post(hook, json={"content": text, "text": text}, timeout=15)
            sent = True
        except Exception:
            pass
    return sent

# ----------------------------------------------------------------------
# Analisis con IA (opcional)
# ----------------------------------------------------------------------
def state_summary(rrg, risk, regime, breadth, plan, flow):
    by_q = {"leading": [], "weakening": [], "improving": [], "lagging": []}
    for s, d in rrg.items():
        by_q[d["quad"]].append(s)
    divs = [f"{s} ({d['diverg']})" for s, d in (flow or {}).items() if d.get("diverg")]
    lines = [
        f"Regimen macro: {regime['label']}. Apetito de riesgo: {risk['label']} ({risk['score']:+}).",
        f"Amplitud: {breadth['leaders']}% con fuerza>indice, {breadth['uptrend']}% en tendencia.",
        f"LIDER: {', '.join(by_q['leading']) or '-'}.",
        f"DEBILITANDOSE: {', '.join(by_q['weakening']) or '-'}.",
        f"MEJORANDO: {', '.join(by_q['improving']) or '-'}.",
        f"REZAGADO: {', '.join(by_q['lagging']) or '-'}.",
    ]
    if divs:
        lines.append(f"Divergencias de flujo: {', '.join(divs)}.")
    if plan:
        lines.append(f"Caida actual del S&P desde maximos: {plan['dd']}%.")
    return "\n".join(lines)

def _cargar_key(constante, var_entorno, archivo):
    """Busca la key en 3 sitios: constante del codigo, variable de entorno, y un ARCHIVO de texto
    junto al script (la via sin tocar codigo). Si esta en un repo git, se auto-anade a .gitignore."""
    if constante:
        return constante.strip()
    v = os.environ.get(var_entorno, "").strip()
    if v:
        return v
    try:
        base = os.path.dirname(os.path.abspath(__file__))
        ruta = os.path.join(base, archivo)
        if os.path.exists(ruta):
            with open(ruta, "r", encoding="utf-8") as fh:
                lineas = [l.strip() for l in fh.read().splitlines() if l.strip()]
            k = lineas[0] if lineas else ""
            if k:
                if os.path.isdir(os.path.join(base, ".git")):
                    gi = os.path.join(base, ".gitignore")
                    try:
                        cont = open(gi, "r", encoding="utf-8").read() if os.path.exists(gi) else ""
                        if archivo not in cont:
                            with open(gi, "a", encoding="utf-8") as fh:
                                fh.write(("" if (not cont or cont.endswith(chr(10))) else chr(10)) + archivo + chr(10))
                            print("  (proteccion) " + archivo + " anadido a .gitignore")
                    except Exception:
                        print("  AVISO: no subas " + archivo + " al repositorio")
                return k
    except Exception:
        pass
    return ""


def run_ia_auto(snap, fecha):
    """EJECUTA los prompts automaticos contra la API de Anthropic al construir el terminal.
    Devuelve {key: {"title","text","ok","modelo"}} o None si no hay API key. El maestro siempre
    (si IA_AUTO); los de IA_AUTO_EXTRA, ademas. Con IA_WEB_SEARCH la IA puede buscar 13F, VIX,
    earnings... (coste extra por busqueda). Errores legibles, nunca rompe el build."""
    if not IA_AUTO:
        return None
    if IA_PROVIDER == "openai_compat":
        key = _cargar_key(IA_COMPAT_KEY, "IA_COMPAT_KEY", "ia_key.txt")
    else:
        key = _cargar_key(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY", "anthropic_key.txt")
    if not key:
        print("  IA automatica: SIN key (crea ia_key.txt junto al script para activarla)")
        return None
    print("  IA automatica: key encontrada, consultando al proveedor ...")
    quiero = ["gestor"] + [k for k in (IA_AUTO_EXTRA or []) if k != "gestor"]
    pmap = {k: (t, p) for k, t, p in IA_PROMPTS}
    out = {}
    for k in quiero:
        if k not in pmap:
            continue
        title, prompt = pmap[k]
        _prompt_full = prompt + ia_data_block(snap, fecha)
        if IA_PROVIDER == "openai_compat":
            _modelo = IA_COMPAT_MODEL
            print(f"  IA automatica ({_modelo} via proveedor compatible): ejecutando '{k}' ...")
            try:
                r = requests.post(IA_COMPAT_BASE.rstrip("/") + "/chat/completions",
                                  headers={"Authorization": "Bearer " + key, "content-type": "application/json"},
                                  json={"model": _modelo, "max_tokens": int(IA_MAX_TOKENS),
                                        "messages": [{"role": "user", "content": _prompt_full}]},
                                  timeout=180)
                j = r.json()
                if r.status_code != 200:
                    err = (j.get("error") or {}).get("message", f"HTTP {r.status_code}")
                    out[k] = {"title": title, "text": "La API devolvió un error: " + str(err), "ok": False, "modelo": _modelo}
                    continue
                txt = ((j.get("choices") or [{}])[0].get("message") or {}).get("content", "").strip()
                _nota = chr(10) + chr(10) + "(Proveedor compatible sin búsqueda web: las referencias externas salen del conocimiento del modelo, no de fuentes en vivo.)" if txt else ""
                out[k] = {"title": title, "text": (txt + _nota) or "(respuesta vacía)", "ok": bool(txt), "modelo": _modelo}
            except Exception as e:
                out[k] = {"title": title, "text": "No se pudo conectar con el proveedor compatible: " + type(e).__name__ +
                          ". Revisa internet, la URL base y la key.", "ok": False, "modelo": _modelo}
            continue
        print(f"  IA automatica: ejecutando '{k}' ({IA_AUTO_MODEL}" + (", con busqueda web" if IA_WEB_SEARCH else "") + ") ...")
        body = {"model": IA_AUTO_MODEL, "max_tokens": int(IA_MAX_TOKENS),
                "messages": [{"role": "user", "content": _prompt_full}]}
        if IA_WEB_SEARCH:
            body["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}]
        try:
            r = requests.post("https://api.anthropic.com/v1/messages",
                              headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                       "content-type": "application/json"},
                              json=body, timeout=180)
            j = r.json()
            if r.status_code != 200:
                err = (j.get("error") or {}).get("message", f"HTTP {r.status_code}")
                out[k] = {"title": title, "text": f"La API devolvió un error: {err}", "ok": False, "modelo": IA_AUTO_MODEL}
                continue
            txt = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text").strip()
            out[k] = {"title": title, "text": txt or "(respuesta vacía)", "ok": bool(txt), "modelo": IA_AUTO_MODEL}
        except Exception as e:
            out[k] = {"title": title, "text": f"No se pudo conectar con la API: {type(e).__name__}. "
                      "Revisa internet y la key; el resto del terminal no se ve afectado.", "ok": False, "modelo": IA_AUTO_MODEL}
    return out or None


def ai_commentary(summary):
    key = _cargar_key(ANTHROPIC_API_KEY, "ANTHROPIC_API_KEY", "anthropic_key.txt")
    if not key:
        return None
    prompt = ("Eres analista de rotacion sectorial. Con estos datos de cierre (no en tiempo real), "
              "escribe un analisis breve en espanol (maximo 150 palabras): que esta rotando, que vigilar "
              "para entrar o proteger, y como encaja con la macro. Se concreto y prudente; no es asesoramiento.\n\n"
              + summary)
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
                          headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                   "content-type": "application/json"},
                          json={"model": AI_MODEL, "max_tokens": 500,
                                "messages": [{"role": "user", "content": prompt}]},
                          timeout=40)
        j = r.json()
        txt = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        return txt.strip() or None
    except Exception:
        return None

# ----------------------------------------------------------------------
# Render del panel HTML (SVG + tablas, sin JS)
# ----------------------------------------------------------------------
CSS = """
*{box-sizing:border-box;margin:0;padding:0}
body{--bg:#0A0E17;--bg2:#0F1521;--bg3:#131B2A;--line:#1E2A3D;--line2:#2A3A52;
--txt:#E6EDF6;--txt2:#93A4BC;--txt3:#5E708A;--accent:#5B8CFF;
background:var(--bg);color:var(--txt);font-family:ui-sans-serif,system-ui,'Segoe UI',Roboto,sans-serif;
line-height:1.45;-webkit-font-smoothing:antialiased;padding-bottom:40px}
.mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-variant-numeric:tabular-nums}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;flex-wrap:wrap;
padding:14px 22px;border-bottom:1px solid var(--line);background:var(--bg2)}
.brand{display:flex;align-items:center;gap:11px}
.title{font-size:17px;font-weight:800;letter-spacing:4px}
.sub{font-size:10.5px;letter-spacing:2px;text-transform:uppercase;color:var(--txt3)}
.status{display:flex;gap:14px;flex-wrap:wrap;align-items:center;font-family:ui-monospace,monospace;font-size:11px;color:var(--txt2)}
.status b{color:var(--txt3);font-weight:500;font-size:9.5px;letter-spacing:1px;text-transform:uppercase;margin-right:5px}
.pill{font-size:10px;font-weight:700;letter-spacing:1px;padding:3px 9px;border-radius:4px;font-family:ui-monospace,monospace}
.RiskON{background:rgba(47,208,138,.14);color:#2FD08A}.RiskOFF{background:rgba(244,96,122,.14);color:#F4607A}
.Neutral{background:rgba(147,164,188,.12);color:var(--txt2)}
main{max-width:1280px;margin:0 auto;padding:16px;display:grid;grid-template-columns:1.55fr 1fr;gap:14px}
@media(max-width:900px){main{grid-template-columns:1fr}}
.panel{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:14px 15px;margin-bottom:14px}
.panel h2{font-size:12.5px;font-weight:600;margin-bottom:10px}
.note{font-size:11.5px;color:var(--txt2);margin:6px 0 10px}
svg{width:100%;height:auto;display:block;background:var(--bg);border-radius:8px}
.legend{display:flex;gap:14px;flex-wrap:wrap;margin-top:10px;font-size:11px;color:var(--txt2)}
.legend i{width:9px;height:9px;border-radius:2px;display:inline-block;margin-right:5px}
.alerts{display:flex;flex-direction:column;gap:7px}
.alert{display:flex;gap:9px;background:var(--bg3);border:1px solid var(--line);border-left-width:3px;border-radius:7px;padding:8px 10px}
.a-warn{border-left-color:#F4B740}.a-in{border-left-color:#4CC2E0}.a-lead{border-left-color:#2FD08A}.a-down{border-left-color:#F4607A}
.atk{font-family:ui-monospace,monospace;font-weight:700;font-size:12px;min-width:42px}
.atx{font-size:11.5px;color:var(--txt2)}
table{width:100%;border-collapse:collapse;font-size:12px}
th{font-size:10px;text-transform:uppercase;letter-spacing:.6px;color:var(--txt3);text-align:left;padding:6px}
td{padding:7px 6px;border-top:1px solid var(--line);color:var(--txt2)}
td.r{text-align:right;font-family:ui-monospace,monospace}
.tk b{color:var(--txt);font-family:ui-monospace,monospace}.tk em{color:var(--txt3);font-style:normal;font-size:10px;display:block}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;margin-right:5px}
.bar-row{display:grid;grid-template-columns:46px 1fr 44px;align-items:center;gap:9px;margin-bottom:6px}
.bar-lab{font-family:ui-monospace,monospace;font-size:12px;color:var(--txt)}
.bar-track{position:relative;height:16px;background:var(--bg3);border-radius:4px}
.bar-mid{position:absolute;left:50%;top:0;bottom:0;width:1px;background:var(--line2)}
.bar{position:absolute;top:2px;bottom:2px;border-radius:3px}
.bar-val{text-align:right;font-family:ui-monospace,monospace;font-size:11.5px}
.meter{margin-bottom:12px}.meter-top{display:flex;justify-content:space-between;font-size:11.5px;color:var(--txt2);margin-bottom:5px}
.meter-top b{font-family:ui-monospace,monospace}.meter-track{height:7px;background:var(--bg3);border-radius:4px;overflow:hidden}
.meter-fill{height:100%;border-radius:4px}
.bigrisk{font-size:22px;font-weight:800;letter-spacing:2px;text-align:center;padding:12px 0 6px;font-family:ui-monospace,monospace}
.tags{display:flex;flex-wrap:wrap;gap:5px;margin-top:5px}
.tag{font-family:ui-monospace,monospace;font-size:11px;padding:2px 7px;border-radius:4px;font-weight:600}
.tag.good{background:rgba(47,208,138,.12);color:#2FD08A}.tag.bad{background:rgba(244,96,122,.12);color:#F4607A}
.conv{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:10px}
@media(max-width:560px){.conv{grid-template-columns:1fr}}
.conv-box{border:1px solid var(--line);border-radius:8px;padding:11px;background:var(--bg3)}
.conv-box h3{font-size:11.5px;margin-bottom:5px}
.kv{display:flex;justify-content:space-between;font-size:12px;padding:5px 0;border-bottom:1px solid var(--line)}
.kv span{color:var(--txt3)}.kv b{color:var(--txt);font-family:ui-monospace,monospace;font-weight:500}
.full{grid-column:1/-1}
.summary{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:2px}
@media(max-width:700px){.summary{grid-template-columns:1fr 1fr}}
.scard{background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:11px 13px}
.scard .lab{font-size:9px;text-transform:uppercase;letter-spacing:1px;color:var(--txt3);margin-bottom:6px}
.scard .big{font-size:17px;font-weight:800;font-family:ui-monospace,monospace;line-height:1.1}
.scard .sm{font-size:10.5px;color:var(--txt2);margin-top:4px}
td.spk{width:84px;padding-right:10px}
td.spk svg{display:block;opacity:.9}
td.ts2{font-size:10.5px;color:var(--txt3);white-space:nowrap}
.planwrap{display:grid;grid-template-columns:1.1fr 1fr;gap:16px}
@media(max-width:760px){.planwrap{grid-template-columns:1fr}}
.dd-now{background:var(--bg3);border:1px solid var(--line);border-radius:9px;padding:11px 13px;margin-bottom:10px}
.dd-now .lab{font-size:9.5px;text-transform:uppercase;letter-spacing:1px;color:var(--txt3)}
.dd-big{font-size:30px;font-weight:800;font-family:ui-monospace,monospace;line-height:1.1;margin:2px 0}
.dd-now .sm{font-size:11px;color:var(--txt2);font-family:ui-monospace,monospace}
.rung{display:grid;grid-template-columns:54px 1fr auto auto auto;gap:10px;align-items:center;
background:var(--bg3);border:1px solid var(--line);border-left:3px solid var(--line);border-radius:8px;padding:9px 11px;margin-bottom:7px}
.rk-thr{font-family:ui-monospace,monospace;font-weight:800;font-size:15px;color:var(--txt)}
.rk-lvl{font-family:ui-monospace,monospace;font-size:11.5px;color:var(--txt2)}
.rk-pct{font-size:11.5px;color:#5B8CFF;font-weight:600}
.rk-veh{font-family:ui-monospace,monospace;font-size:11px;color:#F4B740;background:rgba(244,183,64,.12);padding:1px 6px;border-radius:4px}
.rk-st{font-size:10.5px;font-family:ui-monospace,monospace;text-align:right}
@media(max-width:520px){.rung{grid-template-columns:46px 1fr auto;row-gap:4px}.rk-veh,.rk-st{grid-column:2/4}}
.planstats table{width:100%}
.planstats th{vertical-align:bottom;line-height:1.15}
.veh3{font-family:ui-monospace,monospace;font-size:10.5px;color:#F4B740;background:rgba(244,183,64,.12);padding:1px 6px;border-radius:4px}
svg circle{cursor:help}
td.tk{cursor:help}
.veh3.off{color:#5E708A;background:none}
.qgrid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
@media(max-width:560px){.qgrid{grid-template-columns:1fr}}
.qcell{background:var(--bg3);border:1px solid var(--line);border-radius:9px;padding:10px 11px;min-height:84px}
.qhead{font-family:ui-monospace,monospace;font-size:11px;font-weight:700;letter-spacing:1px;margin-bottom:8px}
.qhead span{color:var(--txt3);font-weight:400;letter-spacing:0;text-transform:none}
.qchips{display:flex;flex-wrap:wrap;gap:6px}
.qchip{border:1px solid var(--line);border-radius:6px;padding:3px 7px;font-size:11px;background:var(--bg2);cursor:help}
.qchip b{font-family:ui-monospace,monospace}.qchip i{color:var(--txt3);font-style:normal;font-size:9.5px;font-family:ui-monospace,monospace}
.qempty{color:var(--txt3);font-size:11px}
.viewtabs{display:flex;gap:6px;margin-bottom:10px}
.viewtab{font-size:11px;color:var(--txt3);background:var(--bg3);border:1px solid var(--line);border-radius:6px;padding:5px 12px;cursor:pointer}
.viewtab.active{color:#fff;background:#5B8CFF;border-color:#5B8CFF;font-weight:600}
.ai-box{background:linear-gradient(180deg,rgba(91,140,255,.07),rgba(91,140,255,0));border:1px solid rgba(91,140,255,.25);
border-radius:9px;padding:12px 14px;font-size:12.5px;color:var(--txt);line-height:1.55;white-space:pre-wrap}
.ai-btn{display:inline-flex;align-items:center;gap:7px;background:#5B8CFF;color:#fff;border:none;border-radius:8px;
padding:9px 14px;font-size:12.5px;font-weight:600;cursor:pointer;text-decoration:none}
.ai-btn.alt{background:var(--bg3);color:var(--txt2);border:1px solid var(--line)}
.hold-grid{display:grid;grid-template-columns:1fr 1fr;gap:7px}
@media(max-width:600px){.hold-grid{grid-template-columns:1fr}}
.hold{display:flex;justify-content:space-between;align-items:center;gap:8px;background:var(--bg3);border:1px solid var(--line);
border-radius:7px;padding:7px 10px;font-size:11.5px}
.hold .h-sym{font-family:ui-monospace,monospace;font-weight:700;color:var(--txt)}
.hold .h-top{color:var(--txt2);font-family:ui-monospace,monospace;font-size:11px}
.hold a{color:#5B8CFF;text-decoration:none;font-size:10.5px}
.lrow{display:grid;grid-template-columns:150px 1fr;gap:12px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line)}
@media(max-width:560px){.lrow{grid-template-columns:1fr;gap:4px}}
.lsec b{font-family:ui-monospace,monospace;color:var(--txt)}.lsec span{color:var(--txt3);font-size:10.5px}
.lchips{display:flex;flex-wrap:wrap;gap:6px}
.lchip{display:inline-flex;align-items:center;gap:5px;background:var(--bg3);border:1px solid var(--line);border-radius:7px;padding:3px 7px;font-size:11.5px}
.lchip b{font-family:ui-monospace,monospace;color:var(--txt)}
.rsbadge{font-family:ui-monospace,monospace;font-size:10px;border:1px solid;border-radius:4px;padding:0 4px}
.accel{font-family:ui-monospace,monospace;font-size:10px;color:#2FD08A;font-weight:700}
.accel.down{color:#F4607A}
.emrow{display:grid;grid-template-columns:64px 86px 60px 96px 1fr auto;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);font-size:12px}
@media(max-width:600px){.emrow{grid-template-columns:1fr 1fr;gap:4px 10px}}
.em-sym{font-family:ui-monospace,monospace;font-weight:700;color:var(--txt)}
.em-sec{font-family:ui-monospace,monospace;color:var(--txt2);font-size:11px}
.em-rs{font-family:ui-monospace,monospace;color:var(--txt2)}
.em-drs{font-family:ui-monospace,monospace;font-weight:700}
.em-hi{font-family:ui-monospace,monospace;color:var(--txt3);font-size:11px}
.emtag{justify-self:end;font-size:9.5px;color:#0A0E17;background:#2FD08A;border-radius:4px;padding:1px 7px;font-weight:700;text-transform:uppercase;letter-spacing:.5px}
.wkrow{display:grid;grid-template-columns:78px 1fr auto auto auto auto;gap:10px;align-items:center;padding:8px 0;border-bottom:1px solid var(--line);font-size:12px}
@media(max-width:620px){.wkrow{grid-template-columns:1fr 1fr;gap:4px 10px}}
.wk-sym{font-family:ui-monospace,monospace;font-weight:700;color:var(--txt)}
.wk-name{color:var(--txt2);font-size:11px}
.wk-eur{font-family:ui-monospace,monospace;font-weight:700;color:#5B8CFF}
.wk-desde{font-family:ui-monospace,monospace;font-size:11px;margin-left:8px;padding:1px 6px;border:1px solid #ffffff18;border-radius:5px}
.wk-x3{font-family:ui-monospace,monospace;font-size:10px;color:#F4B740;background:rgba(244,183,64,.12);padding:1px 6px;border-radius:4px}
.wk-stk{font-family:ui-monospace,monospace;font-size:10.5px;color:var(--txt3)}
.wk-new{justify-self:end;font-size:9.5px;color:#0A0E17;background:#4CC2E0;border-radius:4px;padding:1px 7px;font-weight:700;letter-spacing:.5px}
.wk-keep{justify-self:end;font-size:9.5px;color:var(--txt3);border:1px solid var(--line);border-radius:4px;padding:1px 7px}
.fgrid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px}
@media(max-width:680px){.fgrid{grid-template-columns:1fr}}
.fcol{background:var(--bg3);border:1px solid var(--line);border-radius:9px;padding:10px 12px}
.fhead{font-size:11px;font-weight:700;margin-bottom:8px;font-family:ui-monospace,monospace}
.fchips{display:flex;flex-wrap:wrap;gap:6px}
.fchip{display:inline-flex;align-items:center;gap:5px;border:1px solid var(--line);border-radius:6px;padding:3px 8px;font-size:11.5px;font-family:ui-monospace,monospace;font-weight:600;background:var(--bg2)}
.ring1{width:9px;height:9px;border-radius:50%;border:2px solid #2FD08A;display:inline-block;margin-right:2px}
.ring2{width:11px;height:11px;border-radius:50%;border:2px solid #F4607A;box-shadow:0 0 0 2px #F4607A;display:inline-block;margin-right:2px}
.hm{width:100%;border-collapse:separate;border-spacing:3px}
.hm-h{font-size:10px;color:var(--txt3);text-align:center;padding:4px 0;font-family:ui-monospace,monospace;text-transform:uppercase;letter-spacing:.5px;font-weight:600}
.hm-name{text-align:left;padding:6px 8px;font-size:12px;white-space:nowrap}
.hm-name b{font-family:ui-monospace,monospace}
.hm-name span{color:var(--txt3);font-size:11px}
.hm-c{text-align:center;font-family:ui-monospace,monospace;font-size:12px;font-weight:700;border-radius:5px;height:30px;width:18%}
.hm-turn{font-size:9.5px;color:#0A0E17;background:#4CC2E0;border-radius:4px;padding:1px 6px;font-weight:700;letter-spacing:.3px;margin-left:6px}
.sc{width:100%;border-collapse:separate;border-spacing:2px}
.sc-h{font-size:9.5px;color:var(--txt3);text-align:center;padding:4px 2px;font-family:ui-monospace,monospace;text-transform:uppercase;letter-spacing:.3px;font-weight:600}
.sc-name{text-align:left;padding:7px 8px;font-size:12px;white-space:nowrap;background:var(--bg3);border-radius:5px}
.sc-name b{font-family:ui-monospace,monospace}
.sc-name span{color:var(--txt3);font-size:11px}
.sc-c{text-align:center;font-size:14px;font-weight:700;background:var(--bg3);border-radius:5px}
.sc-tot{text-align:center;font-family:ui-monospace,monospace;font-weight:700;font-size:13px;background:var(--bg3);border-radius:5px}
.sc-act{text-align:center;font-size:11px;font-weight:700;background:var(--bg3);border-radius:5px;padding:0 6px}
.sc-acc{font-size:9px;color:#0A0E17;background:#F4B740;border-radius:4px;padding:1px 5px;font-weight:700;margin-left:6px}
.sc-warn{font-size:9px;color:#0A0E17;background:#F4607A;border-radius:4px;padding:1px 5px;font-weight:700;margin-left:6px}
.lbreadth{font-size:10px;border:1px solid;border-radius:5px;padding:1px 6px;margin-left:8px;font-weight:600}
.sc-grp,.rk-grp{background:#0E1521 !important;color:#5B8CFF;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;padding:8px 10px !important;text-align:left;border-top:2px solid #1C2740}
.fgwrap{display:flex;align-items:baseline;gap:14px;margin:2px 0 4px}
.fgnum{font-size:42px;font-weight:800;line-height:1}.fgnum span{font-size:15px;color:var(--txt3);font-weight:600}
.fgzone{font-size:17px;font-weight:700}
.fgbar{position:relative;height:10px;border-radius:6px;margin:8px 0 6px;background:linear-gradient(90deg,#F4607A,#F4824A,#F4B740,#7FC97F,#2FD08A)}
.fgmark{position:absolute;top:-3px;width:3px;height:16px;background:#fff;transform:translateX(-50%);border-radius:2px;box-shadow:0 0 3px #000}
.fgctx{display:flex;gap:8px;flex-wrap:wrap;margin:6px 0}
.fgchip{font-size:11px;color:var(--txt3);border:1px solid #1C2740;border-radius:6px;padding:2px 7px}
.verdict{border:1px solid #2B3850;background:linear-gradient(180deg,rgba(91,140,255,.06),var(--bg2))}
.vrow{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;padding:7px 0;border-bottom:1px solid #131C2B;font-size:14px;color:#C7D3E3;line-height:1.5}
.vrow:last-of-type{border-bottom:none}
.vk{flex:0 0 auto;font-size:10px;font-weight:700;color:#0A0E17;border-radius:5px;padding:2px 9px;letter-spacing:.3px}
details.why{grid-column:1/-1;margin-bottom:14px}
details.why[open]{display:grid;grid-template-columns:1.55fr 1fr;gap:14px}
@media(max-width:900px){details.why[open]{grid-template-columns:1fr}}
details.why>summary{grid-column:1/-1;cursor:pointer;list-style:none;background:var(--bg2);border:1px solid var(--line);border-radius:10px;padding:13px 15px;font-size:14px;font-weight:600;color:var(--txt1);user-select:none}
details.why>summary::-webkit-details-marker{display:none}
details.why>summary::before{content:'▸ ';color:#5B8CFF}
details.why>summary span{color:var(--txt3);font-weight:400;font-size:12px}
details.why[open]>summary{color:#5B8CFF}
details.why[open]>summary::before{content:'▾ '}
.readbox{display:flex;gap:12px;align-items:flex-start;background:var(--bg3);border:1px solid var(--line);border-radius:10px;padding:14px}
.read-light{width:14px;height:14px;border-radius:50%;flex:0 0 auto;margin-top:3px;box-shadow:0 0 12px currentColor}
.read-txt{font-size:13px;color:var(--txt);margin-bottom:6px}
.read-stance{font-size:12.5px;font-weight:700}
.pb{width:100%;border-collapse:separate;border-spacing:2px;margin-top:4px}
.pb th{font-size:10px;color:var(--txt3);text-transform:uppercase;letter-spacing:.3px;padding:4px 8px;text-align:right}
.pb .pb-l{text-align:left}
.pb td{background:var(--bg3);padding:7px 8px;font-size:12px}
.pb-l{text-align:left;border-radius:5px 0 0 5px}
.pb-v{text-align:right;font-family:ui-monospace,monospace;font-weight:700}
.pb-n{text-align:right;color:var(--txt3);font-size:11px;border-radius:0 5px 5px 0}
.cand{background:var(--bg3);border:1px solid var(--line);border-radius:9px;padding:10px 12px;margin-bottom:8px}
.cand-h{display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:4px}
.cand-h b{font-family:ui-monospace,monospace}
.cand-h span{color:var(--txt3);font-size:11px}
.cand-sc{margin-left:auto;font-family:ui-monospace,monospace;font-weight:700}
.cand-r{font-size:12px;color:var(--txt2);margin-bottom:2px}
.cand-p{font-size:12px;color:var(--txt)}
.se{width:100%;border-collapse:separate;border-spacing:2px}
.scrollx{overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%}
.se th{font-size:10px;color:var(--txt3);text-transform:uppercase;letter-spacing:.3px;padding:4px 8px;text-align:center}
.se .se-l{text-align:left}
.se td{background:var(--bg3);padding:7px 8px;font-size:12px}
.se-l{text-align:left;border-radius:5px 0 0 5px;white-space:nowrap}
.se-c{text-align:center}
.se-pup{font-family:ui-monospace,monospace;font-weight:700;font-size:13px;display:block}
.se-avg{font-family:ui-monospace,monospace;font-size:10px;display:block;margin-top:1px}
.se-hi td{background:#1A2233}
.se-now{font-size:9px;color:#0A0E17;background:#5B8CFF;border-radius:4px;padding:1px 6px;font-weight:700;margin-left:8px}
.se-next{font-size:9px;color:#0A0E17;background:#2FD08A;border-radius:4px;padding:1px 6px;font-weight:700;margin-left:8px}
.bar-cmf{font-family:ui-monospace,monospace;font-size:10px;margin-left:8px;min-width:62px;text-align:right}
@media(max-width:640px){.sc-name span{display:none}.sc-h{font-size:8px}.sc-act{font-size:9px}}
@media(max-width:600px){.hm-name span{display:none}.hm-c{font-size:11px}}
footer{font-size:10.5px;color:var(--txt3);text-align:center;padding:18px 20px;max-width:760px;margin:0 auto;line-height:1.6}
"""

def render_svg(rrg, flow=None, quality=None):
    flow = flow or {}
    W, H = 1040, 720
    mL, mR, mT, mB = 60, 66, 28, 54
    pw, ph = W - mL - mR, H - mT - mB
    maxdev = 4.0
    for d in rrg.values():
        maxdev = max(maxdev, abs(d["ratio"] - 100), abs(d["mom"] - 100))
        for r, m in d["tail"]:
            maxdev = max(maxdev, abs(r - 100), abs(m - 100))
    r = max(6, min(18, math.ceil(maxdev) + 2))
    lo, hi = 100 - r, 100 + r
    X = lambda v: mL + (v - lo) / (hi - lo) * pw
    Y = lambda v: mT + (1 - (v - lo) / (hi - lo)) * ph
    cx, cy = X(100), Y(100)
    qof = lambda rr, mm: ("Lider" if rr >= 100 and mm >= 100 else "Debilitandose" if rr >= 100
                          else "Mejorando" if mm >= 100 else "Rezagado")
    s = [f'<svg viewBox="0 0 {W} {H}">']
    quads = [(cx, mT, mL + pw - cx, cy - mT, "#2FD08A"),
             (cx, cy, mL + pw - cx, mT + ph - cy, "#F4B740"),
             (mL, cy, cx - mL, mT + ph - cy, "#F4607A"),
             (mL, mT, cx - mL, cy - mT, "#4CC2E0")]
    for x, y, w, h, c in quads:
        s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" fill="{c}" opacity="0.06"/>')
    for i in range(9):
        vx = lo + (hi - lo) * i / 8
        s.append(f'<line x1="{X(vx):.1f}" y1="{mT}" x2="{X(vx):.1f}" y2="{mT+ph}" stroke="#1E2A3D"/>')
    for i in range(7):
        vy = lo + (hi - lo) * i / 6
        s.append(f'<line x1="{mL}" y1="{Y(vy):.1f}" x2="{mL+pw}" y2="{Y(vy):.1f}" stroke="#1E2A3D"/>')
    s.append(f'<line x1="{cx:.1f}" y1="{mT}" x2="{cx:.1f}" y2="{mT+ph}" stroke="#2A3A52" stroke-width="1.5"/>')
    s.append(f'<line x1="{mL}" y1="{cy:.1f}" x2="{mL+pw}" y2="{cy:.1f}" stroke="#2A3A52" stroke-width="1.5"/>')
    corners = [(mL+pw-8, mT+17, "LIDER", "end", "#2FD08A"),
               (mL+pw-8, mT+ph-8, "DEBILITANDOSE", "end", "#F4B740"),
               (mL+8, mT+ph-8, "REZAGADO", "start", "#F4607A"),
               (mL+8, mT+17, "MEJORANDO", "start", "#4CC2E0")]
    for x, y, t, a, c in corners:
        s.append(f'<text x="{x}" y="{y}" fill="{c}" font-size="13" font-family="ui-monospace,monospace" '
                 f'text-anchor="{a}" opacity="0.7" letter-spacing="1">{t}</text>')
    s.append(f'<text x="{mL+pw/2:.0f}" y="{H-14}" fill="#5E708A" font-size="11" text-anchor="middle" '
             f'font-family="ui-monospace,monospace">RS-Ratio - fuerza relativa -></text>')
    s.append(f'<text x="16" y="{mT+ph/2:.0f}" fill="#5E708A" font-size="11" text-anchor="middle" '
             f'font-family="ui-monospace,monospace" transform="rotate(-90 16 {mT+ph/2:.0f})">RS-Momentum - impulso -></text>')
    labels = []
    for sym, d in rrg.items():
        col = QUAD[d["quad"]][1]
        tail = d["tail"]
        tdates = d.get("tail_dates", [""] * len(tail))
        nm = NAMES.get(sym, (sym, sym, ""))[1]
        # estela: linea con degradado + un PUNTO por semana (con fecha al pasar el raton)
        for i in range(1, len(tail)):
            a, b = tail[i-1], tail[i]
            op = 0.10 + 0.6 * (i / max(1, len(tail)-1))
            s.append(f'<line x1="{X(a[0]):.1f}" y1="{Y(a[1]):.1f}" x2="{X(b[0]):.1f}" y2="{Y(b[1]):.1f}" '
                     f'stroke="{col}" stroke-width="1.6" stroke-opacity="{op:.2f}" stroke-linecap="round"/>')
        for i in range(len(tail) - 1):   # semanas anteriores (no la actual)
            rr, mm = tail[i]
            op = 0.25 + 0.5 * (i / max(1, len(tail)-1))
            wk = tdates[i] if i < len(tdates) else ""
            info = f"{sym} · semana {wk} · {qof(rr, mm)} (fuerza {rr:.0f}, impulso {mm:.0f})"
            s.append(f'<circle cx="{X(rr):.1f}" cy="{Y(mm):.1f}" r="3" fill="{col}" fill-opacity="{op:.2f}" '
                     f'stroke="#0A0E17" stroke-width="0.5"/>'
                     f'<circle cx="{X(rr):.1f}" cy="{Y(mm):.1f}" r="9" fill="transparent" class="tdot" '
                     f'data-t="{esc(info)}" style="cursor:pointer"><title>{esc(info)}</title></circle>')
        lx, ly = X(d["ratio"]), Y(d["mom"])
        labels.append((sym, lx, ly, col, nm, d, tail))
    # anillos de FLUJO (verde = entra dinero / acumulacion; doble rojo = cuidado, distribucion oculta)
    def _rad(sym):
        if quality is not None and sym in quality:
            q = max(-1.0, min(8.0, quality[sym]))
            return 4.0 + (q + 1.0) / 9.0 * 7.0
        return 6.5
    for sym, lx, ly, col, nm, d, tail in labels:
        f = flow.get(sym, {})
        dv = f.get("diverg")
        lab = f.get("label")
        rr = _rad(sym)
        if dv == "distribucion oculta":
            s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rr+3:.1f}" fill="none" stroke="#F4607A" stroke-width="1.4"/>')
            s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rr+5.5:.1f}" fill="none" stroke="#F4607A" stroke-width="1.4" stroke-opacity="0.55"/>')
        elif dv == "acumulacion oculta":
            s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rr+3:.1f}" fill="none" stroke="#2FD08A" stroke-width="1.6"/>')
        elif lab == "Acumulacion" and f.get("cmf", 0) > 0:
            s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rr+3:.1f}" fill="none" stroke="#2FD08A" stroke-width="1.1" stroke-opacity="0.45"/>')
        elif lab == "Distribucion" and f.get("cmf", 0) < 0:
            s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rr+3:.1f}" fill="none" stroke="#F4607A" stroke-width="1.1" stroke-opacity="0.45"/>')
    # flecha de direccion + punto actual (en TODOS, brillante y encima)
    for sym, lx, ly, col, nm, d, tail in labels:
        if len(tail) >= 2:
            ax, ay = X(tail[-2][0]), Y(tail[-2][1])
            ang = math.atan2(ly - ay, lx - ax)
            if abs(lx - ax) > 0.3 or abs(ly - ay) > 0.3:
                tip = (lx + 13 * math.cos(ang), ly + 13 * math.sin(ang))
                b1 = (lx + 4 * math.cos(ang + 2.6), ly + 4 * math.sin(ang + 2.6))
                b2 = (lx + 4 * math.cos(ang - 2.6), ly + 4 * math.sin(ang - 2.6))
                s.append(f'<polygon points="{tip[0]:.1f},{tip[1]:.1f} {b1[0]:.1f},{b1[1]:.1f} {b2[0]:.1f},{b2[1]:.1f}" '
                         f'fill="{col}"/>')
        rel = d.get("rel4", 0)
        # precio de las ultimas 8 semanas, para ver si el precio acompana a la estela
        p8 = ""
        try:
            _s = df[sym].dropna()
            if len(_s) >= 9:
                _c = (float(_s.iloc[-1]) / float(_s.iloc[-9]) - 1) * 100
                _a = "↑ sube" if _c > 2 else "↓ baja" if _c < -2 else "→ plano"
                p8 = f" | precio 8s: {_a} {_c:+.1f}%"
        except Exception:
            pass
        f = flow.get(sym, {})
        fl = ""
        if f.get("diverg") == "distribucion oculta":
            fl = " | ⚠ distribucion oculta (cuidado)"
        elif f.get("diverg") == "acumulacion oculta":
            fl = " | entra dinero (acumulacion oculta)"
        else:
            _c = f.get("cmf")
            if _c is not None:
                _w = "entra dinero" if _c > 0.05 else "sale dinero" if _c < -0.05 else "plano"
                fl = f" | flujo: {_w} (CMF {_c:+.2f})"
        info = (f"{sym} · {nm} — {QUAD[d['quad']][0]} | fuerza {d['ratio']:.1f}, "
                f"impulso {d['mom']:.1f} | vs indice 4s {rel:+.1f}%{p8}{fl}")
        if quality is not None and sym in quality:
            rad = _rad(sym)
        else:
            rad = 6.5
        s.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="{rad:.1f}" fill="{col}" stroke="#0A0E17" stroke-width="1.8" '
                 f'class="tdot" data-t="{esc(info)}" style="cursor:pointer"><title>{esc(info)}</title></circle>')
    # etiquetas: columna a cada lado + linea guia desde la bola a su nombre (sin ambiguedad)
    GAP = 14
    rightballs = sorted([l for l in labels if l[1] >= cx], key=lambda p: p[2])   # bolas en mitad derecha -> nombre a la derecha
    leftballs = sorted([l for l in labels if l[1] < cx], key=lambda p: p[2])     # bolas en mitad izquierda -> nombre a la izquierda

    def place(group, side):
        if not group:
            return
        xs = [lx for _, lx, _, _, _, _, _ in group]
        if side == "right":
            colx = min(W - 6, max(xs) + 18); anchor = "start"
        else:
            colx = max(6, min(xs) - 18); anchor = "end"
        tys = [p[2] for p in group]                  # deseado = altura de su bola
        for i in range(1, len(tys)):                 # separar hacia abajo
            if tys[i] - tys[i-1] < GAP:
                tys[i] = tys[i-1] + GAP
        over = tys[-1] - (mT + ph - 4)               # si se sale por abajo, subir todo
        if over > 0:
            tys = [t - over for t in tys]
        if tys[0] < mT + 10:                          # si se sale por arriba, bajar todo
            sh = (mT + 10) - tys[0]
            tys = [t + sh for t in tys]
        anchorx = colx - 2 if side == "right" else colx + 2
        for (sym, lx, ly, col, nm, d, tail), ty in zip(group, tys):
            s.append(f'<line x1="{lx:.1f}" y1="{ly:.1f}" x2="{anchorx:.1f}" y2="{ty-3:.1f}" '
                     f'stroke="{col}" stroke-width="0.7" stroke-opacity="0.55"/>')
            info = f"{sym} · {nm}"
            s.append(f'<text x="{colx:.1f}" y="{ty:.1f}" fill="#E6EDF6" font-size="11.5" text-anchor="{anchor}" '
                     f'font-family="ui-monospace,monospace" font-weight="600" class="tdot" data-t="{esc(info)}" '
                     f'style="cursor:pointer"><title>{esc(info)}</title>{sym}</text>')
    place(rightballs, "right")
    place(leftballs, "left")
    s.append("</svg>")
    return "".join(s)

def quadrant_grid(rrg):
    """Vista alternativa: cuatro cajas con los ETFs de cada cuadrante (sin solapes)."""
    order = ["leading", "weakening", "improving", "lagging"]
    titles = {"leading": "LIDER", "weakening": "DEBILITANDOSE", "improving": "MEJORANDO", "lagging": "REZAGADO"}
    buckets = {q: [] for q in order}
    for sym, d in rrg.items():
        buckets[d["quad"]].append((sym, d["mom"], d["ratio"]))
    for q in buckets:
        buckets[q].sort(key=lambda x: -x[1])
    cells = ""
    for q in order:
        col = QUAD[q][1]
        chips = ""
        for sym, mom, ratio in buckets[q]:
            nm = NAMES.get(sym, (sym, sym, ""))[1]
            chips += (f"<span class='qchip' style='border-color:{col}33' title='{esc(sym)} · {esc(nm)}'>"
                      f"<b style='color:{col}'>{sym}</b> <i>{ratio:.0f}/{mom:.0f}</i></span>")
        if not chips:
            chips = "<span class='qempty'>—</span>"
        cells += (f"<div class='qcell' style='border-top:2px solid {col}'>"
                  f"<div class='qhead' style='color:{col}'>{titles[q]} <span>{QUAD[q][2]}</span></div>"
                  f"<div class='qchips'>{chips}</div></div>")
    return f"<div class='qgrid'>{cells}</div>"

def esc(x):
    return str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def _pm(v):
    if v is None:
        return "n/d"
    return f"{'+' if v >= 0 else ''}{v}%"

def equity_svg(dates, eq_s, eq_b):
    W, H = 900, 250
    mL, mR, mT, mB = 50, 16, 16, 28
    pw, ph = W - mL - mR, H - mT - mB
    allv = eq_s + eq_b
    lo, hi = min(allv), max(allv)
    rng = (hi - lo) or 1e-9
    n = len(eq_s)
    X = lambda i: mL + pw * i / max(1, n - 1)
    Y = lambda v: mT + ph * (1 - (v - lo) / rng)
    def poly(arr, col, w):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(arr))
        return f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="{w}" stroke-linejoin="round"/>'
    grid = []
    for g in range(5):
        v = lo + rng * g / 4
        y = Y(v)
        grid.append(f'<line x1="{mL}" y1="{y:.1f}" x2="{mL+pw}" y2="{y:.1f}" stroke="#1E2A3D"/>'
                    f'<text x="{mL-6}" y="{y+3:.1f}" fill="#5E708A" font-size="10" text-anchor="end" '
                    f'font-family="ui-monospace,monospace">{v:.2f}x</text>')
    return (f'<svg viewBox="0 0 {W} {H}" style="width:100%;height:auto">'
            + "".join(grid) + poly(eq_b, "#93A4BC", 1.6) + poly(eq_s, "#5B8CFF", 2.2)
            + f'<text x="{mL+pw}" y="{mT+10}" fill="#5B8CFF" font-size="11" text-anchor="end" '
              f'font-family="ui-monospace,monospace">Estrategia</text>'
            + f'<text x="{mL+pw}" y="{mT+24}" fill="#93A4BC" font-size="11" text-anchor="end" '
              f'font-family="ui-monospace,monospace">Comprar y mantener {BENCH}</text>'
            + "</svg>")

def fresh_stocks(leaders, etf, n=2, max_hi=90):
    """Acciones de un ETF que ACELERAN (su RS de 3m sube) y NO estan en maximos (no extendidas).
    Devuelve hasta n, priorizando mayor aceleracion. Si ninguna pasa el tope, lo relaja para
    dar siempre 'las que mas aceleran y menos estiradas' (excluye las pegadas a maximos como MLI)."""
    if not leaders or etf not in leaders:
        return []
    rows = leaders[etf]
    def pick(mh, minrs):
        c = [r for r in rows if r.get("drs") is not None and r["drs"] > 0
             and r.get("hi", 100) < mh and r.get("rs", 0) >= minrs]
        c.sort(key=lambda r: -r["drs"])
        return c
    c = pick(max_hi, 45) or pick(95, 35) or pick(100, 30)
    return c[:n]


def compute_watchlist(tickers):
    """Para cada accion vigilada: descarga OHLCV, calcula FASE + FLUJO (OBV/CMF/distribucion) y un ESTADO
    que detecta cuando una hundida empieza a ACUMULAR (dinero entrando) antes de la siguiente subida."""
    if not tickers:
        return None
    try:
        data = yf.download(tickers, period="2y", interval="1d", progress=False,
                           group_by="ticker", auto_adjust=True, threads=True)
    except Exception:
        data = None
    daily, closes = {}, {}
    if data is not None:
        for t in tickers:
            try:
                d = data if len(tickers) == 1 else data[t]
                d = d.dropna(subset=["Close"])
                if len(d) >= 40:
                    daily[t] = d
                    closes[t] = d["Close"]
            except Exception:
                continue
    flow = compute_volume_flow(daily) if daily else {}
    out = []
    for t in tickers:
        if t not in closes:
            out.append({"sym": t, "name": WATCH_NAMES.get(t, t), "ok": False})
            continue
        s = closes[t].dropna()
        price = float(s.iloc[-1])
        win = s.iloc[-252:]
        mx, mn = float(win.max()), float(win.min())
        hi52 = round(price / mx * 100) if mx else 0           # % del maximo de 52s
        frm_lo = round((price / mn - 1) * 100) if mn else 0    # % por encima del minimo de 52s
        n3 = min(63, len(s) - 1)
        mom3 = round((price / float(s.iloc[-1 - n3]) - 1) * 100, 1)
        f = flow.get(t, {})
        ph = _phase(s, None)
        diverg = f.get("diverg")
        entrando = bool(f.get("obv_cross") or (diverg == "acumulacion oculta") or (f.get("cmf_pos") and f.get("obv_above")))
        if diverg == "distribucion oculta" or ph == "distrib":
            estado, ecol = "🟠 distribución — ojo, el dinero sale", "#F4B740"
        elif ph == "sube":
            estado, ecol = "🟢 subiendo — ya arrancó", "#2FD08A"
        elif entrando and ph in ("base", "lateral", "baja"):
            estado, ecol = "🟢 empezando a acumular — el dinero entra", "#2FD08A"
        elif ph == "baja":
            estado, ecol = "🔴 aún cayendo — cuchillo, no toques", "#F4607A"
        elif ph in ("base", "lateral"):
            estado, ecol = "🟦 en base, sin flujo — acumulando callado, espera", "#5AA9E6"
        else:
            estado, ecol = "⚪ sin señal clara", "#9FB0C8"
        out.append({"sym": t, "name": WATCH_NAMES.get(t, t), "ok": True, "price": price,
                    "phase": ph, "hi52": hi52, "frm_lo": frm_lo, "mom3": mom3,
                    "cmf": f.get("cmf"), "obv_above": f.get("obv_above"), "obv_cross": f.get("obv_cross"),
                    "diverg": diverg, "entrando": entrando, "estado": estado, "ecol": ecol})
    return out


CICLO_FASES = [
    ("recuperacion", "Recuperación", "Inicio de ciclo", "#2FD08A",
     ["XLF", "KRE", "XLY", "XRT", "XLI", "XLRE", "IWM", "XBI", "JETS"],
     "Sale de recesión: bajan tipos, curva empinada. Lideran financieras, consumo discrecional, industriales y small caps."),
    ("expansion", "Expansión", "Mitad de ciclo", "#4CC2E0",
     ["XLK", "SMH", "IGV", "XLI", "XLC", "CIBR", "SKYY"],
     "Crecimiento sólido y sostenido. Lideran tecnología, industriales y comunicaciones."),
    ("sobrecalentamiento", "Sobrecalentamiento", "Final de ciclo", "#F4B740",
     ["XLE", "XLB", "XOP", "COPX", "XME", "GLD", "XLP"],
     "Economía recalentada, inflación subiendo, la Fed sube tipos. Lideran energía, materiales y materias primas."),
    ("recesion", "Recesión", "Contracción", "#F4607A",
     ["XLU", "XLP", "XLV", "TLT", "GLD"],
     "Contracción. Refugio en defensivos: utilities, consumo básico, salud y bonos."),
]


def compute_cycle_phase(rrg, scores):
    """Deduce en que fase del ciclo economico estamos segun que sectores tienen el dinero (Lider/Mejorando en el RRG).
    Mapa orientativo basado en el modelo de rotacion sectorial (Fidelity/Stovall), no una prediccion."""
    fases = []
    for key, lbl, sub, col, secs, desc in CICLO_FASES:
        lit, tot = [], 0
        for s in secs:
            d = rrg.get(s)
            if d is None:
                continue
            tot += 1
            if d.get("quad") in ("leading", "improving"):
                lit.append(s)
        ratio = (len(lit) / tot) if tot else 0.0
        fases.append({"key": key, "lbl": lbl, "sub": sub, "col": col, "desc": desc,
                      "secs": secs, "lit": lit, "ratio": ratio, "n": len(lit), "tot": tot})
    cur = max(fases, key=lambda x: (x["ratio"], x["n"])) if fases else None
    return {"fases": fases, "actual": cur}


def cycle_clock_html(cyc):
    """Dibuja un reloj del ciclo economico (4 cuadrantes) con la aguja en la fase actual."""
    import math
    if not cyc or not cyc.get("actual"):
        return ""
    fases, cur = cyc["fases"], cyc["actual"]
    by_key = {f["key"]: f for f in fases}
    order = ["recuperacion", "expansion", "sobrecalentamiento", "recesion"]
    cx, cy, R = 150, 150, 95
    def pt(r, ang):
        a = math.radians(ang)
        return (cx + r * math.sin(a), cy - r * math.cos(a))
    wedges, labels = "", ""
    cur_idx = order.index(cur["key"]) if cur["key"] in order else 0
    for i, key in enumerate(order):
        f = by_key[key]
        active = (key == cur["key"])
        x0, y0 = pt(R, i * 90)
        x1, y1 = pt(R, i * 90 + 90)
        fill = f["col"] if active else f["col"] + "26"
        wedges += (f"<path d='M{cx},{cy} L{x0:.1f},{y0:.1f} A{R},{R} 0 0 1 {x1:.1f},{y1:.1f} Z' "
                   f"fill='{fill}' stroke='#0b0f17' stroke-width='2'/>")
        lx, ly = pt(R + 24, i * 90 + 45)
        labels += (f"<text x='{lx:.0f}' y='{ly:.0f}' fill='{f['col'] if active else '#9FB0C8'}' font-size='11' "
                   f"font-weight='{700 if active else 500}' text-anchor='middle'>{f['lbl']}</text>"
                   f"<text x='{lx:.0f}' y='{ly+13:.0f}' fill='#5E708A' font-size='8.5' text-anchor='middle'>{f['n']}/{f['tot']} con dinero</text>")
    nx, ny = pt(R - 16, cur_idx * 90 + 45)
    needle = (f"<line x1='{cx}' y1='{cy}' x2='{nx:.1f}' y2='{ny:.1f}' stroke='{cur['col']}' stroke-width='3.5' stroke-linecap='round'/>"
              f"<circle cx='{cx}' cy='{cy}' r='6' fill='{cur['col']}'/>")
    return ("<svg viewBox='0 0 300 300' style='width:100%;max-width:280px;display:block;margin:4px auto 0'>"
            + wedges + needle + labels + "</svg>")


def compute_suelo(df, rrg, scores, flow, meanrev):
    """DURMIENTES: sectores machacados y OLVIDADOS (el silencio pesa doble) cuyo impulso empieza
    a girar mientras el precio apenas se ha movido — la anticipacion de la subida, tu caso China.
    Ingredientes 0-10: castigo + SILENCIO (volumen bajisimo, nadie habla de el) + semanas dormido
    + estructura 0/3 + GIRO (verticalidad del impulso) + precio aun quieto + flujo despertando.
    OJO: condiciones de suelo, no el suelo — y sin flujo que deje de sangrar, no hay trato."""
    if not rrg or not flow:
        return None
    _n3 = {}
    for r in (scores or []):
        _n3[r["sym"]] = sum(1 for _, v in r["parts"][:3] if v)
    rows = []
    for s, d in rrg.items():
        if s == BENCH or s in SINTETICOS:
            continue
        if not (d["quad"] == "lagging" or (d["ratio"] <= 97.5 and d["mom"] <= 101)):
            continue
        pts, det = 0, []
        # --- 1) CASTIGO (max 3) ---
        hi52 = None
        if s in df.columns:
            ser = df[s].dropna()
            if len(ser) >= 20:
                hi52 = float(ser.iloc[-1] / ser.iloc[-min(52, len(ser)):].max() * 100)
        if hi52 is not None:
            if hi52 <= 70:
                pts += 2; det.append(f"−{100 - hi52:.0f}% de su máx 52s (paliza)")
            elif hi52 <= 82:
                pts += 1; det.append(f"−{100 - hi52:.0f}% de su máx 52s")
        mg = ((meanrev or {}).get(s) or {}).get("margen")
        if mg is not None and mg >= 12:
            pts += 1; det.append(f"{mg:.0f} pts bajo su media histórica")
        # --- 2) SILENCIO (max 4, POTENCIADO: el ingrediente que pediste subir) ---
        f = flow.get(s, {}) or {}
        vr = f.get("vol_rel5", f.get("vol_rel"))
        sil = 0
        if vr is not None:
            if vr < 0.80:
                sil = 3; det.append(f"volumen {vr:.2f}× — nadie habla de él")
            elif vr < 0.95:
                sil = 2; det.append(f"volumen {vr:.2f}× (poca atención)")
            elif vr < 1.10:
                sil = 1; det.append(f"volumen {vr:.2f}×")
        pts += sil
        wk_lag = 0
        for rr, mm in zip(reversed(d.get("ratio_series") or []), reversed(d.get("mom_series") or [])):
            if rr is None or mm is None or rr != rr or mm != mm:
                break
            if quad_of(rr, mm) == "lagging":
                wk_lag += 1
            else:
                break
        if wk_lag >= 8:
            pts += 1; det.append(f"{wk_lag} semanas dormido en Rezagado")
        # --- 3) ESTRUCTURA 0/3 (max 2) ---
        n3 = _n3.get(s)
        if n3 == 0:
            pts += 2; det.append("0/3 estructurales (64-65% hist. a 4 sem)")
        elif n3 == 1:
            pts += 1; det.append("1/3 estructurales")
        # --- 4) GIRO: la estela se pone vertical (max 3) ---
        tail = d.get("tail") or []
        dmom, vert = None, None
        if len(tail) >= 4:
            r_now, m_now = tail[-1]
            r_prev, m_prev = tail[-4]
            dmom = m_now - m_prev
            vert = dmom / max(0.6, abs(r_now - r_prev)) if dmom is not None else None
            if dmom >= 1.5 and (vert or 0) >= 1.8:
                pts += 2; det.append(f"GIRO VERTICAL {vert:.1f}× (impulso +{dmom:.1f} en 3s)")
            elif dmom >= 1.5:
                pts += 1; det.append(f"impulso girando (+{dmom:.1f} en 3s)")
        # --- 5) PRECIO AUN QUIETO: gira el impulso pero el precio apenas se ha movido (tu China) ---
        quieto = None
        if s in df.columns:
            ser = df[s].dropna()
            if len(ser) >= 5:
                quieto = float(ser.iloc[-1] / ser.iloc[-5] - 1) * 100
                if dmom is not None and dmom >= 1.5 and abs(quieto) <= 2.5:
                    pts += 1; det.append(f"precio aún quieto ({quieto:+.1f}% en 4s): anticipación")
        # --- 6) FLUJO: deja de sangrar o ya entra (max 2) ---
        cmf = f.get("cmf")
        if cmf is not None:
            if cmf > 0.05:
                pts += 2; det.append("CMF>+0.05: el dinero ya ENTRA")
            elif cmf >= -0.05:
                pts += 1; det.append("CMF plano: dejó de salir")
        sangra = (cmf is not None and cmf < -0.05)
        despertando = bool((dmom or 0) >= 1.5 and not sangra and pts >= 6)
        rows.append({"sym": s, "pts": min(pts, 10), "det": det, "hi52": hi52, "vr": vr, "sil": sil,
                     "wk_lag": wk_lag, "n3": n3, "cmf": cmf, "dmom": dmom,
                     "vert": (round(vert, 1) if vert is not None else None),
                     "quieto": (round(quieto, 1) if quieto is not None else None),
                     "sangra": sangra, "despertando": despertando})
    rows.sort(key=lambda r: (-int(r["despertando"]), -r["pts"], (r["hi52"] if r["hi52"] is not None else 999)))
    return [r for r in rows if r["pts"] >= 5][:12] or None


def compute_giro_intradia(daily, rrg=None):
    """Huella del GIRO INTRADIA en la ultima vela diaria: gap de apertura fuerte que la sesion
    revierte. Gap arriba + cierre en el tercio bajo del rango = abrieron comprando y cerraron
    VENDIENDO (distribuyen aprovechando la liquidez del gap). Gap abajo + cierre arriba = compraron
    el miedo. Con velas diarias el aviso llega AL CIERRE, no en vivo: sirve para leer la manana
    siguiente, no para operar la sesion."""
    rows = []
    for sym, d in (daily or {}).items():
        try:
            if not {"Open", "High", "Low", "Close"}.issubset(d.columns):
                continue
            dd = d.dropna(subset=["Open", "High", "Low", "Close"])
            if len(dd) < 21:
                continue
            o, h, l, c = (float(dd["Open"].iloc[-1]), float(dd["High"].iloc[-1]),
                          float(dd["Low"].iloc[-1]), float(dd["Close"].iloc[-1]))
            pc = float(dd["Close"].iloc[-2])
            if min(o, h, l, c, pc) <= 0 or h <= l:
                continue
            gap = (o / pc - 1) * 100
            intra = (c / o - 1) * 100
            pos = (c - l) / (h - l)          # 0 = cierra en minimos · 1 = cierra en maximos
            vol_rel = None
            if "Volume" in dd.columns:
                v = dd["Volume"].astype(float)
                m = v.iloc[-21:-1].mean()
                if m and m > 0:
                    vol_rel = float(v.iloc[-1] / m)
            sig = None
            if gap >= 1.2 and (pos <= 0.35 or intra <= -1.0):
                sig = "bajista"              # vendieron la subida
            elif gap <= -1.2 and pos >= 0.65:
                sig = "alcista"              # compraron el miedo
            if sig:
                rows.append({"sym": sym, "sig": sig, "gap": round(gap, 1), "intra": round(intra, 1),
                             "pos": int(round(pos * 100)), "vol_rel": (round(vol_rel, 2) if vol_rel else None),
                             "fecha": str(dd.index[-1].date()),
                             "quad": ((rrg or {}).get(sym) or {}).get("quad")})
        except Exception:
            continue
    if not rows:
        return None
    rows.sort(key=lambda r: -abs(r["gap"]))
    # el patron de Pedro: venden lo CALIENTE (Lider/Debilitandose) y compran lo FRIO (Rezagado/Mejorando) el mismo dia
    rot_flag = (any(r["sig"] == "bajista" and r["quad"] in ("leading", "weakening") for r in rows)
                and any(r["sig"] == "alcista" and r["quad"] in ("lagging", "improving") for r in rows))
    return {"rows": rows[:10], "rotacion": rot_flag, "fecha": rows[0]["fecha"]}


def compute_semis_desk(df, daily, rrg, flow, scores, leaders, giro=None):
    """Mesa de poker de los SEMICONDUCTORES: la 'mano' actual (estado), la 'mesa'
    (probabilidades HISTORICAS de rebote a 4 semanas condicionadas a la profundidad de la
    caida, con intervalo de confianza Wilson 95%) y el 'bote' (EV y tamano fraccional).
    Todo calculado sobre la serie real disponible del propio SMH — sin numeros inventados."""
    sym = "SMH" if "SMH" in df.columns else ("SOXX" if "SOXX" in df.columns else None)
    if not sym:
        return None
    w = df[sym].dropna()
    # si la serie diaria tiene mas historia, la resampleamos a semanal para engordar la muestra
    try:
        dser = (daily or {}).get(sym)
        if dser is not None and "Close" in dser.columns:
            wl = dser["Close"].dropna().resample("W-FRI").last().dropna()
            if len(wl) > len(w):
                w = wl
    except Exception:
        pass
    if len(w) < 30:
        return None
    # --- LA MANO: estado actual ---
    hi52 = float(w.iloc[-1] / w.iloc[-min(52, len(w)):].max() * 100)
    dd52 = hi52 - 100.0                                   # caida desde maximos (negativa)
    r4 = w.pct_change(4).dropna()
    z4 = float((r4.iloc[-1] - r4.mean()) / (r4.std() or 1.0)) if len(r4) > 10 else 0.0
    ma40 = w.rolling(40, min_periods=20).mean()
    vs40 = float(w.iloc[-1] / ma40.iloc[-1] - 1) * 100 if ma40.iloc[-1] == ma40.iloc[-1] else None
    chg = w.pct_change().dropna()
    streak = 0
    for v in reversed(list(chg)):
        if v < 0:
            streak += 1
        else:
            break
    d = rrg.get(sym, {}) or {}
    f = (flow or {}).get(sym, {}) or {}
    sc = next((r for r in (scores or []) if r["sym"] == sym), {}) or {}
    lead = (leaders or {}).get(sym) or []
    wash = None
    if lead:
        wash = int(round(100 * sum(1 for r in lead if r.get("phase") == "baja" or (r.get("rs") or 99) < 30) / len(lead)))
    g = None
    for row in ((giro or {}).get("rows") or []):
        if row["sym"] in (sym, "SOXX", "SMH"):
            g = row
            break
    # --- LA MESA: prob. historica de estar mas arriba 4 semanas despues, por cubo de caida ---
    hi52s = w / w.rolling(52, min_periods=20).max() * 100
    fwd4 = (w.shift(-4) / w - 1)
    def _wilson(p, n, zz=1.96):
        den = 1 + zz * zz / n
        ctr = (p + zz * zz / (2 * n)) / den
        rad = zz * math.sqrt(p * (1 - p) / n + zz * zz / (4 * n * n)) / den
        return int(round(100 * (ctr - rad))), int(round(100 * (ctr + rad)))
    tbl = []
    for lo, hiB, lbl in [(0, 5, "0–5%"), (5, 10, "5–10%"), (10, 15, "10–15%"), (15, 25, "15–25%"), (25, 100, ">25%")]:
        caida = 100 - hi52s
        mask = (caida >= lo) & (caida < hiB) & fwd4.notna()
        n = int(mask.sum())
        if n >= 3:
            p = float((fwd4[mask] > 0).mean())
            wlo, whi = _wilson(p, n)
            tbl.append({"lbl": lbl, "n": n, "p": int(round(100 * p)), "lo": wlo, "hi": whi,
                        "avg": round(float(fwd4[mask].mean()) * 100, 1),
                        "now": (lo <= -dd52 < hiB)})
    # sobreventa estadistica: retorno 4s por debajo de -1.5 desviaciones
    zview = None
    if len(r4) > 20:
        zmask = r4 <= (r4.mean() - 1.5 * r4.std())
        zf = fwd4.reindex(r4[zmask].index).dropna()
        if len(zf) >= 3:
            p = float((zf > 0).mean())
            wlo, whi = _wilson(p, len(zf))
            zview = {"n": len(zf), "p": int(round(100 * p)), "lo": wlo, "hi": whi,
                     "avg": round(float(zf.mean()) * 100, 1), "now": z4 <= -1.5}
    # --- REBOTE SCORE 0-10: los ingredientes del rebote salvaje ---
    pts, det = 0, []
    if dd52 <= -15:
        pts += 2; det.append(f"caída {dd52:.0f}% desde máximos")
    elif dd52 <= -8:
        pts += 1; det.append(f"caída {dd52:.0f}%")
    if z4 <= -1.5:
        pts += 2; det.append(f"sobreventa z={z4:.1f}")
    elif z4 <= -1.0:
        pts += 1; det.append(f"z={z4:.1f}")
    if streak >= 3:
        pts += 1; det.append(f"{streak} semanas rojas seguidas")
    cmf = f.get("cmf")
    if cmf is not None:
        if cmf > 0.05:
            pts += 2; det.append("CMF: el dinero ya entra")
        elif cmf >= -0.05:
            pts += 1; det.append("CMF plano: dejó de salir")
    if g and g.get("sig") == "alcista":
        pts += 2; det.append(f"giro intradía: compraron el miedo ({g.get('fecha', '')})")
    if wash is not None and wash >= 50:
        pts += 1; det.append(f"washout: {wash}% de componentes rotos")
    tail = d.get("tail") or []
    if len(tail) >= 4 and (tail[-1][1] - tail[-4][1]) >= 1.5:
        pts += 1; det.append("impulso RRG girando al alza")
    pts = min(pts, 10)
    # EV y tamano con el cubo actual
    ev = None
    cur = next((t for t in tbl if t["now"]), None)
    if cur and cur["n"] >= 10:
        ev = {"p": cur["p"], "avg": cur["avg"], "n": cur["n"],
              "kelly4": max(0.0, round((cur["p"] / 100 - (1 - cur["p"] / 100)) * 25, 1))}  # ~Kelly/4 con payoff 1:1, tope abajo
    return {"sym": sym, "dd52": round(dd52, 1), "z4": round(z4, 2), "vs40": (round(vs40, 1) if vs40 is not None else None),
            "streak": streak, "quad": d.get("quad"), "score": sc.get("score"), "cmf": cmf,
            "distrib": sc.get("distrib"), "wash": wash, "giro": g, "tbl": tbl, "zview": zview,
            "pts": pts, "det": det, "ev": ev, "n_hist": len(w)}


def compute_attention_radar(rrg, flow):
    """Cruza tendencia (RRG) con volumen relativo (proxy de atencion del MERCADO, no de prensa, pero capta
    la misma idea de forma fiable) para separar lo que sube EN SILENCIO (volumen normal = joya escondida) de
    lo que sube CON RUIDO (volumen disparado = masificado, posible techo)."""
    if not rrg or not flow:
        return None
    rows = []
    for s, d in rrg.items():
        if s == BENCH:
            continue
        f = flow.get(s)
        if not f:
            continue
        quad = d.get("quad")
        vr = f.get("vol_rel5", f.get("vol_rel"))
        cmf = f.get("cmf")
        rising = quad in ("leading", "improving")
        money_in = (cmf is not None and cmf > 0) or f.get("obv_above")
        if vr is None:
            ruido = "n/d"
        elif vr < 1.1:
            ruido = "🤫 bajo"
        elif vr > 1.5:
            ruido = "📢 alto"
        else:
            ruido = "normal"
        if rising and money_in:
            if vr is not None and vr < 1.15:
                vd, vcol, rank = "🤫 Joya escondida — sube sin ruido", "#2FD08A", 0
            elif vr is not None and vr > 1.5:
                vd, vcol, rank = "📢 Masificado — sube con ruido", "#F4B740", 2
            else:
                vd, vcol, rank = "🟢 Subiendo (ruido normal)", "#7FD8A0", 1
        elif quad in ("weakening", "lagging") and (cmf is not None and cmf < 0):
            vd, vcol, rank = "🩸 Cayendo / sale dinero", "#F4607A", 4
        else:
            vd, vcol, rank = "😴 Dormido / lateral", "#9FB0C8", 3
        rows.append({"sym": s, "quad": quad, "vol_rel": vr, "cmf": cmf,
                     "ruido": ruido, "vd": vd, "vcol": vcol, "rank": rank})
    rows.sort(key=lambda r: (r["rank"], (r["vol_rel"] if r["vol_rel"] is not None else 99)))
    return rows


def _spark(vals, w=70, h=20, color=None, sw=1.4):
    """Mini-linea (sparkline) auto-escalada. Si color es None, verde si termina arriba, rojo si abajo."""
    vals = [float(v) for v in vals if v is not None and v == v]
    if len(vals) < 2:
        return ""
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    n = len(vals)
    pts = " ".join(f"{(i/(n-1))*(w-2)+1:.1f},{h-1-((v-lo)/rng)*(h-2):.1f}" for i, v in enumerate(vals))
    c = color if color else ("#2FD08A" if vals[-1] >= vals[0] else "#F4607A")
    dot = f'<circle cx="{w-1:.1f}" cy="{h-1-((vals[-1]-lo)/rng)*(h-2):.1f}" r="1.6" fill="{c}"/>'
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="vertical-align:middle">'
            f'<polyline points="{pts}" fill="none" stroke="{c}" stroke-width="{sw}"/>{dot}</svg>')


def build_html(df, rrg, alerts, breadth, risk, regime, buy, avoid, sources, fred, flow=None, bt=None,
               dd=None, dd_meta=None, plan=None, fx=None, long_src="", ai_text=None, leaders=None, leaders_n=0, bt2=None, heatmap=None, scores=None, probs=None, season=None, early=None, sector_breadth=None, meanrev=None, nq_close=None, fg_idx=None, spy_flow=None, watch=None, giro=None, semis=None, ia_auto=None):
    rank = {"leading": 0, "weakening": 1, "improving": 2, "lagging": 3}
    ranked = sorted(rrg.items(), key=lambda kv: (rank[kv[1]["quad"]], -kv[1]["mom"]))
    last_date = df.index[-1].date()
    _dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    _mes = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    last_lbl = f"{_dias[last_date.weekday()]} {last_date.day} {_mes[last_date.month-1]}"
    stale_days = (dt.date.today() - last_date).days
    # ¿el ultimo dato es de MEDIA SEMANA? (el sistema decide con el cierre del VIERNES; lo demas es observacion)
    _hoy_wd = dt.date.today().weekday()   # 0=lun ... 4=vie
    media_semana = _hoy_wd < 4            # lun-jue = todavia no ha cerrado la semana
    src_summary = ", ".join(sorted(set(v for v in sources.values() if v not in ("—",))))

    # ranking enriquecido (sparkline RS + rendimiento relativo 4 semanas)
    def spark_svg(vals, color):
        if not vals or len(vals) < 2:
            return ""
        w, h = 78, 22
        lo, hi = min(vals), max(vals)
        rng = (hi - lo) or 1e-9
        pts = " ".join(f"{w*i/(len(vals)-1):.1f},{h-2-(h-4)*(v-lo)/rng:.1f}" for i, v in enumerate(vals))
        return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
                f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.5" '
                f'stroke-linejoin="round" stroke-linecap="round"/></svg>')

    def _rk_row(sym, d):
        c = QUAD[d["quad"]][1]
        rcol = "#2FD08A" if d["rel4"] >= 0 else "#F4607A"
        rarrow = "+" if d["rel4"] >= 0 else ""
        veh = LEV3X.get(sym, "—")
        veh_html = f"<span class='veh3'>{veh}</span>" if veh and veh != "—" else "<span class='veh3 off'>—</span>"
        return (
            f'<tr><td class="tk" title="{esc(sym)} · {esc(NAMES.get(sym,("","",""))[1])}"><b>{sym}</b><em>{esc(NAMES.get(sym,("","",""))[1])}</em></td>'
            f'<td><span class="dot" style="background:{c}"></span>{QUAD[d["quad"]][0]}</td>'
            f'<td class="r">{d["ratio"]:.1f}</td><td class="r">{d["mom"]:.1f}</td>'
            f'<td class="r" style="color:{rcol}">{rarrow}{d["rel4"]:.1f}%</td>'
            f'<td>{veh_html}</td>'
            f'<td class="spk">{spark_svg(d["spark"], c)}</td></tr>')
    rows = []
    for g in GRUPO_ORDEN:
        grp = [(sym, d) for sym, d in ranked if GRUPO.get(sym) == g]
        if not grp:
            continue
        rows.append(f'<tr><td class="rk-grp" colspan="7">{GRUPO_NOMBRE.get(g, g)}</td></tr>')
        for sym, d in grp:
            rows.append(_rk_row(sym, d))
    table = ('<table><tr><th>Activo</th><th>Cuadrante</th><th class="r">Fuerza</th>'
             '<th class="r">Impulso</th><th class="r">vs idx 4s</th><th>x3</th><th>Tendencia RS</th></tr>'
             + "".join(rows) + "</table>")

    # alertas
    if alerts:
        al = "".join(f'<div class="alert a-{k}"><span class="atk">{s}</span><span class="atx">{esc(t)}</span></div>'
                     for s, k, t in alerts)
    else:
        al = '<div class="note">Sin giros relevantes en la ultima lectura. El liderazgo se mantiene estable.</div>'

    # barras de impulso
    mom_sorted = sorted(rrg.items(), key=lambda kv: -kv[1]["mom"])
    maxabs = max([6.0] + [abs(d["mom"] - 100) for _, d in mom_sorted])
    bars = []
    for sym, d in mom_sorted:
        v = d["mom"] - 100
        pct = abs(v) / maxabs * 50
        c = QUAD[d["quad"]][1]
        left = 50 if v >= 0 else 50 - pct
        bars.append(f'<div class="bar-row"><span class="bar-lab">{sym}</span>'
                    f'<div class="bar-track"><div class="bar-mid"></div>'
                    f'<div class="bar" style="background:{c};width:{pct:.1f}%;left:{left:.1f}%"></div></div>'
                    f'<span class="bar-val" style="color:{c}">{d["mom"]:.1f}</span></div>')

    def meter(label, val, good=50):
        col = "#2FD08A" if val >= good else "#F4B740" if val >= good - 15 else "#F4607A"
        return (f'<div class="meter"><div class="meter-top"><span>{label}</span><b style="color:{col}">{val}%</b></div>'
                f'<div class="meter-track"><div class="meter-fill" style="width:{val}%;background:{col}"></div></div></div>')

    # macro
    sig_rows = "".join(f'<div class="kv"><span>{esc(k)}</span><b>{("+" if (v is not None and v>=0) else "")}{v if v is not None else "n/d"}{"%" if k!="Apetito riesgo" and v is not None else ""}</b></div>'
                       for k, v in regime["sig"].items())
    favor = "".join(f'<span class="tag good">{s}</span>' for s in regime["favor"])
    hurt = "".join(f'<span class="tag bad">{s}</span>' for s in regime["hurt"])
    buy_t = "".join(f'<span class="tag good">{s}</span>' for s in buy) or '<em style="color:#5E708A">Ninguno ahora.</em>'
    avoid_t = "".join(f'<span class="tag bad">{s}</span>' for s in avoid) or '<em style="color:#5E708A">Ninguno ahora.</em>'

    fred_html = ""
    if fred:
        fr = "".join(f'<div class="kv"><span>{esc(k)}</span><b>{v["last"]} ({"+" if v["chg"]>=0 else ""}{v["chg"]} 13s)</b></div>'
                     for k, v in fred.items())
        fred_html = f'<div class="panel"><h2>Macro FRED (13 semanas)</h2>{fr}</div>'

    risk_cls = risk["label"].replace("-", "")

    html = []
    html.append("<!DOCTYPE html><html lang='es'><head><meta charset='utf-8'>")
    html.append("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    html.append("<title>Rotacion - Smart-Money Flow Terminal</title>")
    html.append("<meta name='theme-color' content='#0A0E17'>")
    html.append("<link rel='manifest' href='manifest.webmanifest'>")
    html.append("<meta name='apple-mobile-web-app-capable' content='yes'>")
    html.append("<meta name='mobile-web-app-capable' content='yes'>")
    html.append("<meta name='apple-mobile-web-app-status-bar-style' content='black-translucent'>")
    html.append("<meta name='apple-mobile-web-app-title' content='Rotacion'>")
    html.append("<link rel='apple-touch-icon' href='icons/apple-touch-icon.png'>")
    html.append("<link rel='icon' href='icons/icon-192.png'>")
    html.append("<style>" + CSS + "</style></head><body>")
    html.append(
        "<header><div class='brand'><div><div class='title'>ROTACION</div>"
        "<div class='sub'>Smart-Money Flow Terminal</div></div></div>"
        f"<div class='status'><span class='pill RiskON' style='background:rgba(47,208,138,.12);color:#2FD08A'>DATOS REALES</span>"
        f"<span><b>Fuente</b>{esc(src_summary)}</span>"
        f"<span><b>Referencia</b>{BENCH}</span>"
        f"<span><b>Activos</b>{len(rrg)}</span>"
        f"<span><b>Ult. cierre</b>{last_lbl}</span>"
        + (f"<span class='pill' style='background:rgba(244,183,64,.15);color:#F4B740'>⚠ datos {stale_days}d atrás</span>" if stale_days >= 5 else "")
        + f"<span class='pill {risk_cls}'>{risk['label']}</span></div></header>")

    html.append("<main>")
    html.append(
        "<div class='viewtabs' style='grid-column:1/-1;position:sticky;top:0;z-index:60;background:var(--bg);padding:8px 0 6px;margin:-4px 0 6px;border-bottom:1px solid var(--line)'>"
        "<button class='viewtab mainview active' onclick=\"mainView('ctx',this)\" style='font-size:13px;padding:7px 16px'>📊 Contexto</button>"
        "<button class='viewtab mainview' onclick=\"mainView('op',this)\" style='font-size:13px;padding:7px 16px'>🎯 Operativa</button>"
        "<button class='viewtab mainview' onclick=\"mainView('vig',this)\" style='font-size:13px;padding:7px 16px'>📋 Vigilancia</button>"
        "<button class='viewtab mainview' onclick=\"mainView('bbg',this)\" style='font-size:13px;padding:7px 16px;border-color:#FFB00055;color:#FFB000'>🖥️ PRO</button>"
        "<button class='viewtab mainview' onclick=\"mainView('rds',this)\" style='font-size:13px;padding:7px 16px;border-color:#4CC2E055;color:#4CC2E0'>📣 Redes</button>"
        "<button class='viewtab mainview' onclick=\"mainView('cl',this)\" style='font-size:13px;padding:7px 16px'>🤖 Modo Claude</button>"
        "<span style='flex:1'></span>"
        "<button class='viewtab' onclick='descargarPDF()' title='Resumen semanal en PDF (imprimible / para Substack)' style='font-size:12px;padding:7px 12px;border-color:#5B8CFF55;color:#5B8CFF'>📄 Resumen PDF</button>"
        "<button class='viewtab' onclick='descargarJPG()' title='Resumen semanal en JPG (para X / Telegram; necesita internet)' style='font-size:12px;padding:7px 12px;border-color:#5B8CFF33'>🖼 JPG</button>"
        "</div>"
        "<div id='vista-ctx' style='display:contents'>")

    # ---- barra-resumen de rotacion ----
    entering = [s for s, d in rrg.items() if d["quad"] == "improving"]
    leaving = [s for s, d in rrg.items() if d["quad"] == "weakening"]
    leadnow = [s for s, d in rrg.items() if d["quad"] == "leading"]
    flow_col = "#2FD08A" if risk["score"] > 1.5 else "#F4607A" if risk["score"] < -1.5 else "#93A4BC"
    def scard(lab, big, big_col, sm):
        return (f"<div class='scard'><div class='lab'>{lab}</div>"
                f"<div class='big' style='color:{big_col}'>{big}</div><div class='sm'>{sm}</div></div>")
    html.append("<div class='summary full'>"
                + scard("Sesgo de flujo", risk["label"], flow_col, f"{'+' if risk['score']>=0 else ''}{risk['score']} ciclicos vs defensivos")
                + scard("Entrando a liderazgo", str(len(entering)), "#4CC2E0", (", ".join(entering[:4]) or "—"))
                + scard("Perdiendo liderazgo", str(len(leaving)), "#F4B740", (", ".join(leaving[:4]) or "—"))
                + scard("Regimen macro", regime["label"].split(" / ")[0], "#5B8CFF", f"{len(leadnow)} sectores liderando")
                + "</div>")
    verdict_pos = len(html)                       # aqui se insertara el "Veredicto de hoy" (se construye mas abajo)
    # ---- RELOJ DEL CICLO ECONOMICO ----
    try:
        cyc = compute_cycle_phase(rrg, scores or [])
        cur = cyc.get("actual")
        if cur:
            lit_txt = ", ".join(cur["lit"]) if cur["lit"] else "—"
            html.append("<div class='panel full'><h2>🕒 Reloj del ciclo económico — ¿en qué punto estamos?</h2>"
                        "<div class='note'>Dónde está el dinero hoy, traducido al ciclo económico (modelo de rotación sectorial de Fidelity/Stovall). "
                        "La aguja marca la fase cuyos sectores están <b>recibiendo dinero ahora</b> (en Líder o Mejorando). El ciclo gira en el sentido del reloj: "
                        "Recuperación → Expansión → Sobrecalentamiento → Recesión → y vuelta a empezar.</div>"
                        + cycle_clock_html(cyc)
                        + f"<div style='text-align:center;margin-top:6px'><b style='color:{cur['col']};font-size:15px'>{cur['lbl']}</b> "
                          f"<span style='color:#9FB0C8'>· {cur['sub']}</span></div>"
                        + f"<div class='note' style='margin-top:8px'>{cur['desc']}<br>"
                          f"<b>Con dinero entrando ahora ({cur['n']}/{cur['tot']}):</b> <span style='color:{cur['col']}'>{lit_txt}</span></div>"
                        "<div class='note' style='margin-top:8px;color:#5E708A'>⚠ Los ciclos son <b>lentos</b> (cada fase dura 1-4 años) y en tiempo real son <b>confusos</b> — "
                        "distinguir mitad de ciclo de final de ciclo es justo donde más se equivoca todo el mundo. Es un <b>mapa orientativo, no una predicción</b>, "
                        "y va con la rotación del mercado, no con el calendario. El flujo manda. No es asesoramiento.</div></div>")
    except Exception:
        pass
    # ---- RADAR DE ATENCION (ruido vs silencio) ----
    try:
        radar = compute_attention_radar(rrg, flow)
        if radar:
            gems = [r for r in radar if r["rank"] == 0]
            shown = [r for r in radar if r["rank"] <= 2][:14]
            rrows = ""
            for r in shown:
                nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
                vr = r["vol_rel"]
                vrtxt = (f"{vr:.2f}×" if vr is not None else "n/d")
                cuad = QUAD.get(r["quad"], (r["quad"], ""))[0]
                rrows += (f"<tr><td class='se-l'><b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span></td>"
                          f"<td class='r' style='font-size:11px'>{esc(cuad)}</td>"
                          f"<td class='r' style='white-space:nowrap'>{esc(r['ruido'])} <span style='color:#5E708A;font-size:10px'>{vrtxt}</span></td>"
                          f"<td class='r' style='color:{r['vcol']};white-space:nowrap;font-size:11px'>{esc(r['vd'])}</td></tr>")
            gem_line = ", ".join(f"<b>{r['sym']}</b>" for r in gems) if gems else "ninguna clara hoy"
            html.append("<div class='panel full'><h2>📡 Radar de atención — ¿quién sube en silencio?</h2>"
                        "<div class='note'>Tu idea: lo que sube <b>sin ruido</b> suele ser mejor que lo que está en boca de todos (semis, «picos y palas»…). "
                        "Cruzo la <b>tendencia</b> (RRG) con el <b>volumen relativo</b> (volumen medio de 5 sesiones vs su media de 20) como medida de atención. "
                        "Sube con volumen <b>normal/bajo</b> = aún no se ha enterado nadie (🤫 joya escondida). Sube con volumen <b>disparado</b> = ya está la masa dentro (📢 masificado, ojo al techo).</div>"
                        + (f"<div class='note' style='margin-top:6px;color:#2FD08A'>🤫 <b>Subiendo en silencio ahora:</b> {gem_line}</div>")
                        + "<div class='scrollx'><table class='se'><tr><th class='se-l'>sector / tema</th><th class='r'>cuadrante</th><th class='r'>ruido (vol.)</th><th class='r'>veredicto</th></tr>"
                        + rrows + "</table></div>"
                        "<div class='note' style='margin-top:8px;color:#5E708A'>⚠ El volumen es proxy de atención del <b>mercado</b>, no de la prensa — casi siempre coinciden, pero no es idéntico. "
                        "Y poco volumen no garantiza subida: dice que aún no está masificado, no que vaya a subir. Cruza con su flujo y su gráfico. No es asesoramiento.</div></div>")
    except Exception:
        pass
    # ---- 😴 DURMIENTES: suelo + silencio + giro + contraria 0/3, TODO EN UN PANEL ----
    suelo = None
    contra_sigs, contra_led = [], None
    try:
        suelo = compute_suelo(df, rrg, scores, flow, meanrev)
    except Exception:
        suelo = None
    if CONTRARIAN_ON:
        try:
            contra_sigs = compute_contrarian(rrg, scores, flow)
            _px = {k: float(v) for k, v in df.iloc[-1].to_dict().items() if v == v}
            contra_led = update_contrarian_ledger(contra_sigs, _px, str(df.index[-1].date()), df)
        except Exception:
            contra_sigs, contra_led = [], None
    try:
        stats = (contra_led or {}).get("stats")
        if stats and stats["n"] >= 20 and stats.get("kelly4") is not None:
            size_pct = min(stats["kelly4"], 3.0)
            size_src = f"¼ de Kelly empírico con tus {stats['n']} señales fuera-de-muestra"
        else:
            size_pct = CONTRARIAN_SIZE_PCT
            size_src = "tamaño de prueba fijo hasta acumular ≥20 señales fuera-de-muestra"
        if suelo:
            _c_act = {c["sym"] for c in (contra_sigs or [])}
            sfilas = ""
            for r in suelo:
                nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
                if r["sangra"]:
                    verd, vcol = "⚠ aún sangra — sin prisa", "#F4607A"
                elif r["despertando"] and r["sil"] >= 2:
                    verd, vcol = "🌅 DESPERTANDO EN SILENCIO", "#2FD08A"
                elif r["despertando"]:
                    verd, vcol = "🌅 despertando", "#2FD08A"
                elif r["pts"] >= 8:
                    verd, vcol = "suelo armado — falta el giro", "#F4B740"
                else:
                    verd, vcol = "dormido — vigilar", "#9FB0C8"
                scol = "#2FD08A" if r["pts"] >= 8 else "#F4B740" if r["pts"] >= 6 else "#9FB0C8"
                cbadge = (" <span style='color:#7BD88F;font-size:10px;border:1px solid #7BD88F55;border-radius:4px;padding:1px 4px' "
                          "title='dispara HOY la señal contraria 0/3: tamaño de manga abajo'>0/3 ACTIVA</span>"
                          if r["sym"] in _c_act else "")
                hia = f"−{100 - r['hi52']:.0f}%" if r["hi52"] is not None else "—"
                _silc = "#2FD08A" if r["sil"] >= 3 else "#F4B740" if r["sil"] == 2 else "#9FB0C8"
                sila = (f"<span style='color:{_silc}'>{'🤫' * max(r['sil'], 0)}</span> {r['vr']:.2f}×" if r["vr"] is not None else "—")
                gira = (f"<b style='color:#7BD88F'>{r['vert']:.1f}×</b>" if (r.get("vert") and r["dmom"] and r["dmom"] >= 1.5)
                        else (f"{r['dmom']:+.1f}" if r.get("dmom") is not None else "—"))
                qta = (f"{r['quieto']:+.1f}%" if r.get("quieto") is not None else "—")
                fla = ("<span style='color:#2FD08A'>entra</span>" if (r["cmf"] or 0) > 0.05 else
                       "<span style='color:#F4607A'>sale</span>" if (r["cmf"] or 0) < -0.05 else
                       "<span style='color:#9FB0C8'>plano</span>") if r["cmf"] is not None else "—"
                n3a = ("<b style='color:#7BD88F'>0/3</b>" if r["n3"] == 0 else f"{r['n3']}/3" if r["n3"] is not None else "—")
                # marca de sector EXPLOSIVO: los que al rebotar se mueven mas (donde tener liquidez lista)
                expl = ""
                if r["sym"] in SECTORES_EXPLOSIVOS:
                    _et = EXPLOSIVO_TIPO.get(r["sym"], "")
                    expl = (f" <span style='color:#FF8C42;font-size:9px;border:1px solid #FF8C4255;border-radius:3px;padding:0 4px;white-space:nowrap' "
                            f"title='Sector de beta alta: cuando rebota, se mueve mucho más que el mercado. Aquí es donde conviene tener liquidez preparada para entrar en el giro.'>💥 {esc(_et)}</span>")
                sfilas += (f"<tr><td class='se-l'><b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span>{cbadge}{expl}</td>"
                           f"<td class='r'><b style='color:{scol};font-size:14px'>{r['pts']}</b><span style='color:#5E708A;font-size:10px'>/10</span></td>"
                           f"<td class='r'>{hia}</td>"
                           f"<td class='r' style='white-space:nowrap'>{sila}</td>"
                           f"<td class='r'>{r['wk_lag'] or '—'}</td>"
                           f"<td class='r'>{n3a}</td>"
                           f"<td class='r'>{gira}</td>"
                           f"<td class='r' style='color:#9FB0C8'>{qta}</td>"
                           f"<td class='r' style='font-size:11px'>{fla}</td>"
                           f"<td class='r' style='color:{vcol};font-size:11px;white-space:nowrap'>{verd}</td></tr>")
            crows = ""
            for s2 in (contra_sigs or []):
                crows += (f"<tr><td class='se-l'><b>{s2['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(NAMES.get(s2['sym'], (s2['sym'], s2['sym'], ''))[1])}</span></td>"
                          f"<td class='r' style='color:#7BD88F;font-weight:700'>{s2['n3']}/3</td>"
                          f"<td class='r'>{s2['vert']:.1f}×</td>"
                          f"<td class='r' style='color:#5B8CFF;font-weight:700'>{size_pct:.1f}%</td></tr>")
            if stats:
                oos = (f"<b style='color:{'#2FD08A' if stats['winrate'] >= 55 else '#F4B740'}'>{stats['winrate']}% de acierto</b> "
                       f"en <b>{stats['n']}</b> señales fuera-de-muestra · media {stats['avg']:+.2f}% a {CONTRARIAN_HORIZON_W} sem")
            else:
                oos = f"aún sin señales maduras — cada una se evalúa sola a las {CONTRARIAN_HORIZON_W} semanas"
            # resumen del MODO CAZADOR DE SUELOS EXPLOSIVOS: cuantos de alta beta estan en zona de suelo
            _expl_suelo = [r for r in suelo if r["sym"] in SECTORES_EXPLOSIVOS]
            _expl_despierta = [r for r in _expl_suelo if r.get("despertando") and not r["sangra"]]
            _expl_sangra = [r for r in _expl_suelo if r["sangra"]]
            cazador = ""
            if _expl_suelo:
                if _expl_despierta:
                    _lst = ", ".join(f"<b style='color:#2FD08A'>{r['sym']}</b> ({EXPLOSIVO_TIPO.get(r['sym'],'')})" for r in _expl_despierta[:5])
                    cazador = (f"<div style='margin-bottom:12px;padding:10px 12px;background:rgba(47,208,138,.08);border:1px solid #2FD08A44;border-radius:8px'>"
                               f"<div style='font-size:12px;color:#2FD08A;font-weight:700;margin-bottom:4px'>🎯 CAZADOR DE SUELOS — {len(_expl_despierta)} sector(es) explosivo(s) DESPERTANDO</div>"
                               f"<div style='font-size:12px;color:#DCE6F5'>{_lst}</div>"
                               "<div style='font-size:10.5px;color:#8FA3C0;margin-top:5px'>Estos son de <b>beta alta</b> (rebotan fuerte) y están dejando de sangrar tras la caída. "
                               "Es la señal para <b>tener la liquidez lista</b> y, si el viernes lo confirma con flujo, entrar en el giro buscando el suelo. "
                               "No persigas: espera el cierre.</div></div>")
                elif _expl_sangra:
                    _lst = ", ".join(f"{r['sym']}" for r in _expl_sangra[:6])
                    cazador = (f"<div style='margin-bottom:12px;padding:10px 12px;background:rgba(244,96,122,.06);border:1px solid #F4607A33;border-radius:8px'>"
                               f"<div style='font-size:12px;color:#F4B740;font-weight:700;margin-bottom:4px'>🎯 CAZADOR DE SUELOS — {len(_expl_sangra)} explosivo(s) cayendo, AÚN SANGRAN</div>"
                               f"<div style='font-size:11.5px;color:#9FB0C8'>{_lst} — castigados pero el dinero todavía sale. <b>Liquidez quieta, sin prisa.</b> "
                               "El suelo se caza cuando el flujo deja de salir, no cuando el precio está barato.</div></div>")

            html.append("<div class='panel full'><h2>😴 DURMIENTES — suelo + silencio + giro, el radar de anticipación</h2>"
                        + cazador +
                        "<div class='note'>Todo lo que antes estaba repartido en tres paneles (detector de suelo, radar de giro vertical y señal contraria 0/3), unido y con el "
                        "<b>SILENCIO potenciado</b>: el patrón que buscas es el de tu China — machacado, del que <b>nadie habla</b> (volumen bajísimo, 🤫🤫🤫), "
                        "con el impulso girando en vertical <b>mientras el precio apenas se ha movido todavía</b>. Esa combinación es la anticipación: "
                        "cuando el precio confirme y el volumen llegue, la etiqueta pasará de 🌅 a líder y ya será tarde para entrar barato. "
                        "La marca <span style='color:#FF8C42'>💥</span> señala los sectores <b>explosivos</b> (beta alta): donde el rebote es más salvaje y conviene tener liquidez lista. "
                        "El veredicto manda: <b>🌅 DESPERTANDO EN SILENCIO</b> = todos los ingredientes; <b>⚠ aún sangra</b> = ni tocar, da igual lo barato.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'>sector / tema</th><th class='r'>😴</th>"
                        "<th class='r'>vs máx 52s</th><th class='r'>silencio</th><th class='r'>sem. dorm.</th>"
                        "<th class='r'>estruct.</th><th class='r'>giro</th><th class='r'>precio 4s</th><th class='r'>flujo</th><th class='r'>veredicto</th></tr>"
                        + sfilas + "</table></div>"
                        + ("<div style='margin-top:10px;padding:8px 10px;background:rgba(123,216,143,.06);border:1px solid #7BD88F33;border-radius:8px'>"
                           "<span style='font-size:11px;color:#7BD88F;font-weight:700'>SEÑAL CONTRARIA 0/3 DE ESTA SEMANA</span> "
                           "<span style='color:#8FA3C0;font-size:11px'>(la manga aparte: tamaño pequeño, nunca apalancados, se registra y se evalúa sola a 4 semanas)</span>"
                           "<table class='se' style='margin-top:6px'><tr><th class='se-l'>señal</th><th class='r'>estruct.</th><th class='r'>verticalidad</th><th class='r'>tamaño</th></tr>"
                           + crows + "</table></div>" if crows else
                           "<div class='note' style='margin-top:8px;color:#5E708A'>Sin señal contraria 0/3 válida esta semana — la paciencia también es una posición.</div>")
                        + f"<div class='note' style='margin-top:8px'><b>Ledger fuera-de-muestra</b>: {oos}. Tamaño: {size_src}. "
                        f"Guardado en <code>senales_contrarias.json</code>. Regla de siempre: esto <b>observa</b> entre semana y se <b>ejecuta</b> con el cierre del viernes, "
                        "con flujo que como mínimo haya dejado de salir. El flujo confirma, no predice — también aquí. No es asesoramiento.</div></div>")
    except Exception:
        pass
    # ---- PLAN DE LIQUIDEZ + CAIDAS DEL S&P 500 (fusionado) ----
    if plan or dd:
        left = ""
        if plan:
            ddc = "#F4607A" if plan["dd"] <= -5 else "#F4B740" if plan["dd"] <= -2 else "#2FD08A"
            idx_name = "S&amp;P 500" if "SP" in long_src.upper() or long_src in ("^SPX", "^GSPC") else long_src or "S&amp;P 500"
            rungs_html = ""
            for r in plan["rungs"]:
                veh = LEV3X.get("QQQ", "TQQQ")
                stt = ("<span style='color:#2FD08A'>ALCANZADA</span>" if r["hit"]
                       else f"<span style='color:#5E708A'>faltan {(r['thr'] + plan['dd']):.1f}%</span>")
                bcol = "#2FD08A" if r["hit"] else "#1E2A3D"
                rungs_html += (f"<div class='rung' style='border-left-color:{bcol}'>"
                               f"<span class='rk-thr'>−{r['thr']}%</span>"
                               f"<span class='rk-lvl'>{idx_name} ≤ {r['level']}</span>"
                               f"<span class='rk-pct'>desplegar {r['pct']}%</span>"
                               f"<span class='rk-veh'>{veh}</span>"
                               f"<span class='rk-st'>{stt}</span></div>")
            left = (f"<div class='dd-now'><div class='lab'>Caida actual del {idx_name} desde maximos</div>"
                    f"<div class='dd-big' style='color:{ddc}'>{plan['dd']:.1f}%</div>"
                    f"<div class='sm'>Maximo {plan['peak']} · ahora {plan['last']} · fuente {long_src}</div></div>"
                    + rungs_html)
        right = ""
        if dd:
            rows = ""
            for t in DD_THRESHOLDS:
                e = dd[t]
                ytdcol = "#F4B740" if e["ytd"] > 0 else "#5E708A"
                restcol = "#2FD08A" if e["rest"] >= 50 else "#F4B740" if e["rest"] >= 20 else "#9FB0C8"
                rows += (f"<tr><td class='r' style='color:#E6EDF6'>−{t:g}%</td>"
                         f"<td class='r'>{e['avg20']}</td><td class='r'>{e['avgfull']}</td>"
                         f"<td class='r' style='color:#5B8CFF'>{e['probfull']}%</td>"
                         f"<td class='r' style='color:{restcol}'>{e['rest']}%</td>"
                         f"<td class='r' style='color:{ytdcol}'>{e['ytd']}</td></tr>")
            meta = dd_meta or {}
            right = ("<table><tr><th>Caida</th><th class='r'>media/año<br>20a</th>"
                     "<th class='r'>media/año<br>histórico</th><th class='r'>prob. en<br>un año</th>"
                     "<th class='r'>prob. resto<br>del año</th>"
                     "<th class='r'>ya este<br>año</th></tr>" + rows + "</table>"
                     f"<div class='note' style='margin-top:6px'>Histórico {meta.get('start','?')}–{meta.get('end','?')} "
                     f"({long_src}, <b>{meta.get('basis','cierre')}</b>). «Prob. en un año» = % de años con al menos una caída de ese tamaño. "
                     "«Prob. resto del año» = % de años en que ocurrió una caída así <b>entre la fecha de hoy y fin de año</b>. "
                     "«Media/año» = nº de caídas de ese tamaño por año (un evento se cierra al recuperar la mitad). "
                     + ("<b>Intradía</b>: cuenta cuando el índice <b>tocó</b> ese nivel en algún momento del día (ahí suele haber compras y rebote), aunque cerrara más arriba."
                        if meta.get('basis') == 'intradía' else
                        "Medido sobre precios de <b>cierre</b>.")
                     + " <b>Método:</b> caída desde el <b>pico de las últimas 52 semanas</b> (pico reciente, como una corrección normal). "
                       "Los cubos grandes (<b>−10%</b> y <b>−20%</b>) saltan a partir de <b>−9.5%</b> y <b>−19.5%</b>: el SPY solo "
                       "registra su sesión de contado, pero el futuro/CFD del S&amp;P cotiza casi 24h, así que una caída que tocó el −10% "
                       "de madrugada puede quedar en ~−9.5% en el dato del SPY. Ese medio punto capta ese hueco nocturno. "
                       "Consenso de mercado: un <b>−10%</b> ocurre ≈<b>1 vez/año</b>, un <b>−5%</b> ≈<b>3 veces/año</b> y un <b>−20%</b> "
                       "≈<b>1 vez cada 5-6 años</b> (13 desde 1950). Son frecuencias históricas, no predicción.</div>")
        html.append("<div class='panel full'><h2>Plan de liquidez y caídas del S&amp;P 500</h2>"
                    "<div class='note'>Guía de entrada escalonada según la caída del S&amp;P desde máximos, junto a la "
                    "frecuencia histórica de caídas. Los porcentajes de despliegue se editan arriba del archivo (CASH_PLAN).</div>"
                    "<div class='planwrap'><div class='planladder'>" + left + "</div>"
                    "<div class='planstats'>" + right + "</div></div>"
                    "<div class='note' style='margin-top:8px;color:#F4607A'>⚠ Los productos apalancados x3 (TQQQ y similares) se reajustan "
                    "a diario, sufren desgaste por volatilidad y pueden caer mucho más que el índice (TQQQ perdió ~80% en 2022). "
                    "No son para mantener en mercados laterales. El mercado puede seguir cayendo más allá del −20%. No es asesoramiento.</div></div>")

    # ---- LECTURA DEL MERCADO Y PROBABILIDADES (fusion de todo) ----
    # defaults incondicionales: el veredicto (stance/light/bull) SIEMPRE debe poder pintarse,
    # aunque scores o probs falten en un build degradado.
    try:
        _spyd = df[BENCH].dropna()
        bull = bool(_spyd.iloc[-1] > _spyd.rolling(min(40, len(_spyd)), min_periods=10).mean().iloc[-1])
    except Exception:
        bull = True
    if bull:
        light, stance = "#F4B740", "ÁMBAR — mercado alcista, sin datos de puntuación suficientes esta semana."
    else:
        light, stance = "#F4607A", "ROJO — el S&P está por debajo de su media de 40 semanas: prudencia."
    if scores and probs:
        spy = df[BENCH]
        bull = bool(spy.iloc[-1] > spy.rolling(min(40, len(spy))).mean().iloc[-1])
        st = probs["stats"]; fwd = probs["fwd"]
        lite = lambda r: sum(1 for _, v in r["parts"][:3] if v)
        buy = [r for r in scores if r["score"] >= 4]
        n_buy = len(buy)
        if not bull:
            light, stance = "#F4607A", "ROJO — el S&P está por debajo de su media de 40 semanas: el filtro de tendencia recomienda prudencia (liquidez o defensivos)."
        elif n_buy >= 5:
            light, stance = "#2FD08A", "VERDE — mercado alcista y varias oportunidades de alta puntuación: entorno favorable para invertir, siendo selectivo."
        elif n_buy >= 2:
            light, stance = "#F4B740", "ÁMBAR-VERDE — mercado alcista pero selectivo: hay oportunidades, aunque pocas y concentradas."
        else:
            light, stance = "#F4B740", "ÁMBAR — mercado alcista pero sin señales fuertes claras esta semana: mejor paciencia."
        read = (f"Régimen <b>{esc(regime['label'])}</b>, apetito de riesgo <b>{esc(risk['label'])}</b>, "
                f"tendencia del mercado <b>{'alcista' if bull else 'bajista'}</b>. "
                f"<b>{n_buy}</b> ETF con puntuación de compra (4–5/5) esta semana.")
        # tabla de probabilidades base (historica)
        prob_rows = ""
        for sc in [3, 2, 1, 0]:
            d = st.get(sc, {})
            if d.get("pup") is None:
                continue
            pcol = "#2FD08A" if d["pup"] >= 60 else "#F4B740" if d["pup"] >= 50 else "#F4607A"
            acol = "#2FD08A" if d["avg"] >= 0 else "#F4607A"
            prob_rows += (f"<tr><td class='pb-l'><b>{sc}/3</b> señales estructurales</td>"
                          f"<td class='pb-v' style='color:{pcol}'>{d['pup']}%</td>"
                          f"<td class='pb-v' style='color:{acol}'>{d['avg']:+.1f}%</td>"
                          f"<td class='pb-n'>{d['n']} casos</td></tr>")
        # candidatos listos con motivos + probabilidad
        cand = ""
        for r in buy[:8]:
            ls = lite(r); bd = st.get(ls, {})
            reasons = ", ".join(name for name, v in r["parts"] if v)
            prob_txt = (f"<b style='color:{'#2FD08A' if bd['pup']>=55 else '#F4B740'}'>{bd['pup']}%</b> histórico de subir en {fwd} sem (media {bd['avg']:+.1f}%)"
                        if bd.get("pup") is not None else "—")
            nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
            acc = " <span class='sc-acc'>⚡</span>" if r["obv_cross"] else ""
            cand += (f"<div class='cand'><div class='cand-h'><b>{r['sym']}</b> <span>{esc(nm)}</span>"
                     f"<span class='cand-sc' style='color:{'#2FD08A' if r['score']>=4 else '#F4B740'}'>{r['score']}/5</span>{acc}</div>"
                     f"<div class='cand-r'>Listo para la semana que viene porque: {esc(reasons)}.</div>"
                     f"<div class='cand-p'>Probabilidad: {prob_txt}.</div></div>")
        # ---- FEAR & GREED de CNN (sentimiento contrario) ----
        if fg_idx:
            sc = fg_idx["score"]
            if sc < 25:
                zona, col = "Miedo extremo", "#F4607A"
            elif sc < 45:
                zona, col = "Miedo", "#F4824A"
            elif sc <= 55:
                zona, col = "Neutral", "#F4B740"
            elif sc <= 74:
                zona, col = "Codicia", "#7FC97F"
            else:
                zona, col = "Codicia extrema", "#2FD08A"
            if sc >= 75:
                lect = "Sentimiento eufórico — históricamente <b>peor</b> momento para añadir riesgo. Encaja con tu pólvora seca: cautela."
            elif sc < 25:
                lect = "Pánico — históricamente de las <b>mejores</b> ventanas de entrada (pero no es señal de timing: puede caer más). Es cuando tu plan de liquidez entra en juego."
            else:
                lect = "Sentimiento intermedio, sin extremo contrario claro."
            def _fgchip(lbl, v):
                return f"<span class='fgchip'>{lbl}: <b>{v if v is not None else '—'}</b></span>"
            html.append("<div class='panel full'><h2>Fear &amp; Greed (CNN)</h2>"
                        f"<div class='fgwrap'><div class='fgnum' style='color:{col}'>{sc}<span>/100</span></div>"
                        f"<div class='fgzone' style='color:{col}'>{esc(zona)}</div></div>"
                        f"<div class='fgbar'><div class='fgmark' style='left:{sc}%'></div></div>"
                        f"<div class='fgctx'>{_fgchip('ayer', fg_idx['prev'])}{_fgchip('hace 1 sem', fg_idx['week'])}"
                        f"{_fgchip('hace 1 mes', fg_idx['month'])}{_fgchip('hace 1 año', fg_idx['year'])}</div>"
                        f"<div class='note'>{lect} Es un indicador <b>contrario</b>: mide la emoción del mercado "
                        "(0 = pánico, 100 = euforia), no su dirección. Fuente: CNN. No es asesoramiento.</div></div>")
        else:
            html.append("<div class='panel full'><h2>Fear &amp; Greed (CNN)</h2>"
                        "<div class='note'>⚠ <b>F&amp;G no disponible</b> ahora mismo: CNN no ha devuelto el dato "
                        "(puede ser un fallo temporal de su servidor o de red). El resto del panel no se ve afectado; "
                        "vuelve a ejecutar más tarde y reaparecerá. No es asesoramiento.</div></div>")

        # ===== TERMOMETRO DEL MERCADO — SPY (entra o sale dinero) =====
        try:
            if spy_flow:
                sf = spy_flow
                spy = df[BENCH].dropna()
                sma40 = spy.rolling(40).mean()
                trend_up = bool(spy.iloc[-1] > sma40.iloc[-1]) if sma40.notna().any() else None
                mom3 = ((spy.iloc[-1] / spy.iloc[-14] - 1) * 100) if len(spy) > 14 else None
                obv_ok = bool(sf.get("obv_above")); cmf = sf.get("cmf", 0.0) or 0.0
                cmf_pos = bool(sf.get("cmf_pos")); diverg = bool(sf.get("diverg"))
                if diverg:
                    verd, vcol = "⚠ Distribución oculta: el precio sube pero el dinero SALE", "#F4607A"
                elif obv_ok and cmf_pos:
                    verd, vcol = "Dinero ENTRANDO en el mercado (acumulación)", "#2FD08A"
                elif (not obv_ok) and cmf < 0:
                    verd, vcol = "Dinero SALIENDO del mercado (distribución)", "#F4607A"
                else:
                    verd, vcol = "Flujo mixto / sin señal clara", "#F4B740"
                def _yn(b, t, f):
                    return (f"<b style='color:#2FD08A'>{t}</b>" if b else f"<b style='color:#F4607A'>{f}</b>")
                obv_txt = _yn(obv_ok, "por encima de su media (acumula)", "por debajo (distribuye)")
                cmf_col = "#2FD08A" if cmf > 0 else "#F4607A"
                cmf_txt = f"<span style='color:{cmf_col}'>{cmf:+.3f} ({'compra' if cmf > 0 else 'venta'})</span>"
                div_txt = "⚠ <b style='color:#F4607A'>sí</b>" if diverg else "<span style='color:#2FD08A'>no</span>"
                rows = (f"<tr><td class='se-l'>OBV (volumen acumulado)</td><td class='r'>{obv_txt}</td></tr>"
                        f"<tr><td class='se-l'>CMF (dinero neto, Chaikin)</td><td class='r'>{cmf_txt}</td></tr>"
                        f"<tr><td class='se-l'>Distribución oculta</td><td class='r'>{div_txt}</td></tr>")
                if trend_up is not None:
                    rows += f"<tr><td class='se-l'>Tendencia (precio vs media 40s)</td><td class='r'>{_yn(trend_up, 'alcista', 'bajista')}</td></tr>"
                if mom3 is not None:
                    mcol = "#2FD08A" if mom3 > 0 else "#F4607A"
                    rows += f"<tr><td class='se-l'>Momentum 3 meses</td><td class='r' style='color:{mcol}'>{mom3:+.1f}%</td></tr>"
                if sf.get("vol_break"):
                    rows += "<tr><td class='se-l'>Volumen</td><td class='r' style='color:#2FD08A'>ruptura al alza con volumen</td></tr>"
                html.append(
                    "<div class='panel full'><h2>Termómetro del mercado — ¿entra o sale dinero del SPY?</h2>"
                    f"<div class='readbox' style='border-color:{vcol}55'><div class='read-light' style='background:{vcol}'></div>"
                    f"<div><div class='read-txt'>{verd}</div><div class='read-stance' style='color:{vcol}'>SPY = el mercado entero (el centro del RRG)</div></div></div>"
                    "<div class='scrollx' style='margin-top:10px'><table class='se'><tr><th class='se-l'>señal</th><th class='r'>lectura</th></tr>"
                    + rows + "</table></div>"
                    "<div class='note' style='margin-top:8px'>Es el <b>flujo absoluto del propio SPY</b> (no relativo): la <b>marea</b> del mercado entero. "
                    "Como SPY es el centro del RRG, su dinero no se ve ahí, por eso va aquí. "
                    "<b>Distribución oculta</b> (el precio sube pero OBV/CMF caen) es el aviso más útil: el mercado sube pero el dinero se va. No es asesoramiento.</div></div>")
        except Exception:
            pass

        # ===== CORTO TÁCTICO — SEMICONDUCTORES (SOXS −3x) — separado y marcado en rojo =====
        try:
            smhf = (flow or {}).get("SMH")
            if smhf is not None and "SMH" in df.columns:
                smh = df["SMH"].dropna()
                sma40 = smh.rolling(40).mean()
                below = bool(smh.iloc[-1] < sma40.iloc[-1]) if sma40.notna().any() else None
                mom3 = ((smh.iloc[-1] / smh.iloc[-14] - 1) * 100) if len(smh) > 14 else None
                obv_ok = bool(smhf.get("obv_above")); cmf = smhf.get("cmf", 0.0) or 0.0
                diverg = bool(smhf.get("diverg"))
                if diverg:
                    verd = "🟢 Setup de corto temprano: el precio aún arriba pero el dinero SALE (distribución oculta). La entrada de corto más limpia — si te pones, es ahora, no cuando ya cae."
                    vcol = "#F4607A"
                elif below and mom3 is not None and mom3 < -8:
                    verd = "🟠 Ya cayendo fuerte: llegas TARDE. Ponerte corto aquí con un 3x inverso es perseguir, con riesgo de rebote violento que destroza el SOXS."
                    vcol = "#F4B740"
                elif obv_ok and cmf > 0:
                    verd = "⛔ NO te pongas corto: el dinero sigue ENTRANDO en semis. Un corto aquí rema contra corriente."
                    vcol = "#2FD08A"
                else:
                    verd = "⚪ Sin señal clara de corto. Espera a que el flujo confirme salida de dinero (distribución oculta)."
                    vcol = "#9FB0C8"
                def _yns(b, t, f):
                    return (f"<b style='color:#2FD08A'>{t}</b>" if b else f"<b style='color:#F4607A'>{f}</b>")
                div_txt = "⚠ <b style='color:#F4607A'>sí — setup de corto</b>" if diverg else "<span style='color:#2FD08A'>no</span>"
                rows = (f"<tr><td class='se-l'>OBV (volumen acumulado)</td><td class='r'>{_yns(obv_ok, 'arriba (entra dinero)', 'abajo (sale dinero)')}</td></tr>"
                        f"<tr><td class='se-l'>CMF (dinero neto)</td><td class='r' style='color:{'#2FD08A' if cmf > 0 else '#F4607A'}'>{cmf:+.3f}</td></tr>"
                        f"<tr><td class='se-l'>Distribución oculta (precio↑ dinero↓)</td><td class='r'>{div_txt}</td></tr>")
                if below is not None:
                    rows += f"<tr><td class='se-l'>Precio vs media 40s</td><td class='r'>{_yns(not below, 'por encima', 'por debajo (ya débil)')}</td></tr>"
                if mom3 is not None:
                    rows += f"<tr><td class='se-l'>Momentum 3 meses</td><td class='r' style='color:{'#2FD08A' if mom3 > 0 else '#F4607A'}'>{mom3:+.1f}%</td></tr>"
                html.append(
                    "<div class='panel full' style='border:1px solid #F4607A55'><h2>🔻 Corto táctico — semiconductores (SOXS −3x)</h2>"
                    "<div class='note' style='color:#F4B740'><b>Avanzado y peligroso.</b> Lee el flujo de los semis (SMH) y lo traduce al lado corto. El instrumento sería <b>SOXS</b> (Direxion −3x diario, el más volátil).</div>"
                    f"<div class='readbox' style='border-color:{vcol}55;margin-top:8px'><div class='read-light' style='background:{vcol}'></div>"
                    f"<div><div class='read-txt'>{verd}</div><div class='read-stance' style='color:{vcol}'>¿está saliendo dinero de los semis?</div></div></div>"
                    "<div class='scrollx' style='margin-top:10px'><table class='se'><tr><th class='se-l'>señal (sobre SMH)</th><th class='r'>lectura</th></tr>"
                    + rows + "</table></div>"
                    "<div class='note' style='margin-top:10px;color:#F4607A'><b>Reglas de supervivencia:</b> "
                    "① corto SOLO con <b>distribución oculta</b> (dinero saliendo y precio aún arriba), nunca solo porque \"esté extendido\". "
                    "② SOXS −3x tiene <b>decay diario brutal</b>: es de <b>días, no semanas</b>. "
                    "③ Si ya cae en vertical, <b>llegas tarde</b> y el rebote te revienta. "
                    "④ Stop duro, tamaño mínimo. Esto es <b>predecir un techo</b>, lo contrario a tu sistema. No es asesoramiento.</div></div>")
        except Exception:
            pass

        html.append("<div class='panel full'><h2>Lectura del mercado y probabilidades</h2>"
                    f"<div class='readbox' style='border-color:{light}55'><div class='read-light' style='background:{light}'></div>"
                    f"<div><div class='read-txt'>{read}</div><div class='read-stance' style='color:{light}'>{stance}</div></div></div>"
                    "<div class='note' style='margin-top:12px'><b>Probabilidades históricas</b> (base, no predicción): de todas las veces que un ETF "
                    "cumplía N de las 3 señales estructurales (<b>precio &gt; media 40s</b>, <b>RS subiendo</b>, <b>gana dinero a 3m</b>), "
                    f"qué % de veces estaba más arriba <b>{fwd} semanas después</b> y cuánto de media. Calculado sobre {probs['weeks']} semanas de tu propio histórico.</div>"
                    f"<table class='pb'><tr><th class='pb-l'></th><th class='pb-v'>prob. subir</th><th class='pb-v'>media {fwd}s</th><th class='pb-n'>muestra</th></tr>{prob_rows}</table>"
                    + (f"<div class='note' style='margin:12px 0 6px'><b>Listos para invertir la semana que viene</b> (puntuación 4–5/5), con el porqué y su probabilidad histórica:</div>{cand}" if cand else "")
                    + "<div class='note' style='margin-top:10px;color:#F4B740'>⚠ Son <b>frecuencias históricas sobre una muestra corta</b> (~"
                    f"{probs['weeks']} semanas), no una predicción. Como el póker: tener buena mano sube las probabilidades, no garantiza ganar la mano. No es asesoramiento.</div></div>")

    # ---- ESTACIONALIDAD (media-quincena: S&P, Nasdaq, Russell) ----
    if season:
        idx_names = list(season.keys())
        base_rows = season[idx_names[0]]["rows"]
        def se_cell(st):
            if not st or st.get("pup") is None:
                return "<td class='se-c' style='color:#3A4658'>—</td>"
            pcol = "#2FD08A" if st["pup"] >= 60 else "#F4B740" if st["pup"] >= 50 else "#F4607A"
            acol = "#9FB0C8" if st["avg"] is None else ("#7FE0B0" if st["avg"] >= 0 else "#F49AAC")
            return (f"<td class='se-c'><span class='se-pup' style='color:{pcol}'>{st['pup']}%</span>"
                    f"<span class='se-avg' style='color:{acol}'>{st['avg']:+.2f}%</span></td>")
        head = "".join(f"<th class='se-c'>{esc(n)}</th>" for n in idx_names)
        body = ""
        for i, base in enumerate(base_rows):
            tag = "<span class='se-now'>ahora</span>" if i == 0 else ("<span class='se-next'>próxima</span>" if i == 1 else "")
            cells = "".join(se_cell(season[n]["rows"][i] if i < len(season[n]["rows"]) else None) for n in idx_names)
            rowcls = " class='se-hi'" if i <= 1 else ""
            body += f"<tr{rowcls}><td class='se-l'>{base['label']}{tag}</td>{cells}</tr>"
        yrs = " · ".join(f"{n} {season[n]['years']}a" for n in idx_names)
        html.append("<div class='panel full'><h2>Estacionalidad por media-quincena (S&P · Nasdaq · Russell)</h2>"
                    "<div class='note'>De cada media-quincena (1ª mitad = días 1–15, 2ª = 16–fin), <b>% de años que cerró en positivo</b> "
                    "y <b>retorno medio</b>, para los tres índices. <b style='color:#2FD08A'>Verde</b> = quincena históricamente alcista; "
                    "<b style='color:#F4607A'>rojo</b> = floja. Es un <b>viento de fondo</b> probabilístico, no una señal de entrada. "
                    f"Histórico: {yrs}.</div>"
                    f"<table class='se'><tr><th class='se-l'></th>{head}</tr>{body}</table>"
                    "<div class='note' style='margin-top:8px'>El Russell (small caps) y el Nasdaq suelen tener su patrón propio "
                    "(p. ej. fuerza de fin de año en small caps). Por eso conviene mirar el índice del activo que vas a tocar.</div></div>")

    # ---- PUNTUACION (SCORING): el entregable de 5 minutos ----
    # historico para "% desde que entro" (racha continua; reinicia si sale y vuelve) — disponible para scoring Y cartera
    try:
        _recs_e = json.load(open(TRACK_FILE, encoding="utf-8")) if os.path.exists(TRACK_FILE) else []
    except Exception:
        _recs_e = []
    try:
        _cur_week = semana_trading(df.index[-1].date())
    except Exception:
        _cur_week = ""
    def _entrada_html(sym, key, in_now):
        try:
            cur_px = float(df[sym].dropna().iloc[-1])
        except Exception:
            return "<span style='color:var(--txt3)'>—</span>"
        res = pct_desde_entrada(_recs_e, sym, key, _cur_week, in_now, cur_px, df)
        if res is None:
            return "<span style='color:var(--txt3)'>—</span>"
        p, wk = res
        col = "#2FD08A" if p >= 0 else "#F4607A"
        return f"<span style='color:{col}'>{p:+.1f}%</span> <span style='color:var(--txt3);font-size:10px'>{wk}s</span>"

    if scores:
        _marked = {r["sym"] for r in scores if r["score"] >= 4}      # "marcado" = señal de compra (>=4/5)
        def sc_col(sc):
            return "#2FD08A" if sc >= 4 else "#F4B740" if sc == 3 else "#F4607A"
        def sc_act(sc):
            return ("comprar" if sc >= 4 else "vigilar" if sc == 3 else "evitar / vender")
        labels = [p[0] for p in scores[0]["parts"]]
        head = "".join(f"<th class='sc-h'>{l}</th>" for l in labels)
        body = ""
        ncols = 1 + len(labels) + 4
        def _sc_row(r):
            cells = ""
            for _, v in r["parts"]:
                cells += (f"<td class='sc-c' style='color:{'#2FD08A' if v else '#5E708A'}'>{'✓' if v else '·'}</td>")
            nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
            cross = "<span class='sc-acc' title='OBV cruzó su media esta semana: presión compradora acelerando'>⚡ acelera</span>" if r["obv_cross"] else ""
            warn = "<span class='sc-warn' title='precio sube pero el dinero sale: distribución oculta'>⚠ distribución</span>" if r.get("distrib") else ""
            col = sc_col(r["score"])
            wk = ""
            try:
                _s = df[r["sym"]].dropna()
                if len(_s) >= 2:
                    _w = (float(_s.iloc[-1]) / float(_s.iloc[-2]) - 1) * 100
                    wk = f"<span style='color:{'#2FD08A' if _w >= 0 else '#F4607A'}'>{_w:+.1f}%</span>"
            except Exception:
                pass
            desde = _entrada_html(r["sym"], "marked", r["score"] >= 4)
            return (f"<tr><td class='sc-name'><b>{r['sym']}</b> <span>{esc(nm)}</span>{cross}{warn}</td>{cells}"
                    f"<td class='sc-c'>{wk}</td>"
                    f"<td class='sc-c'>{desde}</td>"
                    f"<td class='sc-tot' style='color:{col}'>{r['score']}/5</td>"
                    f"<td class='sc-act' style='color:{col}'>{sc_act(r['score'])}</td></tr>")
        for g in GRUPO_ORDEN:
            grp_rows = [r for r in scores if GRUPO.get(r["sym"]) == g]
            if not grp_rows:
                continue
            body += f"<tr><td class='sc-grp' colspan='{ncols}'>{GRUPO_NOMBRE.get(g, g)}</td></tr>"
            for r in grp_rows:
                body += _sc_row(r)
        html.append("<div class='panel full'><h2>Puntuación (scoring) — decide en 5 minutos</h2>"
                    "<div class='note'>Cada ETF suma 1 punto por: <b>precio &gt; su media de 40 semanas</b>, "
                    "<b>RS subiendo</b> (vs S&P), <b>momentum absoluto 3m &gt; 0</b> (gana dinero de verdad), "
                    "<b>OBV por encima de su media</b> y <b>CMF &gt; 0</b> (entra dinero). Ordenado de mayor a menor. "
                    "Regla simple: entra en los <b>4–5/5</b>, vende los que bajen a <b>≤2/5</b>. "
                    "El <b>⚡ acelera</b> marca que el OBV acaba de cruzar su media (entrada temprana). No es asesoramiento.</div>"
                    f"<table class='sc'><tr><th class='sc-name'></th>{head}<th class='sc-h'>sem. curso</th><th class='sc-h'>desde entrada</th><th class='sc-h'>total</th><th class='sc-h'>acción</th></tr>{body}</table></div>")

    # ---- CARTERA DE LA SEMANA (Lider + Mejorando + momentum absoluto positivo) ----
    _ord = {"leading": 0, "improving": 1}
    def _cart_key(sd):
        # Líder primero (si el flag está activo), luego por impulso; si no, solo impulso
        if CARTERA_LIDER_PRIMERO:
            return (_ord.get(sd[1]["quad"], 9), -(sd[1]["mom"] or 0))
        return (-(sd[1]["mom"] or 0),)
    _cart_universe = set(SECTORS + THEMATIC + EXTRA)   # la cartera rota sectores/tematicos, no satelites (IWM, TLT, GLD, UUP, HYG)
    chosen_all = [(s, d) for s, d in rrg.items() if d["quad"] in ("leading", "improving") and s in _cart_universe]

    def _abs_mom_sym(sym):
        # momentum absoluto 3m (13 semanas) calculado directamente del precio (vale para satelites)
        if sym not in df.columns:
            return None
        s = df[sym].dropna()
        if len(s) < 14:
            return None
        n = min(13, len(s) - 1)
        return float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    excluded_dm = []
    if CARTERA_DUAL_MOMENTUM:
        keep = []
        for s, d in chosen_all:
            am = _abs_mom_sym(s)
            if am is None or am > 0:        # si no se puede medir, NO se excluye por esto
                keep.append((s, d))
            else:
                excluded_dm.append(s)
        chosen = keep
    else:
        chosen = chosen_all
    # alinear con el scoring: fuera lo que el scoring suspende (< CARTERA_SCORE_MIN) y SIEMPRE la distribución oculta
    excluded_sc, excluded_di, excluded_fl = [], [], []
    if scores:
        sc_map = {r["sym"]: r["score"] for r in scores}
        distrib_set = {r["sym"] for r in scores if r.get("distrib")}
        keep = []
        for s, d in chosen:
            _cmf = (flow or {}).get(s, {}).get("cmf")
            if s in distrib_set:                         # distribución oculta: el dinero sale -> nunca entra (arregla la paradoja ITB)
                excluded_di.append(s)
            elif CARTERA_SCORE_MIN and sc_map.get(s, 0) < CARTERA_SCORE_MIN:
                excluded_sc.append(s)
            elif CARTERA_EXIGE_FLUJO and _cmf is not None and _cmf < -0.05:   # solo si el dinero SALE de verdad (mismo umbral que todo el panel: plano = -0.05..+0.05 no expulsa)
                excluded_fl.append(s)
            else:
                keep.append((s, d))
        chosen = keep
    below_trend = {r["sym"] for r in scores if r.get("above_sma") is False} if scores else set()   # bajo su propia media 40s: se etiqueta, no se expulsa
    chosen.sort(key=_cart_key)
    # set de símbolos que SÍ entran en la cartera de la semana (top-N), para cruzar con la pantalla Operativa
    _cart_sorted = sorted(chosen, key=_cart_key)
    cartera_syms = {s for s, _ in (_cart_sorted[:MAX_POSICIONES] if MAX_POSICIONES else _cart_sorted)}
    # === FUENTE UNICA DE VERDAD ===
    # CARTERA_FINAL = la unica lista que se opera (todos los filtros + tope de posiciones, universo "Todos").
    # TODOS los paneles (veredicto, mesa, track record, candidato, redes, Modo Claude) leen de aqui.
    CARTERA_FINAL = [s for s, _ in (_cart_sorted[:MAX_POSICIONES] if MAX_POSICIONES else _cart_sorted)]

    def _prev_quad(d):
        rs = d.get("ratio_series") or []
        ms = d.get("mom_series") or []
        if len(rs) >= 2 and rs[-2] is not None and ms[-2] is not None and rs[-2] == rs[-2] and ms[-2] == ms[-2]:
            return quad_of(rs[-2], ms[-2])
        return None

    n_wk = len(chosen)
    if n_wk:
        # estado del mercado para el filtro de tendencia
        spy_w = df[BENCH]
        spy_ma = float(spy_w.rolling(min(TREND_MA_WEEKS, len(spy_w)), min_periods=5).mean().iloc[-1])
        bull = spy_w.iloc[-1] >= spy_ma
        wvol = {s: df[s].pct_change().rolling(13, min_periods=4).std().iloc[-1] for s in rrg}

        def _weights(syms):
            w = {}
            for s in syms:
                if PESO == "volatilidad":
                    v = wvol.get(s)
                    w[s] = 1.0 / (v if v and v == v and v > 1e-6 else 0.02)
                elif PESO == "impulso":
                    w[s] = max(0.1, (rrg[s]["mom"] or 100) - 99)
                else:
                    w[s] = 1.0
            tot = sum(w.values()) or 1.0
            return {s: w[s] / tot for s in syms}

        def _cartera_block(keep):
            sel = [(s, d) for s, d in chosen if keep(s)]
            sel.sort(key=_cart_key)
            if MAX_POSICIONES and len(sel) > MAX_POSICIONES:
                sel = sel[:MAX_POSICIONES]
            n = len(sel)
            if not n:
                return "<div class='note'>Nada en Líder/Mejorando esta semana.</div>"
            w = _weights([s for s, _ in sel])
            # regla anti-anomalia: tope de peso por posicion; el resto se declara LIQUIDEZ.
            _capped = {s: min(w[s] * 100, CARTERA_PESO_MAX) for s, _ in sel}
            _liquidez = max(0.0, 100.0 - sum(_capped.values()))
            rows = ""
            for s, d in sel:
                col = QUAD[d["quad"]][1]
                nm = NAMES.get(s, (s, s, ""))[1]
                pct = _capped[s]
                veh = LEV3X.get(s, "—")
                veh_h = f"<span class='wk-x3'>x3 {veh}</span>" if veh and veh != "—" else ""
                top = TOP_HOLDING.get(s, "")
                fs = fresh_stocks(leaders, s)
                if fs:
                    stk = ", ".join((PHASE_INFO.get(r.get("phase"), ("",))[0] + " " + r["sym"] + f" ↑{r['drs']}").strip() for r in fs)
                    top_h = f"<span class='wk-stk' title='acelerando y no en máximos (no extendidas)'>acciones: {esc(stk)}</span>"
                else:
                    top_h = f"<span class='wk-stk' title='accion lider (orientativo)'>lider: {esc(top)}</span>" if top else ""
                isnew = _prev_quad(d) not in ("leading", "improving")
                tag = "<span class='wk-new'>NUEVO</span>" if isnew else "<span class='wk-keep'>mantener</span>"
                trend_warn = ("<span style='font-size:9.5px;color:#5AA9E6;border:1px solid #5AA9E555;border-radius:4px;padding:1px 5px;margin-left:4px;white-space:nowrap' title='rebote por debajo de su media de 40 semanas — mira el gráfico antes de entrar'>⚠ bajo tendencia, mira el gráfico</span>"
                              if (CARTERA_AVISA_TENDENCIA and s in below_trend) else "")
                desde_h = f"<span class='wk-desde' title='rentabilidad del ETF desde que entró en la cartera (se reinicia si sale y vuelve)'>{_entrada_html(s, 'basket', True)}</span>"
                # AVISO DE COHERENCIA: el tema dominante de este ETF, ¿está saliendo en el mercado US?
                coh_warn = ""
                _coh = COHERENCIA_TEMA.get(s)
                if _coh and s not in _coh[1]:            # no compararse consigo mismo
                    tema, espejos = _coh
                    _malos = [e for e in espejos if e in rrg and rrg[e]["quad"] in ("weakening", "lagging")]
                    if _malos and len(_malos) == len([e for e in espejos if e in rrg]):
                        coh_warn = (f"<span style='font-size:9.5px;color:#F4B740;border:1px solid #F4B74055;border-radius:4px;padding:1px 5px;margin-left:4px;white-space:nowrap' "
                                    f"title='Sube como bloque, pero su tema dominante ({tema}) está debilitándose en EE.UU. ({', '.join(_malos)}). "
                                    f"Puede ser fuerza sana (rota hacia value) o entrada por la puerta de atrás de un tema que el sistema rechaza. Mira su composición.'>"
                                    f"⚠ {esc(tema)} flojo en US</span>")
                rows += (f"<div class='wkrow'><span class='wk-sym'><span class='dot' style='background:{col}'></span>{s}</span>"
                         f"<span class='wk-name'>{esc(nm)} · {QUAD[d['quad']][0]}</span>"
                         f"<span class='wk-eur'>{pct:.0f}%</span>{desde_h}{veh_h}{top_h}{trend_warn}{coh_warn}{tag}</div>")
            if _liquidez >= 1:
                rows += (f"<div class='wkrow' style='border-top:1px dashed #2A3A55'><span class='wk-sym'><span class='dot' style='background:#5E708A'></span>💤</span>"
                         f"<span class='wk-name'>LIQUIDEZ — sin señal suficiente donde ponerla</span>"
                         f"<span class='wk-eur' style='color:#9FB0C8'>{_liquidez:.0f}%</span>"
                         f"<span class='wk-stk' title='regla anti-anomalía: cuando los filtros dejan pocas posiciones (como esta semana el flujo), ninguna se lleva más del "
                         f"{CARTERA_PESO_MAX}% — el resto espera en liquidez a que haya más señales. Editable en CARTERA_PESO_MAX.'>"
                         "quedarse fuera también es una posición</span></div>")
            ex = [s for s, d in rrg.items() if keep(s) and d["quad"] not in ("leading", "improving") and _prev_quad(d) in ("leading", "improving")]
            ex_h = (f"<div class='note' style='margin-top:10px;color:#F4607A'><b>Salen esta semana (vender):</b> {', '.join(ex)}</div>" if ex else "")
            pesotxt = {"volatilidad": "ponderado por volatilidad inversa", "impulso": "ponderado por impulso", "igual": "a partes iguales"}[PESO]
            head = (f"<div class='note' style='margin-bottom:8px;color:#2FD08A'>"
                    f"<b>👉 Aquí repartes tu dinero:</b> estas <b>{n}</b> posiciones son la cartera de esta semana, con el <b>% de tu capital</b> que va en cada una "
                    f"(tope {MAX_POSICIONES or '∞'} posiciones, {pesotxt}). "
                    f"<b>acciones:</b> = qué comprar si el ETF no se vende en España o quieres apalancar.</div>")
            return head + rows + ex_h

        bull_banner = ("<div class='note' style='margin-bottom:10px;padding:8px 12px;border-radius:8px;background:rgba(47,208,138,.1);color:#2FD08A'>"
                       "✓ <b>Mercado alcista</b> (S&P por encima de su media de 40 semanas): la estrategia invierte.</div>"
                       if bull else
                       "<div class='note' style='margin-bottom:10px;padding:8px 12px;border-radius:8px;background:rgba(244,96,122,.12);color:#F4607A'>"
                       "⚠ <b>Mercado bajista</b> (S&P por debajo de su media de 40 semanas): el filtro de tendencia recomienda "
                       "<b>liquidez / defensivo</b>. Las posiciones de abajo son orientativas; el backtest estaría en liquidez.</div>")

        sec_html = _cartera_block(lambda s: s in SECTORS)
        all_html = _cartera_block(lambda s: True)
        dm_note = ""
        if excluded_dm:
            dm_note = ("<div class='note' style='margin-top:8px;color:#F4B740'>⚠ <b>Excluidos por momentum absoluto negativo</b> "
                       "(suben respecto al S&P pero <b>pierden dinero</b> en términos absolutos, así que no se entra): "
                       + ", ".join(excluded_dm) + ".</div>")
        if excluded_di:
            dm_note += ("<div class='note' style='margin-top:8px;color:#F4607A'>⚠ <b>Excluidos por distribución oculta</b> "
                        "(el precio sube pero el dinero sale; no se entra aunque roten al alza): " + ", ".join(excluded_di) + ".</div>")
        if excluded_fl:
            dm_note += ("<div class='note' style='margin-top:8px;color:#F4B740'>⚠ <b>Excluidos por flujo negativo</b> (CMF &lt; -0.05, el dinero sale de verdad; el flujo plano no expulsa: "
                        "la cartera exige el mismo flujo que Operativa; editable en CARTERA_EXIGE_FLUJO): " + ", ".join(excluded_fl) + ".</div>")
        if excluded_sc:
            dm_note += ("<div class='note' style='margin-top:8px;color:#F4B740'>⚠ <b>Excluidos por puntuación &lt; "
                        f"{CARTERA_SCORE_MIN}/5</b> (el scoring los marca como «evitar», para que cartera y scoring no se contradigan): "
                        + ", ".join(excluded_sc) + ".</div>")
        html.append("<div class='panel full'><h2>Cartera de la semana (rotación)</h2>"
                    + bull_banner +
                    "<div class='note'>Reparto del <b>% de tu capital</b> entre lo más fuerte en "
                    "<b>Líder o Mejorando</b>, con las optimizaciones activas: <b>filtro de tendencia</b> (solo invierte en "
                    f"mercado alcista), <b>doble momentum</b> (exige también que gane dinero en absoluto), <b>tope de {MAX_POSICIONES or '∞'} posiciones</b> por impulso "
                    "y <b>peso por volatilidad</b>. <b>Solo sectores</b> = menos comisiones; "
                    "<b>Todos</b> incluye temáticos. Los % suman 100 y los aplicas a tu propio capital.</div>"
                    + dm_note +
                    "<div class='viewtabs'>"
                    "<button class='viewtab cartab active' onclick=\"carView('all',this)\">Todos (la cartera que se opera)</button>"
                    "<button class='viewtab cartab' onclick=\"carView('sec',this)\">Solo sectores</button>"
                    "</div>"
                    "<div id='car-all'>" + all_html + "</div>"
                    "<div id='car-sec' style='display:none'>" + sec_html + "</div>"
                    "<script>function carView(v,b){document.getElementById('car-sec').style.display=(v=='sec')?'block':'none';"
                    "document.getElementById('car-all').style.display=(v=='all')?'block':'none';"
                    "document.querySelectorAll('.cartab').forEach(function(x){x.classList.remove('active')});b.classList.add('active');}</script>"
                    "<div class='note' style='margin-top:10px'>Rutina: <b>decides en el cierre del viernes y ejecutas el lunes</b>; "
                    "aguantas la semana y solo tocas lo que cambia (NUEVO / salen). No es asesoramiento.</div></div>")

    # ---- CANDIDATO DE LA SEMANA (el sistema elige la accion; tu solo ejecutas o no) ----
    candidato = None
    try:
        candidato = compute_candidato(CARTERA_FINAL, leaders, flow, scores, rrg)
    except Exception:
        candidato = None
    if candidato:
        top = candidato["top"]
        st = top["stock"]
        pe, pl, pc = PHASE_INFO.get(st.get("phase"), ("", "—", "#9FB0C8"))
        crows = ""
        for c in candidato["per"]:
            s2 = c["stock"]
            pe2, pl2, pc2 = PHASE_INFO.get(s2.get("phase"), ("", "—", "#9FB0C8"))
            mark = " 🏆" if c is top else ""
            cmf_t = ("<span style='color:#2FD08A'>entra</span>" if (c["cmf"] or 0) > 0.05 else
                     "<span style='color:#F4607A'>sale</span>" if (c["cmf"] or 0) < -0.05 else
                     "<span style='color:#9FB0C8'>plano</span>") if c["cmf"] is not None else "—"
            crows += (f"<tr><td class='se-l'><b>{c['etf']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(NAMES.get(c['etf'], (c['etf'], c['etf'], ''))[1])}</span></td>"
                      f"<td class='se-l'><b style='color:#5B8CFF'>{s2['sym']}</b>{mark}</td>"
                      f"<td class='r' style='font-weight:700'>{s2['rs']}</td>"
                      f"<td class='r' style='color:#7BD88F'>{(s2.get('drs') if s2.get('drs') is not None else 0):+d}</td>"
                      f"<td class='r'>{s2['hi']}%</td>"
                      f"<td class='r' style='color:{pc2};font-size:11px;white-space:nowrap'>{pe2} {pl2}</td>"
                      f"<td class='r' style='font-size:11px'>{cmf_t}</td>"
                      f"<td class='r' style='font-weight:700'>{c['tot']:.0f}</td></tr>")
        html.append("<div class='panel full'><h2>🏆 Candidato de la semana — lo elige el sistema, no tú</h2>"
                    f"<div class='note'>De los ETFs que están <b>esta semana en la cartera</b>, el sistema analiza sus acciones y elige "
                    "<b>una candidata por sector</b> con un criterio fijo (percentil de fuerza + aceleración 3m + fase + no extendida + salud del ETF padre) "
                    "y <b>una ganadora absoluta</b>. Sin discreción: mismas reglas cada semana, para quitarle la decisión al impulso del momento.</div>"
                    f"<div style='margin:10px 0;padding:12px 14px;background:rgba(91,140,255,.08);border:1px solid #5B8CFF44;border-radius:9px'>"
                    f"<span style='font-size:11px;color:#9FB0C8'>ELECCIÓN DE ESTA SEMANA</span><br>"
                    f"<b style='font-size:19px;color:#5B8CFF'>{st['sym']}</b> "
                    f"<span style='color:#9FB0C8'>(vía {top['etf']})</span> · "
                    f"<span style='color:{pc}'>{pe} {pl}</span><br>"
                    f"<span style='font-size:12px;color:var(--txt2)'>{esc(top['why'])}</span></div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'>ETF en cartera</th><th class='se-l'>candidata</th>"
                    "<th class='r'>RS</th><th class='r'>acel. 3m</th><th class='r'>% máx 52s</th><th class='r'>fase</th>"
                    "<th class='r'>flujo ETF</th><th class='r'>puntos</th></tr>" + crows + "</table></div>"
                    "<div class='note' style='margin-top:8px'>Disciplina: la candidata se decide con el <b>cierre confirmado del viernes</b> y se ejecuta el lunes, "
                    "como el resto del sistema. Si la semana siguiente su ETF sale de la cartera, la candidata sale con él. "
                    "Solo hay acciones para los ETFs con desglose (sectores, semis, software, agua, biotech, banca regional, viajes, vivienda, defensa). No es asesoramiento.</div></div>")

    # ---- SEGUIMIENTO SEMANAL DEL SISTEMA (track record real, semana a semana + acumulado) ----
    basket = list(CARTERA_FINAL)          # la MISMA lista que la Cartera de la semana (todos los filtros + tope)
    tperf = None
    if basket:
        try:
            px_now = {k: float(v) for k, v in df.iloc[-1].to_dict().items() if v == v}
            px_now["SPY"] = float(df[BENCH].iloc[-1])
            if "IWM" in df.columns:
                px_now["IWM"] = float(df["IWM"].iloc[-1])
            if nq_close is not None and len(nq_close):
                px_now["QQQ"] = float(nq_close.iloc[-1])
            _marked_now = [r["sym"] for r in (scores or []) if r["score"] >= 4]
            recs = update_track_record(basket, px_now, str(df.index[-1].date()), marked=_marked_now)
            tperf = compute_track_perf(recs)
        except Exception:
            tperf = None
    if tperf:
        def _pct(x):
            return f"{x*100:+.1f}%"
        def _cc(x):
            return "#2FD08A" if x >= 0 else "#F4607A"
        bn = ("SPY", "QQQ", "IWM")
        cum = tperf["cum"]
        has_ew = "ew" in cum and any(w.get("ew") is not None for w in tperf["weeks"])
        rows = ""
        for w in tperf["weeks"][-10:]:
            beat = w["sys"] - w["bench"].get("SPY", 0.0)
            bcells = ""
            for b in bn:
                rb = w["bench"].get(b)
                bcells += (f"<td class='r' style='color:{_cc(rb)}'>{_pct(rb)}</td>" if rb is not None else "<td class='r' style='color:#5E708A'>—</td>")
            ew = w.get("ew")
            ewcell = (f"<td class='r' style='color:{_cc(ew)}'>{_pct(ew)}</td>" if ew is not None else "<td class='r' style='color:#5E708A'>—</td>") if has_ew else ""
            rows += (f"<tr><td class='se-l'>{w['week']}</td>"
                     f"<td class='r' style='color:{_cc(w['sys'])};font-weight:700'>{_pct(w['sys'])}</td>{ewcell}{bcells}"
                     f"<td class='r' style='color:{_cc(beat)}'>{_pct(beat)}</td></tr>")
        cumcells = "".join(f"<td class='r' style='color:{_cc(cum.get(b,0))};font-weight:700'>{_pct(cum.get(b,0))}</td>" for b in bn)
        ewcum = cum.get("ew", 0.0)
        ewcumcell = (f"<td class='r' style='color:{_cc(ewcum)};font-weight:700'>{_pct(ewcum)}</td>") if has_ew else ""
        beat_cum = cum["sys"] - cum.get("SPY", 0.0)
        beat_ew = cum["sys"] - ewcum
        cumrow = (f"<tr style='border-top:2px solid #1C2740'><td class='se-l'><b>ACUMULADO ({tperf['n']} sem)</b></td>"
                  f"<td class='r' style='color:{_cc(cum['sys'])};font-weight:800'>{_pct(cum['sys'])}</td>{ewcumcell}{cumcells}"
                  f"<td class='r' style='color:{_cc(beat_cum)};font-weight:700'>{_pct(beat_cum)}</td></tr>")
        ewth = "<th class='r'>sect.EW</th>" if has_ew else ""
        verdict = (f"bate al S&P por {_pct(beat_cum)}" if beat_cum >= 0 else f"por debajo del S&P ({_pct(beat_cum)})")
        ewphrase = ""
        if has_ew:
            ewverd = (f"<b style='color:#2FD08A'>bate por {_pct(beat_ew)}</b>" if beat_ew >= 0
                      else f"<b style='color:#F4607A'>pierde por {_pct(beat_ew)}</b>")
            ewphrase = (f" · vs <b>sectores equiponderados</b> {_pct(ewcum)}: la <b>selección</b> {ewverd} "
                        "a tener los 11 sectores por igual")
        head = (f"Desde que registras ({tperf['n']} semanas): <b style='color:{_cc(cum['sys'])}'>sistema {_pct(cum['sys'])}</b> · "
                f"SPY {_pct(cum.get('SPY',0))} · QQQ {_pct(cum['QQQ']) if 'QQQ' in cum else '—'} · IWM {_pct(cum['IWM']) if 'IWM' in cum else '—'} → "
                f"<b style='color:{_cc(beat_cum)}'>{verdict}</b>{ewphrase}")
        pend = tperf["pending"]
        # ---- GRAFICO DOSIER: curva acumulada sistema vs SPY (incluye entradas Y salidas: la cadena real) ----
        graf = ""
        try:
            wks = tperf["weeks"]
            if len(wks) >= 2:
                serie_sys = [0.0] + [w["cum_sys"] * 100 for w in wks]
                serie_spy = [0.0] + [w.get("cum_SPY", 0) * 100 for w in wks]
                labels = ["inicio"] + [w["week"].split("-W")[-1] + "'" for w in wks]
                W, H, ML, MT, MB, MR = 720, 300, 46, 24, 46, 16
                lo = min(min(serie_sys), min(serie_spy), 0) - 1
                hi = max(max(serie_sys), max(serie_spy), 0) + 1
                rng = (hi - lo) or 1
                def X(i): return ML + i * (W - ML - MR) / (len(serie_sys) - 1)
                def Y(v): return MT + (hi - v) / rng * (H - MT - MB)
                def path(serie): return "M" + " L".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(serie))
                area_sys = path(serie_sys) + f" L{X(len(serie_sys)-1):.1f},{Y(lo):.1f} L{X(0):.1f},{Y(lo):.1f} Z"
                y0 = Y(0)
                # rejilla horizontal
                grid = ""
                for gv in range(int(lo), int(hi) + 1):
                    if gv % max(1, int(rng / 5)) == 0:
                        gy = Y(gv)
                        grid += f"<line x1='{ML}' y1='{gy:.1f}' x2='{W-MR}' y2='{gy:.1f}' stroke='#1C2740' stroke-width='1'/>"
                        grid += f"<text x='{ML-6}' y='{gy+3:.1f}' fill='#5E708A' font-size='9' text-anchor='end'>{gv:+d}%</text>"
                # etiquetas X (cada ~2)
                xlabels = ""
                step = max(1, len(labels) // 8)
                for i in range(0, len(labels), step):
                    xlabels += f"<text x='{X(i):.1f}' y='{H-MB+16:.1f}' fill='#5E708A' font-size='9' text-anchor='middle'>{esc(labels[i])}</text>"
                _fsys, _fspy = serie_sys[-1], serie_spy[-1]
                _csys = "#2FD08A" if _fsys >= _fspy else "#F4607A"
                graf = (f"<div style='background:#0A0E17;border:1px solid #1C2740;border-radius:10px;padding:14px 10px 6px;margin:10px 0'>"
                        f"<svg viewBox='0 0 {W} {H}' style='width:100%;height:auto;font-family:system-ui'>"
                        f"<defs><linearGradient id='gsys' x1='0' y1='0' x2='0' y2='1'>"
                        f"<stop offset='0%' stop-color='{_csys}' stop-opacity='0.28'/><stop offset='100%' stop-color='{_csys}' stop-opacity='0'/></linearGradient></defs>"
                        + grid +
                        f"<line x1='{ML}' y1='{y0:.1f}' x2='{W-MR}' y2='{y0:.1f}' stroke='#3A4A63' stroke-width='1' stroke-dasharray='3,3'/>"
                        f"<path d='{area_sys}' fill='url(#gsys)'/>"
                        f"<path d='{path(serie_spy)}' fill='none' stroke='#8FA3C0' stroke-width='2' stroke-dasharray='5,4'/>"
                        f"<path d='{path(serie_sys)}' fill='none' stroke='{_csys}' stroke-width='2.5'/>"
                        f"<circle cx='{X(len(serie_sys)-1):.1f}' cy='{Y(_fsys):.1f}' r='4' fill='{_csys}'/>"
                        f"<circle cx='{X(len(serie_spy)-1):.1f}' cy='{Y(_fspy):.1f}' r='3.5' fill='#8FA3C0'/>"
                        f"<text x='{W-MR-2:.1f}' y='{Y(_fsys)-8:.1f}' fill='{_csys}' font-size='12' font-weight='700' text-anchor='end'>Sistema {_fsys:+.1f}%</text>"
                        f"<text x='{W-MR-2:.1f}' y='{Y(_fspy)+14:.1f}' fill='#8FA3C0' font-size='11' text-anchor='end'>S&amp;P 500 {_fspy:+.1f}%</text>"
                        + xlabels +
                        "</svg>"
                        "<div style='display:flex;gap:18px;justify-content:center;font-size:11px;color:#9FB0C8;padding:4px 0 2px'>"
                        f"<span><span style='display:inline-block;width:14px;height:3px;background:{_csys};vertical-align:middle'></span> Cartera del sistema (rota cada semana)</span>"
                        "<span><span style='display:inline-block;width:14px;height:2px;background:#8FA3C0;vertical-align:middle'></span> S&amp;P 500 (comprar y mantener)</span>"
                        "</div></div>")
        except Exception:
            graf = ""
        html.append("<div class='panel full'><h2>📈 Track record del sistema — rendimiento acumulado verificable</h2>"
                    f"<div class='note'>{head}</div>"
                    + graf +
                    "<div class='note' style='margin:6px 0'>Esta curva es la <b>cadena real</b>: cada semana la cartera se recompone y se encadena su rendimiento — "
                    "incluye <b>las posiciones que entraron Y las que salieron</b>, ganaran o perdieran. Es lo que de verdad habría hecho tu dinero siguiendo el sistema, "
                    "no una selección de aciertos. Por eso puede diferir de la tabla de posiciones actuales de la pestaña Redes.</div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'>semana</th><th class='r'>sistema</th>"
                    + ewth + "<th class='r'>SPY</th><th class='r'>QQQ</th><th class='r'>IWM</th><th class='r'>vs S&amp;P</th></tr>"
                    + rows + cumrow + "</table></div>"
                    f"<div class='note' style='margin-top:8px'>La <b>cesta del sistema</b> = las posiciones de la <b>Cartera de la semana</b> (equiponderadas), rotada cada semana. "
                    "<b>sect.EW</b> = los <b>11 sectores SPDR equiponderados</b> (sin rotar): es la referencia honesta de si tu <b>selección</b> aporta algo o si te bastaría con tenerlos todos por igual. "
                    f"En curso ({esc(pend['week'])}): <b>{esc(', '.join(pend['basket']) or '—')}</b> — su resultado se medirá en el próximo registro. "
                    "<b>Paper-track honesto</b>: sin comisiones, impuestos ni slippage; se construye solo si ejecutas la herramienta cada semana. No es asesoramiento.</div></div>")
    elif basket:
        html.append("<div class='panel full'><h2>📈 Track record del sistema — rendimiento acumulado verificable</h2>"
                    f"<div class='note'>Acabo de registrar la cesta de esta semana (<b>{esc(', '.join(basket))}</b>). "
                    "El seguimiento se construye <b>ejecutando la herramienta cada semana</b>: la próxima vez compararé esta cesta con <b>SPY / QQQ / IWM</b> "
                    "y verás, semana a semana y en acumulado, si el sistema bate al mercado. No es asesoramiento.</div></div>")

    # ---- SINTETIZAR FIW: acciones de agua ordenadas por fuerza relativa (para España, donde no se compra el ETF) ----
    if leaders and leaders.get("FIW"):
        _wn = {"ROP":"Roper","FERG":"Ferguson","MLI":"Mueller Ind.","AWK":"American Water","WAT":"Waters",
               "XYL":"Xylem","VLTO":"Veralto","ECL":"Ecolab","IEX":"IDEX","PNR":"Pentair","A":"Agilent",
               "IDXX":"IDEXX Labs","J":"Jacobs","MAS":"Masco","STN":"Stantec","ACM":"AECOM","FELE":"Franklin Electric",
               "WMS":"Adv. Drainage","WTS":"Watts Water","MWA":"Mueller Water","TTEK":"Tetra Tech","ZWS":"Zurn Elkay",
               "CNM":"Core & Main","BMI":"Badger Meter","ITRI":"Itron"}
        wrows = ""
        for r in leaders["FIW"]:
            acc = "—"
            if r["drs"] is not None:
                if r["drs"] >= 8:
                    acc = f"<span style='color:#2FD08A'>⚡ +{r['drs']}</span>"
                elif r["drs"] <= -8:
                    acc = f"<span style='color:#F4607A'>▼ {r['drs']}</span>"
                else:
                    acc = f"<span style='color:var(--txt3)'>{r['drs']:+d}</span>"
            rscol = "#2FD08A" if r["rs"] >= 70 else ("#F4B740" if r["rs"] >= 40 else "#9FB0C8")
            hicol = "#2FD08A" if r["hi"] >= 90 else ("#F4B740" if r["hi"] >= 75 else "#9FB0C8")
            cfd = (" <span class='lchip' style='background:#13351F;border-color:#2FD08A55;color:#2FD08A;font-size:10px;padding:1px 5px'>CFD XTB</span>"
                   if r["sym"] in XTB_CFD_AGUA else "")
            ph = r.get("phase"); pe, pl, pc = PHASE_INFO.get(ph, ("", "—", "#9FB0C8"))
            wrows += (f"<tr><td class='se-l'><b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(_wn.get(r['sym'],''))}</span>{cfd}</td>"
                      f"<td class='r' style='color:{rscol};font-weight:700'>{r['rs']}</td>"
                      f"<td class='r' style='color:{hicol}'>{r['hi']}%</td>"
                      f"<td class='r'>{acc}</td>"
                      f"<td class='r' style='color:{pc};font-size:11px;white-space:nowrap'>{pe} {pl}</td></tr>")
        topn = [r["sym"] for r in leaders["FIW"][:6]]
        html.append("<div class='panel full'><h2>Sintetiza FIW: agua por fuerza relativa</h2>"
                    "<div class='note'>El ETF FIW no se compra en España, pero <b>sus acciones US sí</b> (XTB/DEGIRO; lo que la UE bloquea es el ETF, no la acción). "
                    "Aquí van las empresas del fondo <b>ordenadas por percentil de fuerza relativa frente a todo el mercado</b> (no por tamaño): "
                    "<b>percentil</b> 1–99 (99 = de las más fuertes del mercado), <b>% máx 52s</b> (cerca de 100 = en máximos), "
                    "<b>acel. 3m</b> = cuánto ha subido su percentil en 3 meses (⚡ acelerando, ▼ perdiendo fuerza). "
                    f"Para sintetizar el ETF quedándote con lo mejor, una vía es las de mayor percentil — ahora mismo: <b>{esc(', '.join(topn))}</b>. "
                    "Equipondéralas y revisa cada semana: rota la que caiga de percentil. Ojo: 5–8 acciones es <b>más concentrado</b> que las 39 del ETF, "
                    "así que más riesgo idiosincrático; cuantas más metas, más te pareces al fondo. "
                    "La etiqueta <span style='color:#2FD08A'>CFD XTB</span> marca las que creo disponibles como CFD en XTB (para apalancar agua, que no tiene ETF x3); "
                    "<b>es una lista de partida que debes verificar</b> en el buscador de XTB, porque su catálogo cambia y no puedo comprobarlo en vivo. No es asesoramiento.</div>"
                    "<div class='note' style='margin-top:6px'><b>Fase</b> (modelo de 4 fases): "
                    "🟦 base/acumulación (lateral abajo, dinero entrando callado, antes de arrancar) · 🟢 subiendo (tendencia sana, aquí quieres estar) · "
                    "🟠 distribución (lateral pegada a máximos, techo formándose y el dinero saliendo — <b>la trampa de MLI</b>) · 🔴 cayendo · ⚪ lateral medio sin sesgo claro. "
                    "Se calcula con la media de 30 semanas, dónde está en su rango de 52s y si su fuerza acelera. Es un <b>mapa de probabilidad, no una predicción</b>: una base puede romper para arriba o para abajo; el flujo inclina la balanza, no la garantiza.</div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'>empresa</th><th class='r'>percentil RS</th>"
                    "<th class='r'>% máx 52s</th><th class='r'>acel. 3m</th><th class='r'>fase</th></tr>" + wrows + "</table></div></div>")

    # ---- PLAN DE ROTACION DE MI CARTERA (compara tu cartera real con las señales) ----
    mi_plan = compute_mi_cartera_plan(MI_CARTERA, rrg, scores, flow, chosen, df)
    if mi_plan:
        mrows = ""
        _n_trampa = 0
        for r in mi_plan["rows"]:
            est = (f"{r.get('quad','—')}" + (f" · {r['sc']}/5" if r.get("sc") is not None else "")) if r["base"] else "—"
            eur = f"{r['eur']:,.0f} €" if isinstance(r["eur"], (int, float)) else esc(str(r["eur"]))
            _dd = r.get("dd_pos")
            ddcell = (f"<span style='color:{'#F4607A' if _dd <= -10 else '#F4B740' if _dd <= -3 else '#9FB0C8'}'>{_dd:.0f}%</span>" if _dd is not None else "—")
            motivo = esc(r["why"])
            if r.get("corte"):
                _tipo, _ccol, _ctxt = r["corte"]
                if _tipo == "trampa":
                    _n_trampa += 1
                motivo += f"<br><span style='color:{_ccol};font-size:10.5px'>{esc(_ctxt)}</span>"
            mrows += (f"<tr><td class='se-l'><b>{esc(r['tk'])}</b>{esc(r.get('via',''))}</td>"
                      f"<td class='r' style='color:#9FB0C8'>{esc(r['broker'])}</td>"
                      f"<td class='r'>{eur}</td><td class='r'>{ddcell}</td><td class='r' style='color:#9FB0C8;font-size:11px'>{esc(est)}</td>"
                      f"<td class='r'><b style='color:{r['col']}'>{esc(r['act'])}</b></td>"
                      f"<td class='se-l' style='font-size:11px;color:var(--txt2)'>{motivo}</td></tr>")
        rot = ""
        if mi_plan["rotar_hacia"]:
            chips = " ".join(f"<span class='lchip'><b>{r['sym']}</b> <span style='color:var(--txt3)'>{r['quad']}"
                             + (f" {r['sc']}/5" if r["sc"] is not None else "") + "</span></span>" for r in mi_plan["rotar_hacia"])
            rot = (f"<div style='margin-top:10px'><b style='color:#5B8CFF'>ROTAR HACIA</b> "
                   "<span class='note' style='display:inline'>(recomendadas que aún no tienes):</span><div class='lchips' style='margin-top:6px'>" + chips + "</div></div>")
        html.append("<div class='panel full'><h2>🩺 Plan de rotación de mi cartera — cortar o aguantar</h2>"
                    f"<div class='note'>Compara <b>tus posiciones reales</b> (editables arriba del archivo en <code>MI_CARTERA</code>) con las señales de hoy. "
                    f"Total declarado: <b>{mi_plan['total']:,.0f} €</b> · mantener {mi_plan['n_mantener']} · vender/rotar {mi_plan['n_vender']}"
                    + (f" · <b style='color:#F4607A'>{_n_trampa} en trampa de esperanza</b>" if _n_trampa else "") + ". "
                    "La columna <b>caída</b> es cuánto ha bajado desde su máximo de 52s. El motivo te dice si el sistema ordena <b>CORTAR</b> "
                    "(cae y el dinero sigue saliendo) o si hay <b>base para aguantar con stop</b> (el flujo ya frenó). "
                    "Las acciones y apalancados se evalúan por su ETF de referencia (vía …).</div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'></th><th class='r'>broker</th><th class='r'>importe</th>"
                    "<th class='r'>caída</th><th class='r'>estado</th><th class='r'>acción</th><th class='se-l'>motivo</th></tr>"
                    + mrows + "</table></div>" + rot +
                    "<div class='note' style='margin-top:10px;color:#F4B740'>⚠ La <b>trampa de esperanza</b>: mantener algo que cae «a ver si recupera» mientras el dinero sigue saliendo "
                    "es cómo una pérdida pequeña se hace grande. El sistema no siente apego: si el flujo confirma la salida, corta. "
                    "Esto aplica a tu <b>parte de rotación</b>, no a la liquidez de reserva. Rotar mucho genera comisiones y plusvalías que tributan. No es asesoramiento.</div></div>")

    # ---- APALANCAMIENTO CONSOLIDADO (XTB + Robinhood + DEGIRO) + STRESS-TEST ----
    apal = None
    try:
        apal = compute_apalancamiento(MI_CARTERA, BROKER_INFO)
    except Exception:
        apal = None
    if apal:
        _e = lambda v: f"{v:,.0f} €".replace(",", ".")
        brows = ""
        for b in apal["brokers"]:
            esc5, esc10, esc20 = (b["esc"].get(dd) for dd in STRESS_DD)
            def _cell(e):
                if not e:
                    return "<td class='r'>—</td>"
                col = "#F4607A" if e["estado"] in ("STOP-OUT", "margin call", "cuenta a cero") else "#F4B740" if e["estado"] != "ok" else "#9FB0C8"
                niv = f" · nivel {e['nivel_after']:.0f}%" if e["nivel_after"] is not None else ""
                tag = f"<br><b style='color:{col};font-size:10px'>{e['estado'].upper()}</b>" if e["estado"] != "ok" else ""
                return (f"<td class='r' style='white-space:nowrap'><span style='color:#F4607A'>{e['loss']:+,.0f} €</span> "
                        f"<span style='color:#5E708A;font-size:10px'>({e['pct']:.0f}%{niv})</span>{tag}</td>").replace(",", ".")
            lev_col = "#F4607A" if b["lev_ef"] >= 2.5 else "#F4B740" if b["lev_ef"] >= 1.5 else "#2FD08A"
            extra = ""
            info = b.get("info") or {}
            if info.get("nivel_margen") is not None:
                mcol = "#F4607A" if info["nivel_margen"] < 120 else "#F4B740" if info["nivel_margen"] < 200 else "#2FD08A"
                extra = f"<br><span style='color:{mcol};font-size:10px'>nivel margen HOY: {info['nivel_margen']:.0f}% · libre {info.get('margen_libre', 0):.0f} €</span>"
            brows += (f"<tr><td class='se-l'><b>{esc(b['broker'])}</b>{extra}</td>"
                      f"<td class='r'>{_e(b['equity'])}</td>"
                      f"<td class='r'>{_e(b['expo'])}</td>"
                      f"<td class='r' style='color:{lev_col};font-weight:700'>{b['lev_ef']:.2f}×</td>"
                      + _cell(esc5) + _cell(esc10) + _cell(esc20) + "</tr>")
        tcol = "#F4607A" if apal["lev_ef"] >= 2 else "#F4B740" if apal["lev_ef"] >= 1.4 else "#2FD08A"
        trow = (f"<tr style='border-top:2px solid #1C2740'><td class='se-l'><b>TOTAL</b></td>"
                f"<td class='r'><b>{_e(apal['tot_eur'])}</b></td>"
                f"<td class='r'><b>{_e(apal['tot_expo'])}</b></td>"
                f"<td class='r' style='color:{tcol};font-weight:800'>{apal['lev_ef']:.2f}×</td>"
                + "".join(f"<td class='r' style='color:#F4607A;font-weight:700'>{apal['tot_stress'][dd]:+,.0f} €</td>".replace(",", ".") for dd in STRESS_DD)
                + "</tr>")
        xtb_i = (BROKER_INFO or {}).get("XTB", {})
        warn_xtb = ""
        if xtb_i.get("nivel_margen") is not None and xtb_i["nivel_margen"] < 120:
            warn_xtb = (f"<div class='note' style='margin-top:8px;color:#F4607A'>🚨 <b>XTB en zona crítica</b>: nivel de margen "
                        f"{xtb_i['nivel_margen']:.1f}% y solo {xtb_i.get('margen_libre', 0):.0f} € libres. Sin colchón, una caída moderada "
                        "activa cierres forzosos <b>en el peor momento</b> (justo cuando tu plan de liquidez diría comprar). "
                        "Prioridad antes que cualquier rotación: liberar margen (reducir posiciones CFD) o aportar garantías.</div>")
        html.append("<div class='panel full'><h2>⚖️ Apalancamiento consolidado — los 3 brokers juntos</h2>"
                    "<div class='note'>Lo que ningún broker te enseña: tu <b>exposición real total</b> (importe × apalancamiento) y qué le pasaría "
                    "al equity de cada cuenta si el S&amp;P cae <b>−5% / −10% / −20%</b> (con beta aproximada por tipo de activo: "
                    "cripto ~1.8×, plata ~0.8×, bonos ~−0.2×, resto ~1×). Es un choque de <b>1 día</b>: en una caída de varios días con "
                    "volatilidad, los productos de <b>reset diario</b> (3x/5x) pierden <b>más</b> por el decay — este cuadro es el suelo optimista.</div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'>broker</th><th class='r'>equity</th>"
                    "<th class='r'>exposición</th><th class='r'>apalanc. efectivo</th>"
                    + "".join(f"<th class='r'>S&amp;P {dd}%</th>" for dd in STRESS_DD)
                    + "</tr>" + brows + trow + "</table></div>"
                    + warn_xtb +
                    "<div class='note' style='margin-top:8px'>Regla que hemos hablado: si quieres usar margen de IBKR (tu 10% de pólvora), "
                    "este cuadro tiene que seguir en verde <b>en el escenario −20%</b> DESPUÉS de añadirlo. Margen sobre productos ya apalancados "
                    "= apalancamiento al cuadrado. Los importes de posición se editan arriba en <code>MI_CARTERA</code> y los datos de margen en "
                    "<code>BROKER_INFO</code>. No es asesoramiento.</div></div>")

    # ---- VEREDICTO DE HOY (resumen de un vistazo, se inserta arriba) ----
    sem_short = stance.split("—")[0].strip() or "—"
    reg_short = regime["label"].split(" / ")[0]
    mkt = "alcista" if bull else "bajista"
    top_pos = list(CARTERA_FINAL)          # identica a la Cartera de la semana: una sola verdad
    if not bull:
        cartera_txt = "liquidez — el filtro de tendencia no invierte en mercado bajista"
    elif top_pos:
        cartera_txt = ", ".join(top_pos)
    else:
        cartera_txt = "nada claro — mantener liquidez"
    breadth_pct = round(100 * sum(1 for s in rrg if rrg[s]["ratio"] >= 100) / max(1, len(rrg)))
    if not bull:
        ojo = "el S&P está por debajo de su media de 40s: prioriza <b>liquidez / defensivo</b>."
    elif excluded_di:
        ojo = f"<b>distribución oculta</b> (el dinero sale) en {', '.join(excluded_di)} — no te fíes de su subida."
    elif leaving:
        ojo = f"perdiendo liderazgo: <b>{', '.join(leaving[:4])}</b> (recoger / no añadir)."
    elif breadth_pct < 40:
        ojo = f"amplitud estrecha ({breadth_pct}%): la subida la sostienen pocos sectores, sé selectivo."
    else:
        ojo = "sin alertas mayores; sigue el plan."
    liq = ""
    if plan:
        nxt = next((r for r in plan["rungs"] if not r["hit"]), None)
        if nxt:
            liq = f"S&P {plan['dd']:.1f}% de máximos · próximo escalón −{nxt['thr']}% (faltan {(nxt['thr'] + plan['dd']):.1f}%)."
    verdict_html = (
        "<div class='panel full verdict'><h2>Veredicto de hoy</h2>"
        + ("<div style='margin:0 0 10px 0;padding:9px 12px;background:rgba(244,183,64,.12);border:1px solid #F4B74066;border-radius:8px;font-size:12.5px;color:#F4B740'>"
           "⚠ <b>Cierre de media semana</b> — el sistema decide con el <b>cierre del VIERNES</b>. Hoy es solo <b>observación</b>: mira los giros y prepárate, "
           "pero <b>no ejecutes rotaciones</b> hasta el viernes. El track record de la semana quedó congelado en su primer registro; esta ejecución no lo altera.</div>"
           if media_semana else "")
        + f"<div class='vrow'><span class='vk' style='background:{light}'>¿Invierto?</span>"
        f"<span><b style='color:{light}'>{esc(sem_short)}</b> · {esc(reg_short)}, {esc(risk['label'])}, mercado {mkt}</span></div>"
        f"<div class='vrow'><span class='vk' style='background:#5B8CFF'>Compra</span><span>{esc(cartera_txt)}</span></div>"
        f"<div class='vrow'><span class='vk' style='background:#F4B740'>Ojo</span><span>{ojo}</span></div>"
        + (f"<div class='vrow'><span class='vk' style='background:#93A4BC'>Liquidez</span><span>{liq}</span></div>" if liq else "")
        + "<div class='note' style='margin-top:6px'>Resumen de un vistazo. Debajo tienes la decisión completa (scoring, cartera, entrada temprana) "
          "y, plegado, todo el detalle (RRG, flujo, rankings). No es asesoramiento.</div></div>")

    # ---- ANALISIS IA (opcional) + boton para analizar con IA ----
    snap = state_summary(rrg, risk, regime, breadth, plan, flow)
    snap_js = (snap.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')
                   .replace("`", "'").replace("\n", "\\n"))
    ai_inner = ""
    if ai_text:
        ai_inner = f"<div class='ai-box'>{esc(ai_text)}</div>"
    else:
        ai_inner = ("<div class='note'>Este panel calcula los datos (no es IA en tiempo real). Pulsa para que una IA "
                    "te analice la foto de hoy: copia el resumen y lo pegas en Claude/ChatGPT, o abre Claude directamente.</div>")
    html.append("<div class='panel full'><h2>Análisis con IA</h2>" + ai_inner +
                "<div style='margin-top:10px;display:flex;gap:8px;flex-wrap:wrap'>"
                f"<button class='ai-btn' onclick=\"navigator.clipboard.writeText('Analiza esta rotacion sectorial (datos de cierre):\\n\\n{snap_js}'); this.textContent='Copiado, pegalo en tu IA';\">Copiar resumen para IA</button>"
                "<a class='ai-btn alt' href='https://claude.ai/new' target='_blank' rel='noopener'>Abrir Claude</a>"
                "</div></div>")

    # ---- TIRA RESUMEN (flujo + alertas) justo encima del RRG ----
    entra, sale, cuida = [], [], []
    for sym, fdat in (flow or {}).items():
        dv = fdat.get("diverg"); lab = fdat.get("label")
        if dv == "acumulacion oculta":
            entra.append((sym, True))
        elif lab == "Acumulacion":
            entra.append((sym, False))
        if dv == "distribucion oculta":
            cuida.append(sym)
        elif lab == "Distribucion":
            sale.append(sym)
    def fchips(items, col, ring=0):
        out = ""
        for it in items:
            sym = it[0] if isinstance(it, tuple) else it
            strong = it[1] if isinstance(it, tuple) else False
            mark = ""
            if ring == 2:   # doble circulo rojo
                mark = "<span class='ring2'></span>"
            elif strong:
                mark = "<span class='ring1'></span>"
            out += f"<span class='fchip' style='border-color:{col}55;color:{col}'>{mark}{sym}</span>"
        return out or "<span class='qempty'>—</span>"
    alert_chips = ""
    for sym, kind, txt in (alerts or [])[:8]:
        acol = {"warn": "#F4B740", "in": "#2FD08A", "lead": "#5B8CFF", "down": "#F4607A"}.get(kind, "#93A4BC")
        alert_chips += f"<span class='fchip' style='border-color:{acol}55;color:{acol}' title='{esc(txt)}'>{sym}</span>"
    html.append("<div class='panel full'><h2>Resumen visual: flujo y rotación</h2>"
                "<div class='fgrid'>"
                "<div class='fcol'><div class='fhead' style='color:#2FD08A'>● Entra dinero (acumulación)</div>"
                f"<div class='fchips'>{fchips(entra, '#2FD08A')}</div></div>"
                "<div class='fcol'><div class='fhead' style='color:#F4607A'>◎ Cuidado: distribución oculta</div>"
                f"<div class='fchips'>{fchips(cuida, '#F4607A', ring=2)}</div></div>"
                "<div class='fcol'><div class='fhead' style='color:#F4B740'>Alertas de rotación</div>"
                f"<div class='fchips'>{alert_chips or '<span class=qempty>sin giros</span>'}</div></div>"
                "</div>"
                "<div class='note' style='margin-top:8px'>El <b>◎ doble círculo rojo</b> marca distribución oculta (precio sube, dinero sale: "
                "cuidado). Estos mismos avisos salen dibujados <b>dentro del RRG</b>: anillo verde = entra dinero, doble anillo rojo = cuidado.</div></div>")

    # ---- RRG con selector por grupo (Todos / Sectores / Subsectores / Internacional) ----
    # calidad global de cada ETF: alimenta el TAMAÑO de la bola (mas verde en todo -> mas grande)
    quality = {}
    sc_q = {r["sym"]: r for r in scores} if scores else {}
    for s in rrg:
        base = sc_q.get(s, {}).get("score")
        q = 2.5 if base is None else float(base)              # satelites sin score -> neutro
        f = flow.get(s, {}) if flow else {}
        if f.get("diverg") == "distribucion oculta":
            q -= 1.5
        elif f.get("obv_above") and f.get("cmf_pos"):
            q += 1.5
        if sector_breadth and s in sector_breadth:
            bp = sector_breadth[s]["pct"]
            q += 1.0 if bp >= 60 else (-1.0 if bp < 40 else 0.0)
        if f.get("vol_break"):
            q += 0.7
        quality[s] = q
    rrg_g = {g: {s: d for s, d in rrg.items() if GRUPO.get(s) == g} for g in GRUPO_ORDEN}
    _rrgt = "<button class='viewtab rrgtab active' onclick=\"rrgView('all',this)\">Todos</button>"
    for _g in GRUPO_ORDEN:
        _rrgt += "<button class='viewtab rrgtab' onclick=\"rrgView('" + _g + "',this)\">" + GRUPO_NOMBRE.get(_g, _g) + "</button>"
    _rrgd = "<div id='rrg-all' style='max-width:1040px;margin:0 auto;display:block'>" + render_svg(rrg, flow, quality) + "</div>"
    for _g in GRUPO_ORDEN:
        _rrgd += "<div id='rrg-" + _g + "' style='max-width:1040px;margin:0 auto;display:none'>" + render_svg(rrg_g[_g], flow, quality) + "</div>"
    _rrgk = "['all'," + ",".join("'" + _g + "'" for _g in GRUPO_ORDEN) + "]"
    html.append("<div class='panel full'><h2>Grafico de rotacion relativa (RRG)</h2>"
                "<div class='note'>Cada punto pequeño de la estela es una <b>semana</b> (pasa el ratón o toca para la fecha). "
                "La <b>flecha</b> marca hacia dónde se mueve. El <b>tamaño de la bola</b> = calidad global de la señal "
                "(scoring + flujo + amplitud + volumen): más grande = mejor en todo. Anillo <b style='color:#2FD08A'>verde</b> = entra dinero; "
                "<b style='color:#F4607A'>doble rojo</b> = distribución oculta (cuidado). Usa el selector para ver cada grupo a tamaño completo.</div>"
                "<div class='viewtabs'>"
                + _rrgt +
                "</div>"
                + _rrgd +
                "<script>function rrgView(v,b){" + _rrgk + ".forEach(function(g){"
                "document.getElementById('rrg-'+g).style.display=(g==v)?'block':'none';});"
                "document.querySelectorAll('.rrgtab').forEach(function(x){x.classList.remove('active')});b.classList.add('active');}</script>"
                "<div id='rrgtip' style='position:fixed;display:none;z-index:9999;background:#0F1623;color:#E6EDF6;"
                "border:1px solid #2B3850;border-radius:7px;padding:6px 9px;font-size:12px;max-width:240px;"
                "box-shadow:0 6px 20px rgba(0,0,0,.5);pointer-events:none'></div>"
                "<script>(function(){var tip=document.getElementById('rrgtip');"
                "function show(x,y,t){tip.textContent=t;tip.style.display='block';"
                "var L=Math.min(x+12,window.innerWidth-tip.offsetWidth-8);tip.style.left=Math.max(6,L)+'px';"
                "tip.style.top=Math.min(y+12,window.innerHeight-tip.offsetHeight-8)+'px';}"
                "function hide(){tip.style.display='none';}"
                "document.addEventListener('click',function(e){var d=e.target.closest('.tdot');"
                "if(d){show(e.clientX,e.clientY,d.getAttribute('data-t'));e.stopPropagation();}else hide();},true);"
                "document.querySelectorAll('.tdot').forEach(function(d){"
                "d.addEventListener('mouseenter',function(e){show(e.clientX,e.clientY,d.getAttribute('data-t'));});"
                "d.addEventListener('mouseleave',hide);});})();</script>"
                "<div class='legend' style='justify-content:center'>" +
                "".join(f"<span><i style='background:{QUAD[q][1]}'></i>{QUAD[q][0]}</span>" for q in QUAD) +
                "</div></div>")
    # ---- GRAFICO INTERACTIVO (TradingView, gratuito via widget; requiere internet) ----
    try:
        _tv_syms = sorted(rrg.keys())
        _tv_opts = "".join(f"<option value='{s}'{' selected' if s == 'XBI' else ''}>{s} · {esc(NAMES.get(s, (s, s, ''))[1])}</option>" for s in _tv_syms)
        html.append(
            "<div class='panel full'><h2>📺 Gráfico interactivo (TradingView)</h2>"
            "<div class='note'>Gráfico profesional en velas <b>semanales</b> del ETF que elijas (zoom, indicadores, dibujar). "
            "Necesita internet. Si en este mismo navegador tienes abierta tu sesión de TradingView de pago, tus preferencias extra aparecen solas. No es asesoramiento.</div>"
            f"<select id='tvsel' style='margin:6px 0;padding:7px 10px;background:#0E1626;color:#E8EEF9;border:1px solid #ffffff22;border-radius:6px;font-size:13px'>{_tv_opts}</select>"
            "<div id='tvwrap' style='height:470px;border-radius:8px;overflow:hidden'></div>"
            "<script src='https://s3.tradingview.com/tv.js'></script>"
            "<script>function tvload(s){var w=document.getElementById('tvwrap');w.innerHTML='';"
            "try{new TradingView.widget({container_id:'tvwrap',symbol:s,interval:'W',autosize:true,theme:'dark',style:'1',locale:'es',hide_side_toolbar:false,allow_symbol_change:true});}"
            "catch(e){w.innerHTML='<div style=\\'color:#9FB0C8;padding:20px\\'>Sin conexión con TradingView (requiere internet).</div>';}}"
            "var _tvs=document.getElementById('tvsel');_tvs.addEventListener('change',function(){tvload(this.value)});tvload(_tvs.value);</script>"
            "</div>")
    except Exception:
        pass
    # ---- INDICADOR PINE v6 (para pegar en TradingView): el MISMO flujo del terminal, en grafico profesional ----
    try:
        html.append(
            "<div class='panel full'><h2>📟 Tu flujo en TradingView (indicador Pine v6)</h2>"
            "<div class='note'>El <b>mismo CMF y la misma distribución oculta</b> que calcula este terminal (umbral ±0.05), como indicador "
            "para TradingView: se ve en una <b>ventana bajo el gráfico</b> de arriba y así comparas el flujo con las velas profesionales. "
            "Cómo instalarlo: en TradingView abre el <b>Editor Pine</b> (pestaña inferior) → borra lo que haya → pega este código → "
            "<b>Añadir al gráfico</b> → guárdalo como «Flujo PeVR» y te aparecerá en tus indicadores para siempre. "
            "Ponlo en velas <b>semanales</b> para que cuente la misma historia que el terminal.</div>"
            "<button class='viewtab' onclick=\"var t=document.getElementById('pinesrc').innerText;navigator.clipboard.writeText(t).then(function(){alert('Código Pine copiado. Pégalo en el Editor Pine de TradingView.')});\" "
            "style='margin:6px 0;font-size:12px;border-color:#5B8CFF55;color:#5B8CFF'>📋 Copiar código Pine</button>"
            "<details><summary style='cursor:pointer;color:#9FB0C8;font-size:12px'>Ver el código</summary>"
            "<pre id='pinesrc' style='background:#0E1626;border:1px solid #ffffff18;border-radius:8px;padding:12px;font-size:11px;overflow-x:auto;color:#CDE3FF'>"
            + esc(PINE_SCRIPT) +
            "</pre></details>"
            "<div class='note' style='margin-top:6px;color:#5E708A'>El triángulo naranja marca la <b>distribución oculta</b> (precio sube en 13 velas "
            "pero el dinero sale) — la misma señal que aquí excluye a un ETF de la cartera. Incluye alerta configurable en TradingView "
            "(botón de alertas → condición «Flujo PeVR: Distribución oculta»).</div></div>")
    except Exception:
        pass
    # ---- ZONA DE ENTRADA TEMPRANA (giro al alza, aún sin extender) ----
    if early:
        def _emerging_stock(sym):
            if not leaders or sym not in leaders:
                return None
            rows = leaders[sym]
            em = [r for r in rows if r.get("drs") is not None and r["drs"] >= 10 and 45 <= r["rs"] <= 92]
            if em:
                return max(em, key=lambda r: r["drs"])
            acc = [r for r in rows if r.get("drs") is not None and r["drs"] >= 5 and r["rs"] <= 92]
            return max(acc, key=lambda r: r["drs"]) if acc else None
        erows = ""
        for r in early[:8]:
            nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
            qn = QUAD.get(r["quad"], (r["quad"], "#888"))[0]
            extcol = "#2FD08A" if r["ext"] <= 2 else "#F4B740"
            st = _emerging_stock(r["sym"])
            stock = (f"<b>{st['sym']}</b> <span style='color:#7BD88F'>RS {st['rs']} ↑{st['drs']}</span>"
                     if st else "<span style='color:#5E708A'>—</span>")
            fl = flow.get(r["sym"], {})
            if fl.get("diverg") == "distribucion oculta":
                conf = "<span style='color:#F4607A'>⚠ sale dinero</span>"
            elif fl.get("obv_above") and fl.get("cmf_pos"):
                conf = "<span style='color:#2FD08A'>✓ flujo confirma</span>"
            elif fl.get("obv_above") or fl.get("cmf_pos"):
                conf = "<span style='color:#F4B740'>~ parcial</span>"
            else:
                conf = "<span style='color:#5E708A'>— sin flujo</span>"
            vert = ("<span style='color:#7BD88F;font-weight:700' title='giro VERTICAL: impulso acelerando fuerte (>=3) con fuerza aun baja — tu patron de arranque de varias semanas'>🚀</span> "
                    if (r["accel"] >= 3 and r["ratio"] <= 97) else "")
            erows += (f"<tr><td class='se-l'>{vert}<b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span></td>"
                      f"<td class='r' style='color:#9FB0C8'>{qn}</td>"
                      f"<td class='r'>{r['ratio']:.0f}</td><td class='r' style='color:#5B8CFF'>{r['mom']:.0f}</td>"
                      f"<td class='r' style='color:#2FD08A'>+{r['accel']:.1f}</td>"
                      f"<td class='r' style='color:{extcol}'>{r['ext']:+.1f}%</td>"
                      f"<td class='r' style='font-size:11px'>{conf}</td>"
                      f"<td class='se-l'>{stock}</td></tr>")
        if erows:
            html.append("<div class='panel full'><h2>Zona de entrada temprana — giro al alza, aún sin extender</h2>"
                        "<div class='note'>Lo contrario de comprar caro: ETFs cuyo <b>impulso acaba de girarse al alza</b> "
                        "(aceleración positiva) pero que <b>todavía tienen fuerza baja y precio poco estirado</b> sobre su media. "
                        "Es la zona de abajo-izquierda del RRG que empieza a curvarse: <b>el principio del movimiento</b>, antes de que sea "
                        "un líder caro. <b>Aceleración</b> = subida del impulso en 4 semanas; <b>extensión</b> = cuánto está el precio por encima de su media de 40s. "
                        "<b>Flujo</b>: <span style='color:#2FD08A'>✓ confirma</span> = entra dinero (OBV&gt;media y CMF&gt;0) → señal más fiable; "
                        "<span style='color:#F4607A'>⚠ sale dinero</span> = distribución oculta, desconfía. La <b>acción emergente</b> es el nombre del sector que "
                        "más acelera y aún no está agotado. Más especulativo que el scoring. No es asesoramiento.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'></th><th class='r'>cuadrante</th><th class='r'>fuerza</th>"
                        "<th class='r'>impulso</th><th class='r'>acelera</th><th class='r'>extensión</th><th class='r'>flujo</th><th class='se-l'>acción emergente</th></tr>"
                        + erows + "</table></div></div>")

    # (radar de giro vertical absorbido por el panel 😴 DURMIENTES de arriba)

    # (señal contraria 0/3 absorbida por el panel 😴 DURMIENTES; contra_sigs/contra_led ya calculados alli)
    # ---- Vista alternativa: mapa de cuadrantes (sin solapes) ----
    html.append("<details class='why'><summary>El porqué — mapas, flujo, rankings, backtests y diagnóstico <span>(toca para abrir)</span></summary>")
    # ---- MARGEN VS SU MEDIA HISTORICA (contexto de extension, no senal) ----
    if meanrev:
        mvrows = sorted((kv for kv in meanrev.items() if kv[1].get("ytd") is not None),
                        key=lambda kv: -(kv[1]["margen"] if kv[1]["margen"] is not None else -999))
        mrows = ""
        for sym, m in mvrows:
            nm = NAMES.get(sym, (sym, sym, ""))[1]
            mg = m["margen"]
            if m["ytd"] < -10:
                lec, col = "rezagado / débil", "#9FB0C8"
            elif mg >= 5:
                lec, col = "le queda recorrido", "#2FD08A"
            elif mg >= -5:
                lec, col = "en su media (estirado)", "#F4B740"
            else:
                lec, col = "por encima de su media", "#F4607A"
            q = rrg.get(sym, {})
            turning = q.get("quad") in ("leading", "improving") and q.get("mom", 0) > 100
            combo = " <span style='color:#2FD08A;font-size:11px'>⬆ sitio + girando</span>" if (mg >= 3 and turning) else ""
            ytdcol = "#2FD08A" if m["ytd"] >= 0 else "#F4607A"
            mrows += (f"<tr><td class='se-l'><b>{sym}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span>{combo}</td>"
                      f"<td class='r' style='color:#9FB0C8'>{m['cagr']:+.1f}%</td>"
                      f"<td class='r' style='color:{ytdcol}'>{m['ytd']:+.1f}%</td>"
                      f"<td class='r' style='color:{col}'><b>{mg:+.1f}</b></td>"
                      f"<td class='se-l' style='font-size:11px;color:{col}'>{lec}</td></tr>")
        if mrows:
            html.append("<div class='panel full'><h2>Margen vs su media histórica</h2>"
                        "<div class='note'>Rentabilidad media anual de cada ETF (CAGR ~10 años) frente a lo que <b>lleva en el año</b> (YTD). "
                        "El <b>margen</b> = media − YTD: <span style='color:#2FD08A'>positivo</span> = va por debajo de su ritmo habitual (le queda sitio); "
                        "<span style='color:#F4607A'>negativo</span> = ya por encima (estirado). <b>Es contexto, no señal</b>: estar por debajo de la media "
                        "<b>no garantiza</b> subir — un sector puede seguir barato años. Solo es potente combinado con el RRG: "
                        "<b style='color:#2FD08A'>⬆ sitio + girando</b> marca los que están por debajo de su media <b>Y</b> rotando al alza — "
                        "esa es la combinación que de verdad interesa. Ordenado por margen (más sitio arriba). No es asesoramiento.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'></th><th class='r'>media anual</th><th class='r'>este año</th>"
                        "<th class='r'>margen</th><th class='se-l'>lectura</th></tr>" + mrows + "</table></div></div>")
    if heatmap and heatmap["rows"]:
        hcols = "".join(f"<th class='hm-h'>{c}</th>" for c in heatmap["cols"])
        hrows = ""
        for r in heatmap["rows"]:
            nm = NAMES.get(r["sym"], (r["sym"], r["sym"], ""))[1]
            turn = "<span class='hm-turn' title='rotacion temprana'>↗ girando</span>" if r["turning"] else ""
            cells = ""
            for v in r["vals"]:
                txt = "—" if v is None else f"{v:+.1f}"
                cells += f"<td class='hm-c' style='{heatmap_color(v)}'>{txt}</td>"
            hrows += (f"<tr><td class='hm-name'><b>{r['sym']}</b> <span>{esc(nm)}</span>{turn}</td>{cells}</tr>")
        html.append("<div class='panel full'><h2>Mapa de calor: fuerza relativa por plazo</h2>"
                    "<div class='note'>Rendimiento de cada ETF <b>menos el del S&P 500</b> en cada plazo. "
                    "<b style='color:#2FD08A'>Verde</b> = bate al mercado; <b style='color:#F4607A'>rojo</b> = lo hace peor. "
                    "La señal de <b>rotación temprana</b> es una fila <b>roja a 3–6 meses</b> que se pone <b>verde a 1 semana/1 mes</b> "
                    "(marcada con <b>↗ girando</b>): un sector castigado que empieza a despertar.</div>"
                    f"<table class='hm'><tr><th class='hm-name'></th>{hcols}</tr>{hrows}</table></div>")

    # ---- Vista de cuadrantes ----
    html.append("<div class='panel full'><h2>Mapa de cuadrantes (vista alternativa)</h2>"
                "<div class='note'>La misma información sin puntos que se solapan: cada caja lista los ETFs de ese cuadrante, "
                "ordenados por impulso. El número es fuerza/impulso (100 = igual que el índice).</div>"
                + quadrant_grid(rrg) + "</div>")

    # columna izquierda
    html.append("<div>")
    html.append("<div class='panel'><h2>Impulso relativo (RS-Momentum)</h2>"
                "<div class='note'>A la derecha = gana impulso vs indice. A la izquierda = lo pierde. "
                "Aqui aparece pronto el giro antes de que el precio lo confirme.</div>" + "".join(bars) + "</div>")
    html.append("</div>")
    # columna derecha
    html.append("<div>")
    html.append("<div class='panel'><h2>Alertas de rotacion</h2><div class='alerts'>" + al + "</div></div>")
    html.append("<div class='panel'><h2>Amplitud y riesgo</h2>" +
                meter("Sectores con fuerza &gt; indice", breadth["leaders"]) +
                meter("Sectores en tendencia alcista", breadth["uptrend"]) +
                f"<div class='bigrisk {risk_cls}'>{risk['label']}</div>"
                f"<div class='note'>Ciclicos/sensibles vs defensivos: {'+' if risk['score']>=0 else ''}{risk['score']} puntos.</div></div>")
    # panel de flujo de dinero por volumen
    if flow:
        fl_sorted = sorted(flow.items(), key=lambda kv: kv[1]["flow"], reverse=True)
        divs = [(s, d) for s, d in flow.items() if d["diverg"]]
        flow_rows = []
        for s, d in fl_sorted:
            col = "#2FD08A" if d["label"] == "Acumulacion" else "#F4607A" if d["label"] == "Distribucion" else "#93A4BC"
            mag = min(abs(d["flow"]) / 3.0, 1.0) * 50
            left = 50 if d["flow"] >= 0 else 50 - mag
            cmf = d.get("cmf", 0)
            ccol = "#2FD08A" if cmf > 0 else "#F4607A" if cmf < 0 else "#93A4BC"
            cross = " <span class='sc-acc' title='OBV cruzó su media: presión compradora acelerando'>⚡</span>" if d.get("obv_cross") else ""
            vr = d.get("vol_rel", 1.0)
            vcol = "#2FD08A" if d.get("vol_break") else ("#F4B740" if vr >= 1.0 else "#5E708A")
            brk = " 🔼" if d.get("vol_break") else ""
            vol_h = f"<span class='bar-cmf' style='color:{vcol}' title='Volumen de hoy vs media de 20 sesiones (≥1.3x con precio al alza = ruptura con volumen)'>×{vr:.1f} vol{brk}</span>"
            flow_rows.append(f"<div class='bar-row'><span class='bar-lab'>{s}{cross}</span>"
                             f"<div class='bar-track'><div class='bar-mid'></div>"
                             f"<div class='bar' style='background:{col};width:{mag:.0f}%;left:{left:.0f}%'></div></div>"
                             f"<span class='bar-val' style='color:{col}'>{d['flow']:+.1f}</span>"
                             f"<span class='bar-cmf' style='color:{ccol}' title='Chaikin Money Flow'>CMF {cmf:+.2f}</span>"
                             f"{vol_h}</div>")
        div_html = ""
        if divs:
            items = []
            for s, d in divs:
                kind = "warn" if d["diverg"] == "distribucion oculta" else "in"
                txt = ("Precio sube pero sale dinero (distribucion oculta): cuidado."
                       if d["diverg"] == "distribucion oculta"
                       else "Precio flojo pero entra dinero (acumulacion oculta): vigilar.")
                items.append(f"<div class='alert a-{kind}'><span class='atk'>{s}</span><span class='atx'>{txt}</span></div>")
            div_html = "<div class='alerts' style='margin-bottom:10px'>" + "".join(items) + "</div>"
        html.append("<div class='panel'><h2>Flujo de dinero (volumen)</h2>"
                    "<div class='note'>Acumulacion/Distribucion por volumen (OBV + A/D + <b>CMF</b>). Verde = entra dinero, rojo = sale. "
                    "El <b>CMF</b> (−1 a +1) es la presión compradora reciente; <b>⚡</b> = el OBV cruzó al alza su media (acelera). "
                    "El <b>×N vol</b> es el volumen de hoy frente a su media de 20 sesiones; <b>🔼</b> = ruptura al alza con volumen (≥1.3×). "
                    "Las <b>divergencias</b> (precio y dinero en sentidos opuestos) avisan antes que el precio.</div>"
                    + div_html + "".join(flow_rows) + "</div>")
    # panel de cobertura EUR/USD (avanzado)
    if fx:
        euro_strong = fx["strong"]
        fxcol = "#F4607A" if euro_strong else "#2FD08A"
        fxtrend = "Euro fuerte / dólar débil" if euro_strong else "Dólar fuerte / euro débil"
        # recomendacion de cobertura segun fuerza del euro
        if euro_strong and fx["pos"] > 60:
            hedge = ("Euro fuerte y caro (cerca de máximos de 52s): es cuando <b>más conviene cubrir</b> tus "
                     "activos en dólares. Usa ETFs con clase <b>EUR hedged</b> o reduce exposición neta al dólar.")
            hcol = "#F4607A"; hlab = "Cobertura: ALTA prioridad"
        elif euro_strong:
            hedge = ("El euro sube pero no está caro: cobertura <b>moderada</b>. Puedes cubrir una parte e ir "
                     "ajustando si rompe la media de 200 al alza con fuerza.")
            hcol = "#F4B740"; hlab = "Cobertura: media"
        else:
            hedge = ("Dólar fuerte: te da <b>viento a favor</b> al convertir a euros, así que cubrir es poco "
                     "urgente. Vigila un giro del euro (cruce de la media de 50 sobre la de 200).")
            hcol = "#2FD08A"; hlab = "Cobertura: baja prioridad"
        sp = fx["spark"]
        fx_spark = ""
        if len(sp) > 2:
            lo_, hi_ = min(sp), max(sp); rg = (hi_ - lo_) or 1e-9
            pts = " ".join(f"{200*i/(len(sp)-1):.1f},{34-2-(34-4)*(v-lo_)/rg:.1f}" for i, v in enumerate(sp))
            fx_spark = f"<svg width='100%' height='34' viewBox='0 0 200 34' preserveAspectRatio='none'><polyline points='{pts}' fill='none' stroke='{fxcol}' stroke-width='1.5'/></svg>"
        html.append("<div class='panel'><h2>Cobertura EUR/USD</h2>" + fx_spark +
                    f"<div class='kv'><span>EUR/USD</span><b style='color:{fxcol}'>{fx['last']}</b></div>"
                    f"<div class='kv'><span>Media 50 / 200</span><b>{fx['ma50']} / {fx['ma200']}</b></div>"
                    f"<div class='kv'><span>Cruce de medias</span><b>{fx['cross']}</b></div>"
                    f"<div class='kv'><span>Variación 1m / 3m / 6m</span><b>{_pm(fx['roc1m'])} / {_pm(fx['roc3m'])} / {_pm(fx['roc6m'])}</b></div>"
                    f"<div class='kv'><span>Rango 52 semanas</span><b>{fx['lo52']}–{fx['hi52']} ({fx['pos']}%)</b></div>"
                    f"<div class='kv'><span>Tendencia</span><b style='color:{fxcol}'>{fxtrend}</b></div>"
                    f"<div class='note' style='margin-top:8px;color:{hcol}'><b>{hlab}.</b> {hedge}</div>"
                    "<div class='note' style='color:#5E708A'>La dirección del cambio no se puede predecir; esto es la "
                    "lectura técnica actual y su implicación para tu cartera en dólares, no una previsión.</div></div>")
    html.append("</div>")
    # fila completa: ranking enriquecido
    html.append("<div class='panel full'><h2>Ranking por cuadrante</h2>" + table + "</div>")
    # fila completa: backtest
    if bt:
        delta = bt["tot_s"] - bt["tot_b"]
        dcol = "#2FD08A" if delta >= 0 else "#F4607A"
        opt = []
        if TREND_FILTER: opt.append("filtro de tendencia (200d)")
        if MAX_POSICIONES: opt.append(f"tope {MAX_POSICIONES} posic.")
        opt.append({"volatilidad": "peso por volatilidad", "impulso": "peso por impulso", "igual": "peso igual"}[PESO])
        if BUFFER: opt.append(f"histeresis ±{BUFFER:g}")
        html.append("<div class='panel full'><h2>Backtest A — salir al debilitarse</h2>"
                    "<div class='note'>Estrategia <b>causal</b> (no mira el futuro): mantiene los activos en <b>Líder o Mejorando</b> "
                    "y <b>vende al pasar a Debilitándose</b>. Optimizaciones activas: <b>" + ", ".join(opt) + "</b>. "
                    f"Sobre {bt['weeks']} semanas (en mercado el {bt.get('exposure', 100)}% del tiempo).</div>"
                    + equity_svg(bt["dates"], bt["eq_s"], bt["eq_b"]) +
                    "<div class='summary' style='margin-top:12px'>"
                    + scard("Rentab. estrategia", f"{bt['tot_s']:+.1f}%", "#5B8CFF", "periodo completo")
                    + scard(f"Rentab. {BENCH}", f"{bt['tot_b']:+.1f}%", "#93A4BC", "comprar y mantener")
                    + scard("Diferencia", f"{delta:+.1f}%", dcol, "estrategia vs indice")
                    + scard("Caida maxima", f"{bt['mdd_s']:.0f}% / {bt['mdd_b']:.0f}%", "#F4B740", "estrategia / indice")
                    + "</div>"
                    "<div class='note' style='margin-top:8px'>El filtro de tendencia busca <b>bajar la caída máxima</b> (te saca en "
                    "mercados bajistas), no tanto subir la rentabilidad. Historia corta; sin comisiones ni impuestos. No es asesoramiento.</div></div>")
    if bt2:
        delta2 = bt2["tot_s"] - bt2["tot_b"]
        dcol2 = "#2FD08A" if delta2 >= 0 else "#F4607A"
        diff_ab = bt2["tot_s"] - (bt["tot_s"] if bt else 0)
        html.append("<div class='panel full'><h2>Backtest B — aguantar hasta rezagado</h2>"
                    "<div class='note'>Igual que la A pero <b>más paciente</b>: mantiene también los que están en <b>Debilitándose</b> "
                    "y <b>solo vende cuando caen a Rezagado</b> (la salida tardía «Debilitándose → Rezagado»). "
                    f"Sobre {bt2['weeks']} semanas.</div>"
                    + equity_svg(bt2["dates"], bt2["eq_s"], bt2["eq_b"]) +
                    "<div class='summary' style='margin-top:12px'>"
                    + scard("Rentab. estrategia", f"{bt2['tot_s']:+.1f}%", "#5B8CFF", "periodo completo")
                    + scard(f"Rentab. {BENCH}", f"{bt2['tot_b']:+.1f}%", "#93A4BC", "comprar y mantener")
                    + scard("Diferencia", f"{delta2:+.1f}%", dcol2, "estrategia vs indice")
                    + scard("B vs A", f"{diff_ab:+.1f}%", "#2FD08A" if diff_ab >= 0 else "#F4607A", "aguantar vs salir antes")
                    + "</div>"
                    "<div class='note' style='margin-top:8px'>Compara salir pronto (A) con aguantar (B): si <b>B &gt; A</b>, salir al primer "
                    "síntoma te cuesta dinero (sales demasiado pronto); si <b>A &gt; B</b>, cortar rápido protege. Historia corta, no es asesoramiento.</div></div>")
    # fila completa: empresa lider de cada ETF (por si no hay apalancado, entrar en la accion)
    rank_pri = {"leading": 0, "weakening": 1, "improving": 2, "lagging": 3}
    hold_syms = sorted([s for s in rrg if s in TOP_HOLDING],
                       key=lambda s: (rank_pri.get(rrg[s]["quad"], 9), -rrg[s]["mom"]))
    holds = ""
    for s in hold_syms:
        col = QUAD[rrg[s]["quad"]][1]
        holds += (f"<div class='hold'><span class='h-sym'><span class='dot' style='background:{col}'></span>{s}</span>"
                  f"<span class='h-top'>{esc(TOP_HOLDING[s])}</span>"
                  f"<a href='https://stockanalysis.com/etf/{s}/holdings/' target='_blank' rel='noopener'>ver</a></div>")
    html.append("<div class='panel full'><h2>Empresa líder de cada ETF</h2>"
                "<div class='note'>Por si no encuentras el ETF apalancado: la mayor posición de cada ETF (orientativo, "
                "puede cambiar). Pulsa «ver» para la lista actualizada de cada uno. Ordenado por cuadrante e impulso.</div>"
                "<div class='hold-grid'>" + holds + "</div></div>")
    # fila completa: acciones lideres por sector (RS Rating)
    if leaders:
        def rs_col(v):
            return "#2FD08A" if v >= 95 else "#7BD88F" if v >= 90 else "#F4B740" if v >= 80 else "#93A4BC" if v >= 60 else "#5E708A"
        lead_order = sorted(leaders.keys(),
                            key=lambda sec: (rank_pri.get(rrg.get(sec, {}).get("quad"), 9),
                                             -(rrg.get(sec, {}).get("mom", 0))))
        lrows = ""
        for sec in lead_order:
            q = rrg.get(sec, {}).get("quad")
            qchip = (f"<span class='dot' style='background:{QUAD[q][1]}'></span>" if q else "")
            chips = ""
            for r in leaders[sec][:LEADERS_TOP_N]:
                c = rs_col(r["rs"])
                star = " ★" if r["rs"] >= 99 else ""
                drs = r.get("drs")
                acc = ""
                if drs is not None and drs >= 6:
                    acc = f"<span class='accel'>↑{drs}</span>"
                elif drs is not None and drs <= -6:
                    acc = f"<span class='accel down'>↓{abs(drs)}</span>"
                chips += (f"<span class='lchip'><b>{r['sym']}</b>"
                          f"<span class='rsbadge' style='color:{c};border-color:{c}55'>RS {r['rs']}{star}</span>{acc}</span>")
            secname = NAMES.get(sec, (sec, sec, ""))[1]
            br = (sector_breadth or {}).get(sec)
            br_h = ""
            if br:
                bp = br["pct"]
                bc = "#2FD08A" if bp >= 60 else "#F4B740" if bp >= 40 else "#F4607A"
                btitle = ("amplitud amplia: la fuerza del sector está repartida" if bp >= 60 else
                          "amplitud media" if bp >= 40 else "ojo: falso liderazgo, suben pocas (2-3 megacaps)")
                br_h = f"<span class='lbreadth' style='color:{bc};border-color:{bc}55' title='{btitle}'>{bp}% &gt;media50</span>"
            lrows += (f"<div class='lrow'><div class='lsec'>{qchip}<b>{sec}</b> <span>{esc(secname)}</span>{br_h}</div>"
                      f"<div class='lchips'>{chips}</div></div>")
        html.append("<div class='panel full'><h2>Acciones líderes por sector (fuerza relativa)</h2>"
                    f"<div class='note'>RS Rating estilo IBD (1–99): percentil de fuerza calculado sobre las <b>{leaders_n} acciones seguidas</b> "
                    "(cuanto mayor el universo, más se acerca al percentil real del mercado; amplía la lista en SECTOR_STOCKS). "
                    "Las de <b>RS 90+</b> (verde) son las líderes; <b>★</b> = RS 99. El <b>↑N</b> es cuánto ha subido de percentil en 3 meses "
                    "(aceleración). El <b>% &gt;media50</b> de cada sector es su <b>amplitud real</b>: qué % de sus acciones están sobre su media de 50 sesiones "
                    "(<span style='color:#2FD08A'>verde &ge;60%</span> = subida repartida; <span style='color:#F4607A'>rojo &lt;40%</span> = <b>falso liderazgo</b>, tiran 2-3 megacaps). "
                    "Sectores ordenados por su cuadrante. Aproximación del rating, no asesoramiento.</div>"
                    + lrows + "</div>")

        # ---- ACCIONES EMERGENTES: RS acelerando en sectores donde entra dinero ----
        entering = [sec for sec in leaders if rrg.get(sec, {}).get("quad") in ("improving", "leading")]
        cands = []
        for sec in entering:
            for r in leaders[sec]:
                if r.get("drs") is not None:
                    cands.append((sec, r))
        # quitar duplicados (una accion puede estar en SMH e XLK): nos quedamos con el mayor drs
        best = {}
        for sec, r in cands:
            k = r["sym"]
            if k not in best or r["drs"] > best[k][1]["drs"]:
                best[k] = (sec, r)
        ranked = sorted(best.values(), key=lambda x: -x[1]["drs"])[:14]
        if ranked:
            erows = ""
            for sec, r in ranked:
                sweet = (r["drs"] >= 10 and 45 <= r["rs"] <= 92)
                dcol = "#2FD08A" if r["drs"] >= 10 else "#7BD88F" if r["drs"] >= 5 else "#93A4BC"
                qcol = QUAD[rrg.get(sec, {}).get("quad", "improving")][1]
                tag = "<span class='emtag'>emergente</span>" if sweet else ""
                erows += (f"<div class='emrow'><span class='em-sym'>{r['sym']}</span>"
                          f"<span class='em-sec' title='{esc(NAMES.get(sec,(sec,sec,''))[1])}'>"
                          f"<span class='dot' style='background:{qcol}'></span>{sec}</span>"
                          f"<span class='em-rs'>RS {r['rs']}</span>"
                          f"<span class='em-drs' style='color:{dcol}'>↑{r['drs']} en 3m</span>"
                          f"<span class='em-hi'>{r['hi']}% del máx.</span>{tag}</div>")
            html.append("<div class='panel full'><h2>Acciones emergentes (RS acelerando)</h2>"
                        "<div class='note'>Acciones cuyo <b>percentil RS sube más rápido</b> (últimos 3 meses), y solo en sectores que "
                        "están <b>entrando o liderando</b> en el RRG (donde fluye el dinero). La idea: pillarlas <b>mientras escalan</b>, "
                        "antes de que estén en RS 95+ y ya muy estiradas. <b>«emergente»</b> = sube fuerte (≥10) pero aún no está agotada "
                        "(RS 45–92). El «% del máx.» es lo cerca que está de su máximo de 52 semanas. No es asesoramiento.</div>"
                        + erows + "</div>")
    # fila completa: macro
    html.append("<div class='panel full'><h2>Regimen macro automatico: " + esc(regime["label"]) + "</h2>"
                "<div class='note'>Lectura orientativa deducida del propio mercado (bonos, credito, oro, dolar y apetito de riesgo).</div>"
                "<div class='conv'>"
                "<div><div class='kv'><span><b>Senales (variacion 13 semanas)</b></span><b></b></div>" + sig_rows + "</div>"
                "<div><div style='margin-bottom:10px'><h3 style='color:#2FD08A;font-size:11px'>Favorece</h3><div class='tags'>" + favor + "</div></div>"
                "<div><h3 style='color:#F4607A;font-size:11px'>Penaliza</h3><div class='tags'>" + hurt + "</div></div></div>"
                "</div>"
                "<div class='conv'>"
                "<div class='conv-box'><h3 style='color:#2FD08A'>Alta conviccion alcista</h3>"
                "<div class='note' style='margin:0 0 6px'>Regimen a favor + rotacion entrando/liderando:</div>"
                "<div class='tags'>" + buy_t + "</div></div>"
                "<div class='conv-box'><h3 style='color:#F4607A'>Evitar / reducir confirmado</h3>"
                "<div class='note' style='margin:0 0 6px'>Regimen en contra + rotacion saliendo/rezagada:</div>"
                "<div class='tags'>" + avoid_t + "</div></div>"
                "</div></div>")
    if fred_html:
        html.append("<div class='full'>" + fred_html + "</div>")
    html.append("</details>")
    html.insert(verdict_pos, verdict_html)
    # ===== PREVISION MACRO (reloj de inversion) — al final del todo =====
    try:
        _macro = fetch_macro()
        _mr = compute_macro_regime(_macro, ISM_MANUAL)
        if _macro and _mr:
            def _ar(it):
                d = it["dir"]; gu = it.get("goodup", True)
                if d > 0:
                    return "▲", ("#2FD08A" if gu else "#F4607A")
                if d < 0:
                    return "▼", ("#F4607A" if gu else "#2FD08A")
                return "▬", "#9FB0C8"
            def _rows(kind):
                r = ""
                for k, v in _macro.items():
                    if v["kind"] != kind:
                        continue
                    a, c = _ar(v)
                    r += (f"<tr><td class='se-l'>{esc(v['lab'])}</td>"
                          f"<td class='r'>{v['val']:g}{(' ' + v['unit']) if v['unit'] else ''}</td>"
                          f"<td class='r' style='color:{c}'>{a} {v['dir']:+g}</td></tr>")
                return r
            ism_row = (f"<tr><td class='se-l'>ISM manufacturas <span style='color:#5E708A;font-size:10px'>(manual)</span></td>"
                       f"<td class='r'>{ISM_MANUAL:g}</td>"
                       f"<td class='r' style='color:{'#2FD08A' if ISM_MANUAL >= 50 else '#F4607A'}'>{'expansión' if ISM_MANUAL >= 50 else 'contracción'}</td></tr>")
            conf_list, wait_list = [], []
            for s in _mr["favor"]:
                q = (rrg.get(s, {}) or {}).get("quad")
                (conf_list if q in ("leading", "improving") else wait_list).append(s)
            qcol = {"recuperacion": "#2FD08A", "sobrecalentamiento": "#F4B740",
                    "estanflacion": "#F4607A", "desinflacion": "#5AA9E6"}.get(_mr["quad"], "#9FB0C8")
            pr = _mr["pr"]
            esc_base = f"sigue <b>{_mr['label']}</b> → favorece {', '.join(_mr['favor'][:5])}"
            html.append(
                "<div class='panel full'><h2>Previsión macro — reloj de inversión</h2>"
                "<div class='note'>Cruzo la <b>dirección del crecimiento</b> (datos blandos, que se adelantan) con la <b>dirección de la inflación</b> "
                "(PCE/IPC subyacente) para situar el régimen, y miro dónde está entrando el dinero en tu propio panel. "
                "<b>Es un mapa de probabilidades por régimen, no una predicción.</b></div>"
                "<div class='scrollx'><table class='se'><tr><th class='se-l'>indicador</th><th class='r'>nivel</th><th class='r'>tendencia</th></tr>"
                "<tr><td colspan='3' style='color:#5E708A;font-size:11px;padding-top:6px'>DUROS (retrasados)</td></tr>"
                + _rows("hard") +
                "<tr><td colspan='3' style='color:#5E708A;font-size:11px;padding-top:6px'>BLANDOS (líderes)</td></tr>"
                + ism_row + _rows("soft") +
                "</table></div>"
                f"<div style='margin-top:12px;padding:10px;border:1px solid {qcol}55;border-radius:8px;background:{qcol}11'>"
                f"Crecimiento <b>{_mr['grow_lbl']}</b> · inflación <b>{_mr['infl_lbl']}</b> → "
                f"<b style='color:{qcol}'>{_mr['label']}</b>"
                + ("<br><span style='color:#F4B740;font-size:11px'>⚠ inflación plana, en la frontera entre regímenes — poca convicción, puede cambiar con el próximo dato</span>" if _mr.get("infl_weak") else "")
                + "<br>"
                f"<span style='color:#9FB0C8'>Playbook histórico:</span> a favor <b style='color:#2FD08A'>{', '.join(_mr['favor'])}</b> · "
                f"en contra <b style='color:#F4607A'>{', '.join(_mr['hurt'])}</b></div>"
                "<div class='note' style='margin-top:10px'><b>¿El dinero lo confirma?</b> "
                + (f"Ya en Líder/Mejorando: <b style='color:#2FD08A'>{', '.join(conf_list)}</b>. " if conf_list else "Aún ninguno de los favorecidos está en Líder/Mejorando. ")
                + (f"Aún no confirman: <span style='color:#9FB0C8'>{', '.join(wait_list)}</span>. " if wait_list else "")
                + "Actúa donde el régimen <b>y</b> el flujo coinciden.</div>"
                "<div class='scrollx' style='margin-top:10px'><table class='se'><tr><th class='se-l'>escenario</th><th class='r'>prob.*</th><th class='se-l'>implicación</th></tr>"
                f"<tr><td class='se-l'>Base</td><td class='r' style='font-weight:700'>~{pr['base']}%</td><td class='se-l'>{esc_base}</td></tr>"
                f"<tr><td class='se-l'>Alcista</td><td class='r'>~{pr['bull']}%</td><td class='se-l'>crecimiento reacelera con inflación contenida → giro a cíclicos/tech (XLK, XLY, XLF, IWM)</td></tr>"
                f"<tr><td class='se-l'>Bajista</td><td class='r'>~{pr['bear']}%</td><td class='se-l'>susto de crecimiento o inflación que reacelera → defensa (XLP, XLU, XLV, TLT, GLD)</td></tr>"
                "</table></div>"
                "<div class='note' style='margin-top:8px'><b>Línea de tiempo — qué dato rompe el empate:</b> "
                "el <b>PCE subyacente</b> (fin de mes) marca el eje inflación; las <b>nóminas</b> (1er viernes), el <b>ISM</b> (1er día hábil) y el <b>IPC</b> (mitad de mes) marcan el crecimiento. "
                "Cada build lo recalcula con el dato fresco.</div>"
                f"<div class='note' style='margin-top:8px;color:#5E708A'>*Probabilidades gruesas derivadas de la fuerza de la señal (claridad {round(_mr['conf'] * 100)}%), "
                "no de un modelo predictivo. La previsión macro es de poca pericia hasta para los bancos: úsala como marco, no como certeza. "
                "El <b>flujo manda</b>. No es asesoramiento.</div></div>")
        elif _macro is None:
            _k = _fred_key()
            if not _k:
                _diag = ("No encuentro la key. En el <b>PC</b>: pon <b>clave_fred.txt</b> (con la key dentro) en la misma carpeta "
                         "desde la que lanzas <code>python rotacion.py</code> y re-ejecuta. En <b>GitHub</b>: ponla en Secrets "
                         "(Settings → Secrets and variables → Actions → <b>FRED_API_KEY</b>).")
            else:
                _diag = (f"Key detectada (<b>{len(_k)} caracteres</b>) pero FRED no devolvió datos. Casi seguro es internet/firewall al "
                         "ejecutar o una key inválida. Pruébala en el navegador: "
                         "<code>https://api.stlouisfed.org/fred/series/observations?series_id=UNRATE&amp;api_key=TU_KEY&amp;file_type=json&amp;limit=1</code> "
                         "— si te devuelve JSON, la key va bien.")
            html.append("<div class='panel full'><h2>Previsión macro — reloj de inversión</h2>"
                        f"<div class='note'>⚙ {_diag}</div></div>")
    except Exception:
        pass
    # ===== V3 — VISTA OPERATIVA (cerrar Contexto, abrir Operativa) =====
    html.append("</div><div id='vista-op' style='display:none'>")

    # ===== MESA DE OPERACIONES: todo lo accionable de la semana en una pantalla =====
    try:
        _box = lambda titulo, cuerpo, bcol="#24344F": (f"<div style='flex:1 1 300px;min-width:280px;background:#0E1626;border:1px solid {bcol};"
                                                       f"border-radius:10px;padding:12px 14px'><div style='font-size:11px;color:#8FA3C0;"
                                                       f"text-transform:uppercase;letter-spacing:.6px;margin-bottom:8px'>{titulo}</div>{cuerpo}</div>")
        mesa = []
        # 1) semaforo + ordenes de cartera
        _fg_t = f" · F&G {fg_idx['score']}" if fg_idx else ""
        c1 = (f"<div style='font-size:14px;margin-bottom:8px'><b style='color:{light}'>{esc(sem_short)}</b> · {esc(reg_short)} · {esc(risk['label'])}{_fg_t}</div>")
        c1 += ("<div style='font-size:12px;margin-bottom:6px;padding:6px 8px;background:rgba(91,140,255,.08);border:1px solid #5B8CFF33;border-radius:6px'>"
               "CARTERA FINAL: <b style='color:#5B8CFF'>" + esc(", ".join(CARTERA_FINAL) if CARTERA_FINAL else "liquidez") + "</b>"
               "<span style='color:#8FA3C0;font-size:10px'> — la única lista que se opera; el resto son candidatos</span></div>")
        _ent = ", ".join(entering[:4]) or "—"
        _sal = ", ".join(leaving[:4]) or "—"
        c1 += (f"<div style='font-size:12px;line-height:1.7'>Entran (Mejorando): <b style='color:#4CC2E0'>{esc(_ent)}</b><br>"
               f"Salen (Debilitándose): <b style='color:#F4B740'>{esc(_sal)}</b>")
        if mi_plan and mi_plan.get("rows"):
            _vnd = [r for r in mi_plan["rows"] if str(r.get("act", "")).upper().startswith("VENDER")]
            _veur = sum(r["eur"] for r in _vnd if isinstance(r.get("eur"), (int, float)))
            _vt = ", ".join(r["tk"] for r in _vnd[:5]) + ("…" if len(_vnd) > 5 else "")
            if _vnd:
                c1 += (f"<br>Tu cartera en señal de salida: <b style='color:#F4607A'>{len(_vnd)} posiciones · ~{_veur:,.0f} €</b>"
                       f"<br><span style='color:#8FA3C0;font-size:11px'>{esc(_vt)}</span>").replace(",", ".")
            else:
                c1 += "<br>Tu cartera: <b style='color:#2FD08A'>sin señales de venta esta semana</b>"
        c1 += "</div>"
        mesa.append(_box("🚦 La semana en una línea + órdenes", c1, light + "55"))
        # 2) candidato del sistema
        if candidato:
            _t = candidato["top"]
            c2 = (f"<div style='font-size:16px'><b style='color:#5B8CFF'>{_t['stock']['sym']}</b> "
                  f"<span style='color:#8FA3C0;font-size:12px'>vía {_t['etf']}</span></div>"
                  f"<div style='font-size:11px;color:#B9C9E2;margin-top:6px;line-height:1.6'>{esc(_t['why'])}</div>"
                  f"<div style='font-size:10px;color:#5E708A;margin-top:6px'>se ejecuta el lunes si el viernes lo confirma · detalle en Contexto</div>")
            mesa.append(_box("🏆 Candidato de la semana (lo elige el sistema)", c2))
        # 3) tempranos: giro al alza sin extender, con flujo
        if early:
            c3 = ""
            for r in early[:5]:
                fl = (flow or {}).get(r["sym"], {}) or {}
                if fl.get("diverg") == "distribucion oculta":
                    tag, tcol = "⚠ sale dinero", "#F4607A"
                elif fl.get("obv_above") and fl.get("cmf_pos"):
                    tag, tcol = "✓ flujo confirma", "#2FD08A"
                elif fl.get("obv_above") or fl.get("cmf_pos"):
                    tag, tcol = "~ parcial", "#F4B740"
                else:
                    tag, tcol = "sin flujo aún", "#5E708A"
                c3 += (f"<div style='display:flex;justify-content:space-between;font-size:12px;margin:4px 0'>"
                       f"<span><b>{r['sym']}</b> <span style='color:#8FA3C0;font-size:10px'>ext {r['ext']}%</span></span>"
                       f"<span style='color:{tcol};font-size:11px'>{tag}</span></div>")
            c3 += "<div style='font-size:10px;color:#5E708A;margin-top:6px'>girando al alza y aún cerca de la media — la entrada barata, si el flujo acompaña</div>"
            mesa.append(_box("🌱 Tempranos — giro sin extender", c3))
        # 4) DURMIENTES: suelo + silencio + giro (unificado; sustituye a suelos y giros al alza)
        if suelo:
            _c_set = {c["sym"] for c in (contra_sigs or [])}
            c4 = ""
            for r in suelo[:6]:
                if r["sangra"]:
                    verd, vcol = "aún sangra", "#F4607A"
                elif r["despertando"] and r["sil"] >= 2:
                    verd, vcol = "🌅 DESPIERTA EN SILENCIO", "#2FD08A"
                elif r["despertando"]:
                    verd, vcol = "despertando", "#2FD08A"
                else:
                    verd, vcol = "dormido", "#9FB0C8"
                badge = " <span style='color:#7BD88F;font-size:9px;border:1px solid #7BD88F55;border-radius:3px;padding:0 3px'>0/3</span>" if r["sym"] in _c_set else ""
                _sq = "🤫" * max(r["sil"], 0)
                c4 += (f"<div style='display:flex;justify-content:space-between;font-size:12px;margin:4px 0'>"
                       f"<span><b>{r['sym']}</b>{badge} <span style='color:#8FA3C0;font-size:10px'>{r['pts']}/10 {_sq}"
                       + (f" · giro {r['vert']:.1f}×" if (r.get('vert') and (r.get('dmom') or 0) >= 1.5) else "") + "</span></span>"
                       f"<span style='color:{vcol};font-size:11px'>{verd}</span></div>")
            c4 += ("<div style='font-size:10px;color:#5E708A;margin-top:6px'>castigado + 🤫 silencio (nadie habla de él) + giro vertical con el precio aún quieto = "
                   "anticipación. Solo con cierre de viernes, flujo que no sale y tamaño de manga. Detalle completo en Contexto → 😴 DURMIENTES.</div>")
            mesa.append(_box("😴 Durmientes — suelo + silencio + giro", c4, "#7BD88F44"))
        # 5b) giro intradia de la ultima sesion (el patron de la trampa de apertura)
        if giro and giro.get("rows"):
            c5b = ""
            if giro.get("rotacion"):
                c5b += ("<div style='font-size:12px;margin-bottom:8px;padding:7px 9px;background:rgba(244,183,64,.1);"
                        "border:1px solid #F4B74055;border-radius:7px;color:#F4B740'><b>⚠ ROTACIÓN INTRADÍA DETECTADA</b>: "
                        "en la misma sesión vendieron lo caliente (gap arriba → cierre abajo) y compraron lo frío "
                        "(gap abajo → cierre arriba). Si se repite 2-3 sesiones, suele anticipar el relevo semanal.</div>")
            for g in giro["rows"][:6]:
                if g["sig"] == "bajista":
                    ic, col, lect = "🔻", "#F4607A", f"abrió {g['gap']:+.1f}%, cerró en el {g['pos']}% del rango — vendieron la subida"
                else:
                    ic, col, lect = "🔹", "#2FD08A", f"abrió {g['gap']:+.1f}%, cerró en el {g['pos']}% del rango — compraron el miedo"
                vtxt = f" · vol {g['vol_rel']}×" if g.get("vol_rel") else ""
                c5b += (f"<div style='font-size:12px;margin:4px 0'>{ic} <b>{g['sym']}</b> "
                        f"<span style='color:{col}'>{lect}</span><span style='color:#5E708A;font-size:10px'>{vtxt}</span></div>")
            c5b += (f"<div style='font-size:10px;color:#5E708A;margin-top:6px'>vela diaria del {esc(giro.get('fecha', ''))} · "
                    "aviso A CIERRE VENCIDO (sin datos intradía en vivo): léelo por la mañana antes de la apertura. "
                    "Observación diaria, ejecución el viernes — como siempre.</div>")
            mesa.append(_box("🔀 Giro intradía — quién vendió la subida y quién compró el miedo", c5b, "#F4B74055"))
        # 6) alertas de riesgo (margen + escalones)
        c6 = ""
        if apal:
            for b in apal["brokers"]:
                e5 = b["esc"].get(-5) or {}
                if e5.get("estado") and e5["estado"] != "ok":
                    c6 += (f"<div style='font-size:12px;margin:4px 0'>🚨 <b>{esc(b['broker'])}</b>: a S&P −5% → "
                           f"<b style='color:#F4607A'>{esc(e5['estado'])}</b>"
                           + (f" (nivel {e5['nivel_after']:.0f}%)" if e5.get("nivel_after") else "") + "</div>")
        if dd is not None:
            try:
                _fal = 5.0 - abs(dd)
                if 0 < _fal <= 3.5:
                    c6 += (f"<div style='font-size:12px;margin:4px 0'>⏳ Escalón −5% a <b>{_fal:.1f}%</b> de distancia — "
                           "¿la pólvora está líquida y FUERA de las cuentas con margen?</div>")
            except Exception:
                pass
        if c6:
            c6 += "<div style='font-size:10px;color:#5E708A;margin-top:6px'>detalle completo en Contexto → Apalancamiento consolidado</div>"
            mesa.append(_box("⚠️ Riesgo antes que rentabilidad", c6, "#F4607A55"))
        html.append("<div class='panel full'><h2>🎛️ Mesa de operaciones — la semana en una pantalla</h2>"
                    "<div class='note'>Lo accionable de todo el terminal, junto: semáforo y órdenes, el candidato, los <b>tempranos</b> (girando sin extender), "
                    "y los <b>😴 durmientes</b> (castigo + silencio + giro con el precio aún quieto — la anticipación, con la señal contraria 0/3 marcada). "
                    "El detalle y el porqué de cada cosa siguen en Contexto — esto es la chuleta del viernes por la tarde. No es asesoramiento.</div>"
                    "<div style='display:flex;flex-wrap:wrap;gap:12px'>" + "".join(mesa) + "</div>"
                    "<div class='note' style='margin-top:10px;color:#5E708A'>Ritual: 1) cierre del viernes confirmado → 2) órdenes de venta primero (liberan margen) → "
                    "3) rotaciones de la cartera → 4) candidato/tempranos solo si el flujo confirma → 5) suelos y 0/3 con tamaño de manga contraria, nunca apalancados.</div></div>")
    except Exception:
        pass

    # ===== RESUMEN SENCILLO: DONDE ESTAR (funde scoring + cuadrante + flujo) =====
    try:
        _estar, _evitar = [], []
        for r in (scores or []):
            sym = r["sym"]
            d = rrg.get(sym)
            if d is None:
                continue
            quad = d["quad"]
            fcmf = flow.get(sym, {}).get("cmf")
            if r.get("distrib"):
                _evitar.append((sym, "dinero saliendo"))
            elif quad in ("leading", "improving") and r["score"] >= 4 and (fcmf is None or fcmf >= 0):
                _estar.append({"sym": sym, "sc": r["score"], "quad": quad, "cmf": fcmf, "in_cart": sym in cartera_syms})
            elif r["score"] <= 2:
                _evitar.append((sym, f"débil {r['score']}/5"))
        _estar.sort(key=lambda x: (0 if x["in_cart"] else 1, -x["sc"], -(x["cmf"] or 0)))
        # mini-lineas: precio del ETF y fuerza vs mercado (ETF/SPY), ultimas ~10 semanas (como la estela)
        def _pv(sym, n=10):
            try:
                return list(df[sym].dropna().iloc[-n:])
            except Exception:
                return []
        def _rsv(sym, n=10):
            try:
                return list((df[sym] / df[BENCH]).dropna().iloc[-n:])
            except Exception:
                return []
        er = ""
        for e in _estar[:9]:
            nm = NAMES.get(e["sym"], (e["sym"], e["sym"], ""))[1]
            qn = QUAD.get(e["quad"], (e["quad"], ""))[0]
            star = "⭐ " if e["in_cart"] else ""
            cmftxt = (f"{e['cmf']:+.2f}" if e["cmf"] is not None else "—")
            base = "líder" if e["quad"] == "leading" else "girando al alza"
            flujo_txt = "dinero entrando" if (e["cmf"] or 0) > 0.03 else "flujo tibio (vigila)"
            verd = f"{base} + {flujo_txt}"
            vcol = "#2FD08A" if (e["cmf"] or 0) > 0.03 else "#F4B740"
            er += (f"<tr><td class='se-l'>{star}<b>{e['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span></td>"
                   f"<td class='r'>{e['sc']}/5</td><td class='r' style='font-size:11px'>{esc(qn)}</td>"
                   f"<td class='r' style='font-size:11px'>CMF {cmftxt}</td>"
                   f"<td class='r'>{_spark(_pv(e['sym']), w=62, h=18)}</td>"
                   f"<td class='r' style='font-size:11px;color:{vcol}'>{esc(verd)}</td></tr>")
        evtxt = ", ".join(f"<b>{s}</b> ({esc(w)})" for s, w in _evitar[:12])
        html.append("<div class='panel full'><h2>✅ Dónde estar — CANDIDATOS por puntuación (⭐ = en la CARTERA FINAL)</h2>"
                    "<div style='font-size:13px;margin:6px 0;padding:8px 10px;background:rgba(91,140,255,.08);border:1px solid #5B8CFF33;border-radius:7px'>"
                    "CARTERA FINAL de la semana: <b style='color:#5B8CFF'>" + esc(", ".join(CARTERA_FINAL) if CARTERA_FINAL else "liquidez") + "</b>"
                    "<span style='color:#8FA3C0;font-size:11px'> — esta tabla son los candidatos que pasan el corte de puntuación; la cartera además exige cuadrante, momentum absoluto, flujo y tope de posiciones. Si un 4/5 no lleva ⭐, algún filtro lo dejó fuera (lo dice la Cartera de Contexto).</span></div>"
                    "<div class='note'>Todo el panel en una tabla: los sectores donde <b>coinciden las tres cosas</b> — tendencia (Líder o Mejorando), "
                    "puntuación alta (≥4/5) y <b>el dinero entrando</b>. La ⭐ marca los que están en tu <b>Cartera</b> "
                    "(el <b>% exacto</b> en <b>Contexto → Cartera de la semana</b>). La columna <b>precio 8s</b> es la mini-línea del precio (verde sube, rojo baja). No es asesoramiento.</div>"
                    "<div class='scrollx'><table class='se'><tr><th class='se-l'>sector</th><th class='r'>nota</th>"
                    "<th class='r'>tendencia</th><th class='r'>flujo</th><th class='r'>precio 8s</th><th class='r'>por qué</th></tr>"
                    + (er or "<tr><td colspan='6' style='color:#9FB0C8'>Ninguno cumple las tres a la vez esta semana — mejor esperar.</td></tr>")
                    + "</table></div>"
                    + (f"<div class='note' style='margin-top:8px;color:#F4607A'>⛔ <b>Fuera / evitar:</b> {evtxt}.</div>" if evtxt else "")
                    + "</div>")

        # ===== MURAL: TODOS los sectores, estela (fuerza) vs precio =====
        def _lectura(pch, rch):
            if rch > 1 and pch > 2:   return "sube de verdad", "#2FD08A"
            if rch > 1 and abs(pch) <= 2:  return "posible acumulación (fuerza↑ precio plano)", "#5AA9E6"
            if rch > 1:               return "solo fuerza relativa", "#F4B740"
            if rch < -1 and abs(pch) <= 2: return "posible distribución (fuerza↓ precio plano)", "#F4B740"
            if pch > 2 and rch < -1:  return "sube pero pierde fuerza", "#F4B740"
            if pch < -2:              return "flojo", "#F4607A"
            return "plano", "#9FB0C8"
        _qorder = {"leading": 0, "improving": 1, "weakening": 2, "lagging": 3}
        _all = sorted(((s, d) for s, d in rrg.items() if s != BENCH),
                      key=lambda kv: (_qorder.get(kv[1]["quad"], 9), -kv[1].get("rel4", 0)))
        mu, _lastq = "", None
        for s, d in _all:
            pv, rv = _pv(s), _rsv(s)
            if len(pv) < 3:
                continue
            pch = (pv[-1] / pv[0] - 1) * 100 if pv[0] else 0
            rch = (rv[-1] / rv[0] - 1) * 100 if (len(rv) >= 2 and rv[0]) else 0
            vd, vc = _lectura(pch, rch)
            qn, qc = QUAD.get(d["quad"], (d["quad"], "#9FB0C8"))[0], {"leading": "#2FD08A", "improving": "#5AA9E6", "weakening": "#F4B740", "lagging": "#F4607A"}.get(d["quad"], "#9FB0C8")
            if d["quad"] != _lastq:
                mu += f"<tr><td colspan='5' style='color:{qc};font-weight:700;font-size:11px;padding-top:10px'>— {esc(qn)} —</td></tr>"
                _lastq = d["quad"]
            nm = NAMES.get(s, (s, s, ""))[1]
            mu += (f"<tr><td class='se-l'><b>{s}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span></td>"
                   f"<td class='r'>{_spark(pv, w=76, h=20)}</td>"
                   f"<td class='r'>{_spark(rv, w=76, h=20, color='#5B8CFF')}</td>"
                   f"<td class='r' style='font-size:11px'>{pch:+.1f}%</td>"
                   f"<td class='r' style='font-size:11px;color:{vc}'>{esc(vd)}</td></tr>")
        if mu:
            html.append("<div class='panel full'><h2>🧱 Mural — todos los sectores: estela vs precio</h2>"
                        "<div class='note'>Los ~8 últimas semanas de <b>todos</b> los ETF, para comparar de un vistazo. "
                        "<b>Precio</b> (verde/rojo) = qué hizo el ETF · <b>fuerza vs mercado</b> (azul) = su estela del RRG en línea · <b>% 8s</b> = lo que ha hecho el precio. "
                        "Agrupados por cuadrante (Líder arriba). Si la fuerza sube pero el precio está plano = <b>posible acumulación</b>; "
                        "si la fuerza baja con precio plano = <b>posible distribución</b>. No es asesoramiento.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'>ETF</th><th class='r'>precio 8s</th>"
                        "<th class='r'>fuerza 8s</th><th class='r'>% 8s</th><th class='r'>lectura</th></tr>" + mu + "</table></div></div>")

        # ===== PLAN DE SALIDA (media semanal como stop de tendencia) =====
        _exit_syms = list(dict.fromkeys(list(cartera_syms) + [e["sym"] for e in _estar]))
        xr = ""
        for sym in _exit_syms:
            try:
                ser = df[sym].dropna()
            except Exception:
                continue
            if len(ser) < SALIDA_MA_SEMANAS + 9:
                continue
            price = float(ser.iloc[-1])
            ma_s = ser.rolling(SALIDA_MA_SEMANAS).mean()
            ma = float(ma_s.iloc[-1])
            if ma <= 0:
                continue
            # capa 1: banda adaptativa = K x volatilidad semanal propia (26s). En laterales la banda absorbe el ruido.
            ret = ser.pct_change().iloc[-26:].dropna()
            sig = float(ret.std()) if len(ret) >= 8 else 0.02
            banda = max(0.01, SALIDA_BANDA_K * sig)
            # capa 3: stop duro (chandelier con cierres): pico 12s - K x volatilidad
            peak12 = float(ser.iloc[-12:].max())
            chand = peak12 * (1 - SALIDA_STOP_K * sig)
            # capa 2: confirmacion -> semanas consecutivas cerrando bajo la media (calculado del propio historico, sin estado)
            below = (ser < ma_s).dropna()
            n_below = 0
            for v in reversed(list(below)):
                if v:
                    n_below += 1
                else:
                    break
            pct = (price / ma - 1) * 100
            if price < chand:
                st, sc = "🔴 SALIR — stop duro (desplome desde el pico)", "#F4607A"
            elif price < ma * (1 - banda):
                st, sc = "🔴 SALIR — ruptura clara (fuera de banda)", "#F4607A"
            elif price < ma and n_below >= 2:
                st, sc = f"🔴 SALIR — {n_below}ª semana bajo la media (confirmado)", "#F4607A"
            elif price < ma:
                st, sc = "⚠ 1ª semana bajo media — confirma el próximo viernes", "#F4B740"
            elif pct < banda * 100:
                st, sc = "🟡 cerca de la media — vigila", "#F4B740"
            else:
                st, sc = "🟢 mantén", "#2FD08A"
            nm = NAMES.get(sym, (sym, sym, ""))[1]
            xr += (f"<tr><td class='se-l'><b>{sym}</b> <span style='color:var(--txt3);font-size:11px'>{esc(nm)}</span></td>"
                   f"<td class='r'>{_spark(list(ser.iloc[-12:]))}</td>"
                   f"<td class='r' style='font-size:11px'>{price:,.2f}</td>"
                   f"<td class='r' style='font-size:11px'>{ma:,.2f} <span style='color:var(--txt3)'>±{banda*100:.1f}%</span></td>"
                   f"<td class='r' style='font-size:11px'>{chand:,.2f}</td>"
                   f"<td class='r' style='font-size:11px;color:{sc};white-space:nowrap'>{esc(st)}</td></tr>")
        if xr:
            html.append("<div class='panel full'><h2>🛑 Plan de salida — para no devolver la plusvalía</h2>"
                        f"<div class='note'>Motor de salida en <b>3 capas anti-latigazo</b> (el fallo de una media simple es que en lateral te saca y mete sin parar): "
                        f"<b>① Banda adaptativa</b> — cerrar bajo la media de {SALIDA_MA_SEMANAS}s <i>dentro</i> de la banda (±K×volatilidad propia del ETF) NO dispara la venta; "
                        "en laterales el ruido queda absorbido. <b>② Confirmación</b> — bajo la media dentro de banda, hace falta la <b>2ª semana consecutiva</b> para SALIR (la 1ª es aviso). "
                        "<b>③ Stop duro</b> — pico de 12 semanas − K×volatilidad: si el precio cae ahí, SALIR sin esperar a la media (protege del desplome rápido). "
                        "Salir = ruptura clara fuera de banda, o 2ª semana confirmada, o stop duro. Ajustable en SALIDA_BANDA_K / SALIDA_STOP_K.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'>ETF</th><th class='r'>precio 12s</th>"
                        f"<th class='r'>precio</th><th class='r'>media {SALIDA_MA_SEMANAS}s ± banda</th><th class='r'>stop duro</th><th class='r'>señal</th></tr>"
                        + xr + "</table></div>"
                        "<div class='note' style='margin-top:8px;color:#F4B740'>⚠ <b>Para tu LABU (biotech x3) y cualquier apalancado:</b> NO uses la media del propio apalancado (el decay la distorsiona). "
                        "Usa la señal del <b>ETF base</b> — para LABU es <b>XBI</b>: cuando XBI cierre bajo su media, sal de LABU. Y en apalancado sé aún más estricto (media más corta, o salir al primer cierre por debajo), porque la vuelta con 3x + decay es brutal. No es asesoramiento.</div></div>")
    except Exception:
        pass

    try:
        QL = {"leading": "Líder", "improving": "Mejorando", "weakening": "Debilitándose", "lagging": "Rezagado"}
        QC = {"leading": "#2FD08A", "improving": "#5AA9E6", "weakening": "#F4B740", "lagging": "#F4607A"}
        GL = {"sector": "Sector", "subsector": "Subsector", "tech": "Tech", "limpia": "E.limpia", "materiales": "Materiales", "iainfra": "IA/infra", "internac": "Internac.", "refugio": "Refugio"}
        cand, warns = [], []
        for r in (scores or []):
            s = r["sym"]; sc = r["score"]; distrib = bool(r.get("distrib")); am = r.get("abs_mom", 0)
            q = (rrg.get(s, {}) or {}).get("quad")
            f = (flow or {}).get(s, {})
            money_in = bool(f.get("obv_above")) and bool(f.get("cmf_pos"))
            cmf_val = f.get("cmf", 0.0) or 0.0
            if (q in ("leading", "improving")) and sc >= 3 and not distrib and money_in and am > 0:
                cand.append((s, sc, q, am, cmf_val))
            elif distrib or (q == "weakening" and sc >= 3):
                warns.append((s, q, sc, "distribución oculta" if distrib else "debilitándose"))
        cand.sort(key=lambda c: -(c[4] or 0))   # ordenar por fuerza de flujo (CMF), de más a menos dinero entrando
        crows = ""
        for s, sc, q, am, cmf in cand:
            desc = NAMES.get(s, (s, "", ""))[1] or s
            grp = GL.get(GRUPO.get(s, ""), "")
            _fsc = fresh_stocks(leaders, s)
            lid = (", ".join((PHASE_INFO.get(r.get("phase"), ("",))[0] + " " + r["sym"] + f" ↑{r['drs']}").strip() for r in _fsc)) if _fsc else TOP_HOLDING.get(s, "")
            lid_lbl = "acciones" if _fsc else "líder"
            in_cart = s in cartera_syms
            badge = ("<span style='color:#2FD08A;font-size:10px;font-weight:700'> ✓ en cartera</span>"
                     if in_cart else "<span style='color:#5AA9E6;font-size:10px;font-weight:700'> 🆕 nueva</span>")
            cmf_col = "#2FD08A" if cmf >= 0.10 else ("#7BC47F" if cmf > 0 else "#9FB0C8")
            crows += (f"<tr><td class='se-l'><b>{s}</b>{badge} <span style='color:var(--txt3);font-size:11px'>{esc(desc)}</span>"
                      + (f"<br><span style='color:#5E708A;font-size:10px'>{lid_lbl}: {esc(lid)}</span>" if lid else "") + "</td>"
                      f"<td class='r'><span style='color:{QC.get(q, '#9FB0C8')}'>{QL.get(q, q)}</span></td>"
                      f"<td class='r' style='font-weight:700;color:{cmf_col}'>{cmf:+.2f}</td>"
                      f"<td class='r' style='font-weight:700;color:{'#2FD08A' if sc >= 4 else '#F4B740'}'>{sc}/5</td>"
                      f"<td class='r' style='color:#2FD08A'>+{am:g}%</td>"
                      f"<td class='r' style='color:#5E708A;font-size:11px'>{grp}</td></tr>")
        if not crows:
            crows = "<tr><td colspan='6' style='color:#9FB0C8;padding:12px'>Ningún candidato pasa todos los filtros ahora mismo. En seco: no fuerces entradas.</td></tr>"
        # ---- 3 VÍAS DE ENTRAR por cada candidato: ETF normal / apalancado / cesto sintético ----
        destr = ""
        for s, sc, q, am, cmf in cand:
            rl = (leaders or {}).get(s)
            if not rl:
                continue
            lev = LEVERAGED.get(s)
            if lev:
                via2 = f"<b>{lev[0]}</b> ({lev[1]}) <span style='color:#F4B740;font-size:10px'>⚠ decay diario</span>"
            else:
                via2 = "<span style='color:#9FB0C8'>sin ETF apalancado limpio → vía <b>CFD en XTB</b> sobre las acciones</span>"
            basket = [rr for rr in rl if rr.get("rs", 0) >= SINT_MIN_RS and (rr.get("drs") or 0) > 0 and rr.get("hi", 100) < SINT_MAX_HI][:SINT_TOP]
            if basket:
                wgt = round(100.0 / len(basket))
                chips = " · ".join(f"{PHASE_INFO.get(b.get('phase'),('',))[0]} <b>{b['sym']}</b> {wgt}%" for b in basket)
                nota = "(equiponderado)" if len(basket) >= SINT_MIN_N else "(pocas cumplen hoy; cesto fino)"
                via3 = f"{chips} <span style='color:#5E708A;font-size:10px'>{nota}</span>"
            else:
                fs = fresh_stocks(leaders, s, n=3, max_hi=97)
                if fs:
                    chips2 = " · ".join(f"{PHASE_INFO.get(r.get('phase'),('',))[0]} <b>{r['sym']}</b> RS{r['rs']} ↑{r['drs']} <span style='color:#5E708A;font-size:10px'>({r['hi']}% máx)</span>" for r in fs)
                    via3 = f"{chips2} <span style='color:#5E708A;font-size:10px'>(las que más aceleran y menos estiradas; revisa cada semana)</span>"
                else:
                    via3 = "<span style='color:#9FB0C8'>sin acciones claras hoy → mejor el ETF o esperar</span>"
            trows = ""
            for j, rr in enumerate(rl[:8]):
                sym2 = rr["sym"]; rs2 = rr.get("rs", 0); hi2 = rr.get("hi", 0); dr = rr.get("drs")
                tag = " 🔥" if (rs2 >= 70 and (dr or 0) > 0) else ""
                if hi2 >= SINT_MAX_HI:
                    tag += " <span style='color:#F4B740;font-size:10px'>⚠ extendida</span>"
                if (dr or 0) > 0:
                    acc = f"<span style='color:#2FD08A'>⚡ +{dr}</span>"
                elif dr is not None and dr < 0:
                    acc = f"<span style='color:#F4607A'>▼ {dr}</span>"
                else:
                    acc = "—"
                in_b = any(b["sym"] == sym2 for b in basket)
                stl = "font-weight:700;color:#2FD08A" if in_b else ""
                ph2 = PHASE_INFO.get(rr.get("phase"), ("",))[0]
                trows += (f"<tr><td class='se-l' style='{stl}'>{ph2} {sym2}{' 🧺' if in_b else ''}{tag}</td>"
                          f"<td class='r'>{rs2}</td><td class='r'>{hi2}%</td><td class='r'>{acc}</td></tr>")
            desc = NAMES.get(s, (s, "", ""))[1] or s
            destr += (
                f"<div style='margin:14px 0 6px;padding:10px;border:1px solid var(--line);border-radius:8px'>"
                f"<div style='font-weight:700;margin-bottom:6px'>{s} · <span style='color:var(--txt3);font-weight:400'>{esc(desc)}</span> — 3 vías de entrar:</div>"
                f"<div class='note' style='margin:2px 0'>① <b>ETF</b>: {s}</div>"
                f"<div class='note' style='margin:2px 0'>② <b>Apalancado</b>: {via2}</div>"
                f"<div class='note' style='margin:2px 0'>③ <b>Sintético</b> (fuertes sin estar en máximos): {via3}</div>"
                f"<details style='margin-top:6px'><summary style='cursor:pointer;color:#9FB0C8;font-size:12px'>ver ranking completo de {s} (🧺 = entra al cesto)</summary>"
                "<div class='scrollx'><table class='se'><tr><th class='se-l'>empresa</th><th class='r'>percentil</th><th class='r'>% máx 52s</th><th class='r'>acel 3m</th></tr>"
                + trows + "</table></div></details></div>")
        destr_block = (("<div class='note' style='margin-top:16px'><b>🧺 Cómo entrar en cada candidato — 3 vías, tú eliges:</b> "
                        "el <b>ETF</b> normal, su <b>apalancado</b> (⚠ con decay diario, tu mayor riesgo en lateral), "
                        "o un <b>cesto sintético</b> con las acciones más fuertes que <b>aún no estén pegadas a máximos</b> "
                        f"(percentil ≥ {SINT_MIN_RS}, acelerando, por debajo del {SINT_MAX_HI}% de máximos — el filtro que evita comprar la punta, como pasó con MLI).</div>"
                        + destr
                        + "<div class='note' style='margin-top:6px;color:#5E708A'>El cesto reduce el riesgo de una sola acción, pero 4-5 mid-caps siguen siendo más concentrado que el ETF entero. Y es momentum: lo fuerte hoy puede revertir. No es asesoramiento.</div>") if destr else "")
        wrows = ""
        for s, q, sc, why in warns[:10]:
            desc = NAMES.get(s, (s, "", ""))[1] or s
            wrows += (f"<tr><td class='se-l'><b>{s}</b> <span style='color:var(--txt3);font-size:11px'>{esc(desc)}</span></td>"
                      f"<td class='r' style='color:#F4607A'>{esc(why)}</td></tr>")
        op = (
            "<div class='panel full'><h2>🎯 Operativa — candidatos ya filtrados</h2>"
            "<div class='note'>Lista corta de <b>posibles entradas</b> que pasan <b>todos</b> los filtros a la vez: "
            "cuadrante <b>Líder o Mejorando</b> + puntuación ≥ 3/5 + <b>el flujo confirma</b> (OBV y CMF a favor) + "
            "sin distribución oculta + ganando dinero a 3 meses. No es una orden de compra; es lo que merece mirar. "
            "<b style='color:#2FD08A'>✓ en cartera</b> = ya está en tu cartera de la semana · <b style='color:#5AA9E6'>🆕 nueva</b> = entrada fresca con flujo confirmando que aún no tienes. "
            "<b>Ordenado por flujo (CMF)</b>: arriba = donde más dinero está entrando ahora. Ojo: el CMF más alto no es automáticamente la mejor entrada (puede estar ya extendida) — cruza con ✓/🆕 y el destripado.</div>"
            "<div class='scrollx'><table class='se'><tr><th class='se-l'>candidato</th><th class='r'>cuadrante</th><th class='r'>flujo (CMF)</th><th class='r'>nota</th><th class='r'>mom 3m</th><th class='r'>grupo</th></tr>"
            + crows + "</table></div>"
            + destr_block
            + (("<div class='note' style='margin-top:14px;color:#F4607A'><b>⚠ Ojo / evitar (no entrar):</b></div>"
                "<div class='scrollx'><table class='se'>" + wrows + "</table></div>") if wrows else "")
            + "<div class='note' style='margin-top:14px'><b>Cómo ejecutar (tu rutina):</b> decides en el <b>cierre del viernes</b> y ejecutas el lunes; "
              "tamaño por <b>volatilidad inversa</b> (menos en lo que más se mueve); <b>stop</b> bajo el mínimo de las últimas semanas o un % fijo que aguantes; "
              "y si está en <b>vertical</b> (mom 3m muy alto), mejor esperar una pausa que perseguir la punta. No es asesoramiento.</div>"
            "<div class='note' style='margin-top:8px;color:#5E708A'>Próximo paso (Fase 2): aquí se conectará tu <b>cartera</b> (archivo cartera.json) para mapear tus posiciones a mantener/añadir/recortar/salir y ver el saldo por broker.</div>"
            "</div>")
        html.append(op)
    except Exception:
        pass
    html.append("</div>")

    # ===== V-PRO — TERMINAL PRO (estetica de terminal profesional: negro, ambar, monoespaciada, densa) =====
    html.append("<div id='vista-bbg' style='display:none'>")
    _bbg_mark = len(html)
    try:
        AMB, GRN, RED, GRY, CYN = "#FFB000", "#00E676", "#FF5252", "#8A96A8", "#4CC2E0"
        html.append(
            "<style>"
            ".bbgp{background:#050505;border:1px solid #2A2A2A;border-radius:4px;padding:0;margin:0 0 10px 0;"
            "font-family:'IBM Plex Mono','Cascadia Mono','Consolas','Courier New',monospace;overflow:hidden}"
            ".bbgh{background:#141414;color:#FFB000;font-size:11px;letter-spacing:1.5px;padding:6px 10px;"
            "border-bottom:1px solid #2A2A2A;font-weight:700}"
            ".bbgb{padding:8px 10px;font-size:12px;line-height:1.75;color:#D8DEE9}"
            ".bbgb table{width:100%;border-collapse:collapse;font-size:11.5px}"
            ".bbgb th{color:#8A96A8;text-align:right;font-weight:400;border-bottom:1px solid #222;padding:2px 6px;font-size:10px;letter-spacing:.5px}"
            ".bbgb th:first-child,.bbgb td:first-child{text-align:left}"
            ".bbgb td{text-align:right;padding:2.5px 6px;border-bottom:1px solid #141414;white-space:nowrap}"
            ".bbgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:10px;grid-column:1/-1}"
            ".bbgtapewrap{overflow:hidden;white-space:nowrap;background:#050505;border:1px solid #2A2A2A;border-radius:4px;"
            "padding:7px 0;margin-bottom:10px;grid-column:1/-1}"
            ".bbgtape{display:inline-block;animation:bbgtape 55s linear infinite;font-family:'Consolas','Courier New',monospace;font-size:12px}"
            "@keyframes bbgtape{0%{transform:translateX(0)}100%{transform:translateX(-50%)}}"
            ".bbgfk{display:inline-block;background:#141414;border:1px solid #333;color:#FFB000;font-size:10px;"
            "padding:3px 10px;border-radius:3px;margin-right:6px;cursor:pointer;letter-spacing:1px}"
            ".bbgfk:hover{background:#FFB000;color:#000}"
            "</style>")
        def _ser(sym):
            try:
                if sym == "QQQ" and sym not in df.columns and nq_close is not None:
                    s = nq_close.dropna()              # QQQ llega por nq_close, no por df
                else:
                    s = df[sym].dropna()
                return s if len(s) else None
            except Exception:
                return None
        def _chg(sym, n=1):
            s = _ser(sym)
            if s is None or len(s) <= n:
                return None
            try:
                return float(s.iloc[-1] / s.iloc[-1 - n] - 1) * 100
            except Exception:
                return None
        def _ytd(sym):
            s = _ser(sym)
            if s is None or len(s) < 2:
                return None
            try:
                y = s.index[-1].year
                prev = s[s.index.year < y]
                base = prev.iloc[-1] if len(prev) else s.iloc[0]
                return float(s.iloc[-1] / base - 1) * 100
            except Exception:
                return None
        def _fp(v, dec=1):
            if v is None:
                return f"<span style='color:{GRY}'>—</span>"
            return f"<span style='color:{GRN if v >= 0 else RED}'>{v:+.{dec}f}%</span>"
        def _bsp(sym, n=14):
            s = _ser(sym)
            if s is None or len(s) < 4:
                return ""
            v = list(s.iloc[-n:])
            mn, mx = min(v), max(v)
            rng = (mx - mn) or 1.0
            blocks = "▁▂▃▄▅▆▇█"
            c = GRN if v[-1] >= v[0] else RED
            return ("<span style='color:%s;letter-spacing:1px;font-size:10px'>" % c
                    + "".join(blocks[int((x - mn) / rng * 7)] for x in v) + "</span>")
        _mod = lambda titulo, cuerpo: f"<div class='bbgp'><div class='bbgh'>{titulo}</div><div class='bbgb'>{cuerpo}</div></div>"
        # --- CINTA DE COTIZACIONES ---
        tape = ""
        for s in [x for x in rrg.keys() if x in df.columns]:
            c = _chg(s, 1)
            if c is None:
                continue
            col = GRN if c >= 0 else RED
            arrow = "▲" if c >= 0 else "▼"
            tape += f"<span style='color:#E8E8E8;margin-left:26px'>{s}</span> <span style='color:{col}'>{arrow}{abs(c):.1f}%</span>"
        html.append(f"<div class='bbgtapewrap'><div class='bbgtape'>{tape}{tape}</div></div>")
        # --- CABECERA + TECLAS DE FUNCION ---
        _rk = risk.get("label", "—") if isinstance(risk, dict) else str(risk)
        html.append("<div class='bbgp' style='grid-column:1/-1'><div class='bbgb' style='display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;align-items:center'>"
                    f"<span style='color:{AMB};font-size:14px;font-weight:700;letter-spacing:2px'>PeVR TERMINAL <span style='color:#555'>|</span> PRO</span>"
                    f"<span style='color:{GRY};font-size:11px'>cierre {last_lbl} · {esc(sem_short)} · {esc(reg_short)} · {esc(_rk)}"
                    + (f" · F&G {fg_idx['score']}" if fg_idx else "") + "</span>"
                    "<span><span class='bbgfk' onclick=\"document.querySelectorAll('.mainview')[0].click()\">F1 CONTEXTO</span>"
                    "<span class='bbgfk' onclick=\"document.querySelectorAll('.mainview')[1].click()\">F2 OPERATIVA</span>"
                    "<span class='bbgfk' onclick=\"document.querySelectorAll('.mainview')[2].click()\">F3 VIGILANCIA</span>"
                    "<span class='bbgfk' onclick='descargarPDF()'>F9 PDF</span></span>"
                    "</div></div>")
        html.append("<div class='bbgrid'>")
        # --- MODULO 1: MARKET MONITOR ---
        mm = "<table><tr><th>TICKER</th><th>1S</th><th>4S</th><th>12S</th><th>YTD</th><th>14 SEM</th></tr>"
        for s in ["SPY", "QQQ", "IWM", "TLT", "GLD", "UUP", "HYG", "IBIT", "EURUSD", "FXI", "KWEB", "EWP"]:
            if s not in df.columns:
                continue
            mm += (f"<tr><td style='color:{AMB};font-weight:700'>{s}</td><td>{_fp(_chg(s, 1))}</td>"
                   f"<td>{_fp(_chg(s, 4))}</td><td>{_fp(_chg(s, 12))}</td><td>{_fp(_ytd(s))}</td><td>{_bsp(s)}</td></tr>")
        mm += "</table>"
        html.append(_mod("MARKET MONITOR — ÍNDICES · REFUGIO · FX", mm))
        # --- MODULO 2: FLOW MONITOR (CMF) ---
        _fl = sorted([(s, f) for s, f in (flow or {}).items() if f.get("cmf") is not None and s in rrg],
                     key=lambda x: -x[1]["cmf"])
        fm = "<table><tr><th>ENTRA $</th><th>CMF</th><th>VOL</th><th></th><th>SALE $</th><th>CMF</th><th>VOL</th><th></th></tr>"
        _in = [x for x in _fl if x[1]["cmf"] > 0.05][:8]
        _out = [x for x in _fl if x[1]["cmf"] < -0.05][-8:][::-1]
        for i in range(max(len(_in), len(_out))):
            fm += "<tr>"
            for grp, col in ((_in, GRN), (_out, RED)):
                if i < len(grp):
                    s, f = grp[i]
                    vr = f.get("vol_rel5", f.get("vol_rel"))
                    dv = f"<span style='color:{AMB}'>DIV!</span>" if f.get("diverg") == "distribucion oculta" else ("↑OBV" if f.get("obv_above") else "")
                    fm += (f"<td style='color:{col};font-weight:700'>{s}</td><td style='color:{col}'>{f['cmf']:+.2f}</td>"
                           f"<td style='color:{GRY}'>{(str(round(vr, 2)) + 'x') if vr is not None else '—'}</td><td style='font-size:10px'>{dv}</td>")
                else:
                    fm += "<td></td><td></td><td></td><td></td>"
            fm += "</tr>"
        fm += "</table><div style='font-size:10px;color:#666;margin-top:4px'>CMF 20s · umbral ±0.05 · DIV! = distribución oculta (precio sube, dinero sale)</div>"
        html.append(_mod("FLOW MONITOR — DÓNDE ENTRA Y SALE EL DINERO", fm))
        # --- MODULO 3: ROTATION READOUT (RRG) ---
        _qcount = {"leading": [], "improving": [], "weakening": [], "lagging": []}
        _movers = []
        for s, d in rrg.items():
            if s == BENCH:
                continue
            if d["quad"] in _qcount:
                _qcount[d["quad"]].append(s)
            tail = d.get("tail") or []
            if len(tail) >= 4:
                _movers.append((s, tail[-1][1] - tail[-4][1]))
        _movers.sort(key=lambda x: -x[1])
        _qlbl = {"leading": ("LÍDER", GRN), "improving": ("MEJORANDO", CYN), "weakening": ("DEBILITÁNDOSE", AMB), "lagging": ("REZAGADO", RED)}
        rr = "<table><tr><th>CUADRANTE</th><th>N</th><th style='text-align:left'>MIEMBROS</th></tr>"
        for q in ("leading", "improving", "weakening", "lagging"):
            lbl, col = _qlbl[q]
            mem = " ".join(_qcount[q][:11]) + ("…" if len(_qcount[q]) > 11 else "")
            rr += f"<tr><td style='color:{col};font-weight:700'>{lbl}</td><td>{len(_qcount[q])}</td><td style='text-align:left;color:#BFC7D5;font-size:10.5px'>{mem}</td></tr>"
        rr += "</table>"
        up5 = " · ".join(f"<span style='color:{GRN}'>{s} +{v:.1f}</span>" for s, v in _movers[:5])
        dn5 = " · ".join(f"<span style='color:{RED}'>{s} {v:.1f}</span>" for s, v in _movers[-5:][::-1])
        rr += (f"<div style='margin-top:6px;font-size:11px'><span style='color:{GRY}'>IMPULSO 3S ▲</span> {up5}<br>"
               f"<span style='color:{GRY}'>IMPULSO 3S ▼</span> {dn5}</div>")
        html.append(_mod("ROTATION READOUT — RRG EN TEXTO", rr))
        # --- MODULO 4: SCORE BOARD ---
        sb = "<table><tr><th>RK</th><th style='text-align:left'>ETF</th><th>SCORE</th><th>SEÑALES</th><th>CMF</th><th>Q</th></tr>"
        _ss = sorted(scores or [], key=lambda r: -r["score"])
        for i, r in enumerate(_ss[:10], 1):
            dots = "".join("●" if v else "○" for _, v in r["parts"])
            cmf = (flow or {}).get(r["sym"], {}).get("cmf")
            q = rrg.get(r["sym"], {}).get("quad", "")
            qc = _qlbl.get(q, ("—", GRY))
            di = f" <span style='color:{RED}'>✕DIV</span>" if r.get("distrib") else ""
            sb += (f"<tr><td style='color:{GRY}'>{i:02d}</td><td style='text-align:left;color:{AMB};font-weight:700'>{r['sym']}{di}</td>"
                   f"<td>{r['score']}/5</td><td style='letter-spacing:2px;color:{GRN}'>{dots}</td>"
                   f"<td style='color:{GRN if (cmf or 0) > 0 else RED}'>{(f'{cmf:+.2f}' if cmf is not None else '—')}</td>"
                   f"<td style='color:{qc[1]};font-size:10px'>{qc[0][:4]}</td></tr>")
        sb += "</table><div style='font-size:10px;color:#666;margin-top:4px'>● tendencia · fuerza · impulso · flujo · amplitud — ✕DIV excluido por distribución oculta</div>"
        html.append(_mod("SCORE BOARD — RANKING DEL SISTEMA", sb))
        # --- MODULO 5: SENTIMENT & INTERNALS ---
        si = ""
        if fg_idx:
            try:
                _fgv = float(fg_idx["score"])
                fgc = RED if _fgv <= 25 else AMB if _fgv <= 45 else GRN if _fgv < 75 else AMB
                bar_n = max(0, min(20, int(round(_fgv / 5))))
                si += (f"<div>FEAR &amp; GREED <span style='color:{fgc};font-weight:700'>{_fgv:.0f}</span> "
                       f"<span style='color:{fgc}'>{'█' * bar_n}</span><span style='color:#222'>{'█' * (20 - bar_n)}</span> "
                       f"<span style='color:{GRY};font-size:10px'>{esc(str(fg_idx.get('rating', '')))} · 1s:{fg_idx.get('week', '—')} 1m:{fg_idx.get('month', '—')} 1a:{fg_idx.get('year', '—')}</span></div>")
            except Exception:
                pass
        if isinstance(risk, dict):
            si += f"<div>RISK APPETITE <span style='color:{AMB};font-weight:700'>{esc(str(risk.get('label', '—')))}</span> <span style='color:{GRY}'>({float(risk.get('score', 0)):+.0f})</span></div>"
        si += f"<div>RÉGIMEN <span style='color:{AMB}'>{esc(reg_short)}</span> · SEMÁFORO <span style='color:{light};font-weight:700'>{esc(sem_short)}</span></div>"
        if dd is not None:
            try:
                si += f"<div>SPY vs MÁXIMO <span style='color:{RED if dd <= -3 else GRY}'>{dd:+.1f}%</span> · escalones plan: −5/−10/−20</div>"
            except Exception:
                pass
        if spy_flow:
            _sc = spy_flow.get("cmf")
            _so = spy_flow.get("obv_above")
            _sc_col = GRN if (_sc or 0) > 0 else RED
            _sc_val = _sc if _sc is not None else 0
            _obv_txt = ("<span style=" + '"' + "color:" + GRN + '"' + ">" + '↑' + " sobre media</span>") if _so else ("<span style=" + '"' + "color:" + RED + '"' + ">" + '↓' + " bajo media</span>")
            si += (f"<div>SPY FLOW CMF <span style='color:{_sc_col}'>{_sc_val:+.2f}</span>"
                   f" · OBV {_obv_txt}"
                   + (f" · <span style='color:{AMB}'>DISTRIBUCIÓN</span>" if spy_flow.get("diverg") == "distribucion oculta" else "") + "</div>")
        _nlead = len(_qcount["leading"]) + len(_qcount["improving"])
        _ntot = sum(len(v) for v in _qcount.values()) or 1
        si += f"<div>AMPLITUD RRG <span style='color:{GRN if _nlead / _ntot >= .5 else AMB}'>{_nlead}/{_ntot}</span> en Líder+Mejorando ({100 * _nlead / _ntot:.0f}%)</div>"
        html.append(_mod("SENTIMENT & INTERNALS", si))
        # --- MODULO 6: PORTFOLIO DESK ---
        if apal:
            pd_ = (f"<div>EQUITY <span style='color:{AMB};font-weight:700'>{apal['tot_eur']:,.0f} €</span>"
                   f" · EXPOSICIÓN {apal['tot_expo']:,.0f} €"
                   f" · LEV <span style='color:{RED if apal['lev_ef'] >= 1.6 else AMB}'>{apal['lev_ef']:.2f}x</span></div>").replace(",", ".")
            pd_ += "<table><tr><th style='text-align:left'>BROKER</th><th>EQ €</th><th>LEV</th><th>S&P−5%</th><th>ESTADO</th></tr>"
            for b in apal["brokers"]:
                e5 = b["esc"].get(-5) or {}
                st5 = e5.get("estado", "ok")
                stc = RED if st5 not in ("ok",) else GRN
                pd_ += (f"<tr><td style='text-align:left;color:{AMB}'>{esc(b['broker'])}</td>"
                        f"<td>{b['equity']:,.0f}</td><td>{b['lev_ef']:.2f}x</td>"
                        f"<td style='color:{RED}'>{e5.get('loss', 0):+,.0f}</td>"
                        f"<td style='color:{stc};font-size:10px'>{esc(st5.upper())}</td></tr>").replace(",", ".")
            pd_ += "</table>"
            if mi_plan and mi_plan.get("rows"):
                _vnd = [r for r in mi_plan["rows"] if str(r.get("act", "")).upper().startswith("VENDER")]
                _veur = sum(r["eur"] for r in _vnd if isinstance(r.get("eur"), (int, float)))
                _mnt = [r for r in mi_plan["rows"] if r.get("act") == "MANTENER"]
                _meur = sum(r["eur"] for r in _mnt if isinstance(r.get("eur"), (int, float)))
                _tot = mi_plan.get("total") or 1
                pd_ += (f"<div style='margin-top:4px'>ALINEACIÓN <span style='color:{GRN}'>{100 * _meur / _tot:.0f}% mantener</span> · "
                        f"<span style='color:{RED}'>{len(_vnd)} pos en señal de salida (~{_veur:,.0f} €)</span></div>").replace(",", ".")
            _top = sorted(apal["rows"], key=lambda r: -r["expo"])[:6]
            pd_ += ("<div style='font-size:10.5px;color:#BFC7D5;margin-top:2px'>TOP EXPO: "
                    + " · ".join(f"{r['tk']} {r['expo']:,.0f}€".replace(",", ".") for r in _top) + "</div>")
            html.append(_mod("PORTFOLIO DESK — LOS 3 BROKERS", pd_))
        # --- MODULO 6b: SEMIS DESK — poker de rebote ---
        if semis:
            _card = lambda k, v, c="#D8DEE9": (f"<span style='display:inline-block;background:#101010;border:1px solid #333;"
                                               f"border-radius:5px;padding:4px 8px;margin:2px 3px 2px 0;font-size:10.5px'>"
                                               f"<span style='color:#777'>{k}</span> <b style='color:{c}'>{v}</b></span>")
            sd = ""
            # LA MANO
            _qs = {"leading": ("LÍDER", GRN), "improving": ("MEJORANDO", CYN), "weakening": ("DEBILITÁNDOSE", AMB), "lagging": ("REZAGADO", RED)}
            _q = _qs.get(semis.get("quad"), ("—", GRY))
            sd += "<div style='color:#777;font-size:10px;letter-spacing:1px;margin-bottom:3px'>LA MANO (estado actual)</div><div>"
            sd += _card("cuadrante", _q[0], _q[1])
            if semis.get("score") is not None:
                sd += _card("score", f"{semis['score']}/5", GRN if semis["score"] >= 4 else AMB if semis["score"] >= 3 else RED)
            sd += _card("vs máx 52s", f"{semis['dd52']:+.0f}%", RED if semis["dd52"] <= -10 else GRY)
            sd += _card("z 4 sem", f"{semis['z4']:+.1f}", RED if semis["z4"] <= -1.5 else GRY)
            if semis.get("vs40") is not None:
                sd += _card("vs media 40s", f"{semis['vs40']:+.1f}%", GRN if semis["vs40"] > 0 else RED)
            _cmf = semis.get("cmf")
            if _cmf is not None:
                sd += _card("CMF", f"{_cmf:+.2f}", GRN if _cmf > 0.05 else RED if _cmf < -0.05 else GRY)
            if semis.get("streak"):
                sd += _card("racha", f"{semis['streak']} sem rojas", AMB)
            if semis.get("wash") is not None:
                sd += _card("washout comp.", f"{semis['wash']}%", AMB if semis["wash"] >= 50 else GRY)
            if semis.get("giro"):
                _gg = semis["giro"]
                sd += _card("giro intradía", "compraron el miedo" if _gg["sig"] == "alcista" else "vendieron la subida",
                            GRN if _gg["sig"] == "alcista" else RED)
            if semis.get("distrib"):
                sd += _card("⚠", "DISTRIBUCIÓN OCULTA", RED)
            sd += "</div>"
            # REBOTE SCORE
            _pc = GRN if semis["pts"] >= 8 else AMB if semis["pts"] >= 5 else GRY
            _verd = ("MANO FUERTE — setup de rebote sobre la mesa" if semis["pts"] >= 8 else
                     "proyecto de mano — faltan cartas" if semis["pts"] >= 5 else
                     "no hay mano — no fuerces la entrada")
            _bar = int(round(semis["pts"] / 10 * 20))
            sd += (f"<div style='margin:8px 0'>REBOTE SCORE <b style='color:{_pc};font-size:15px'>{semis['pts']}</b>"
                   f"<span style='color:#555;font-size:10px'>/10</span> "
                   f"<span style='color:{_pc}'>{'█' * _bar}</span><span style='color:#1c1c1c'>{'█' * (20 - _bar)}</span> "
                   f"<span style='color:{_pc};font-size:11px'>{_verd}</span></div>")
            if semis.get("det"):
                sd += f"<div style='font-size:10.5px;color:#9AA7B8;margin-bottom:8px'>{esc(' · '.join(semis['det']))}</div>"
            # LA MESA
            if semis.get("tbl"):
                sd += ("<div style='color:#777;font-size:10px;letter-spacing:1px;margin:6px 0 3px'>LA MESA — % de veces que estaba MÁS ARRIBA 4 semanas después "
                       f"(histórico propio, {semis['n_hist']} sem)</div>")
                sd += "<table><tr><th style='text-align:left'>CAÍDA DESDE MÁX</th><th>PROB.</th><th>IC 95%</th><th>MEDIA 4S</th><th>N</th></tr>"
                for t in semis["tbl"]:
                    mark = f" <b style='color:{AMB}'>◄ AHORA</b>" if t["now"] else ""
                    _tc = GRN if t["p"] >= 60 else AMB if t["p"] >= 50 else RED
                    sd += (f"<tr><td style='text-align:left'>{t['lbl']}{mark}</td>"
                           f"<td style='color:{_tc};font-weight:700'>{t['p']}%</td>"
                           f"<td style='color:#667'>{t['lo']}–{t['hi']}%</td>"
                           f"<td>{_fp(t['avg'])}</td><td style='color:#667'>{t['n']}</td></tr>")
                sd += "</table>"
            if semis.get("zview"):
                zv = semis["zview"]
                _zn = f" <b style='color:{AMB}'>◄ AHORA</b>" if zv["now"] else ""
                sd += (f"<div style='font-size:11px;margin-top:4px'>SOBREVENTA (z≤−1.5){_zn}: rebotó el "
                       f"<b style='color:{GRN if zv['p'] >= 60 else AMB}'>{zv['p']}%</b> "
                       f"<span style='color:#667'>(IC {zv['lo']}–{zv['hi']}%, n={zv['n']})</span> · media {_fp(zv['avg'])}</div>")
            # EL BOTE
            if semis.get("ev"):
                e = semis["ev"]
                sd += (f"<div style='margin-top:6px;font-size:11px'>EL BOTE: en el cubo actual, prob. {e['p']}% y media {e['avg']:+.1f}% a 4 sem → "
                       f"tamaño orientativo ¼-Kelly ≈ <b style='color:{CYN}'>{min(e['kelly4'], 3.0):.1f}%</b> de cartera (tope 3%), "
                       "en <b>contado</b> (SMH/SOXL pequeño), nunca promediando el corto.</div>")
            sd += ("<div style='font-size:10px;color:#666;margin-top:8px'>REGLAS DE LA PARTIDA: ① el rebote se juega LARGO (SMH contado; SOXL solo con mano fuerte y stop) — "
                   "<b style='color:" + RED + "'>SOXS es la apuesta CONTRARIA</b>: si esperas rebote y tienes SOXS, estás contra tu propia mano y su decay −3x te cobra cada día. "
                   "② La mesa son frecuencias in-sample con IC ancho, no una promesa. ③ Mano fuerte sin flujo (CMF sangrando) = proyecto, no mano: espera el cierre semanal. "
                   "④ Semis es el sector más noticioso (Corea, aranceles, resultados NVDA): el gap te puede saltar el stop. Tamaño pequeño SIEMPRE.</div>")
            html.append(_mod(f"🎰 SEMIS DESK — PÓKER DE REBOTE ({semis['sym']})", sd))
        # --- MODULO 7: SIGNALS WIRE (cable de señales, con memoria entre sesiones) ---
        wire = []
        def _wadd(col, tag, txt, sym=None, dr=0):
            wire.append({"col": col, "tag": tag, "txt": txt, "sym": sym, "dir": dr})
        if semis and semis.get("pts", 0) >= 8:
            _wadd(GRN, "SEMIS", f"{semis['sym']}: REBOTE SCORE {semis['pts']}/10 — mano fuerte sobre la mesa, mira el SEMIS DESK", semis["sym"], 1)
        if giro and giro.get("rotacion"):
            _wadd(AMB, "GIRO", "Rotación intradía: vendieron lo caliente y compraron lo frío en la misma sesión (" + giro.get("fecha", "") + ")", "MERCADO", -1)
        for g in (giro.get("rows", [])[:3] if giro else []):
            _gt = "vendieron la subida" if g["sig"] == "bajista" else "compraron el miedo"
            _wadd((RED if g["sig"] == "bajista" else GRN), "GIRO",
                  f"{g['sym']}: gap {g['gap']:+.1f}% → cierre en {g['pos']}% del rango — {_gt}",
                  g["sym"], -1 if g["sig"] == "bajista" else 1)
        for b in (apal["brokers"] if apal else []):
            e5 = (b["esc"].get(-5) or {})
            if e5.get("estado") and e5["estado"] != "ok":
                _wadd(RED, "RISK", f"{b['broker']}: a S&P −5% → {e5['estado'].upper()}", b["broker"], -1)
        for s in (excluded_di or []):
            _wadd(AMB, "FLOW", f"{s}: DISTRIBUCIÓN OCULTA — precio sube, dinero sale. Excluido.", s, -1)
        for c in (contra_sigs or []):
            _wadd(GRN, "0/3", f"{c['sym']}: señal contraria {c['n3']}/3 · verticalidad {c['vert']}x · tamaño manga", c["sym"], 1)
        for r in (suelo or [])[:4]:
            if r["pts"] >= 8 and not r["sangra"]:
                _wadd(GRN, "SUELO", f"{r['sym']}: {r['pts']}/10 — castigo+olvido y dejó de sangrar", r["sym"], 1)
            elif r["sangra"]:
                _wadd(GRY, "SUELO", f"{r['sym']}: {r['pts']}/10 pero AÚN SANGRA — sin prisa", r["sym"], 0)
        for r in (early or [])[:3]:
            _wadd(CYN, "EARLY", f"{r['sym']}: girando al alza, ext {r['ext']}% — entrada sin perseguir", r["sym"], 1)
        if entering:
            _wadd(CYN, "RRG", "Entran a Mejorando: " + ", ".join(entering[:5]))
        if leaving:
            _wadd(AMB, "RRG", "Salen a Debilitándose: " + ", ".join(leaving[:5]))
        if candidato:
            _wadd(AMB, "PICK", f"Candidato del sistema: {candidato['top']['stock']['sym']} vía {candidato['top']['etf']}")
        if fg_idx and fg_idx["score"] <= 25:
            _wadd(RED, "SENT", f"F&G en MIEDO EXTREMO ({fg_idx['score']}) — histórico contrarian, confirma con flujo", "F&G", 1)
        # persistencia entre sesiones: guardar hoy + analizar las ultimas sesiones
        _wire_date = (giro or {}).get("fecha") or str(df.index[-1].date())
        wtl = None
        try:
            wtl = analyze_wire_persistence(update_wire_ledger(wire, _wire_date))
        except Exception:
            wtl = None
        _pers = {}
        if wtl:
            for sgn in wtl["sigs"]:
                _pers[(sgn["tag"], sgn["sym"])] = sgn
        sw = ""
        for it in wire[:14]:
            badge = ""
            p = _pers.get((it["tag"], it["sym"]))
            if p and p["today"] and it["sym"]:
                if p["streak"] >= 3:
                    badge = f" <b style='color:{GRN}'>×{p['streak']} sesiones ✓</b>"
                elif p["streak"] == 2:
                    badge = f" <span style='color:{AMB}'>×2 sesiones</span>"
                if p.get("contradice"):
                    badge += f" <span style='color:{RED}'>⚠ ayer al revés</span>"
            sw += (f"<div style='margin:3px 0;font-size:11.5px'><span style='color:#000;background:{it['col']};padding:0 5px;"
                   f"font-size:9px;font-weight:700;border-radius:2px'>{it['tag']}</span> <span style='color:#D8DEE9'>{esc(it['txt'])}</span>{badge}</div>")
        html.append(_mod(f"SIGNALS WIRE — {last_lbl}", sw or "<span style='color:#666'>sin señales relevantes esta semana</span>"))
        # --- MODULO 7b: WIRE TIMELINE — persistencia de señales entre sesiones ---
        if wtl and wtl.get("sigs"):
            _dts = wtl["dates"]
            _hdr = "".join(f"<th style='min-width:26px'>{d[8:10]}/{d[5:7]}</th>" for d in _dts)
            wt = f"<table><tr><th style='text-align:left'>SEÑAL</th>{_hdr}<th style='text-align:left'>LECTURA</th></tr>"
            _lvlc = {"alta": GRN, "media": AMB, "ruido": RED, "baja": GRY}
            for sgn in wtl["sigs"]:
                dots = ""
                for v in sgn["tl"]:
                    if v is None:
                        dots += "<td style='color:#333'>·</td>"
                    else:
                        _dc = GRN if v > 0 else RED if v < 0 else AMB
                        dots += f"<td style='color:{_dc}'>●</td>"
                _vc = _lvlc.get(sgn["lvl"], GRY)
                wt += (f"<tr><td style='text-align:left'><span style='color:#777;font-size:9px'>{sgn['tag']}</span> "
                       f"<b style='color:{AMB}'>{esc(str(sgn['sym']))}</b></td>{dots}"
                       f"<td style='text-align:left;color:{_vc};font-size:10.5px'>{esc(sgn['verd'])}</td></tr>")
            wt += "</table>"
            wt += ("<div style='font-size:10px;color:#666;margin-top:6px'>● verde = señal alcista ese cierre · ● rojo = bajista · ● ámbar = neutra · '·' = no apareció. "
                   "La regla que pediste, codificada: <b>un día es ruido; tres cierres seguidos en la misma dirección es un patrón confirmándose</b>; "
                   "un día y al siguiente lo contrario, el TIMELINE lo marca como mercado indeciso y le quita validez. "
                   "El histórico se guarda en <code>senales_wire.json</code> y empieza a contar desde hoy: necesita unas sesiones para llenarse.</div>")
            html.append(_mod(f"⏱ WIRE TIMELINE — persistencia de señales (últimas {len(_dts)} sesiones)", wt))
        # --- MODULO 8: FX & CROSS-ASSET ---
        xa = "<table><tr><th style='text-align:left'>ACTIVO</th><th>ÚLT</th><th>1S</th><th>12S</th><th style='text-align:left'>LECTURA</th></tr>"
        _lect = {"EURUSD": "€ fuerte = viento en contra en tus USD", "TLT": "TLT ↑ = tipos largos ↓",
                 "GLD": "refugio / tu manga metales", "UUP": "dólar: inverso a emergentes",
                 "HYG": "crédito HY: canario del riesgo", "IBIT": "beta cripto de tu perp"}
        for s in ["EURUSD", "TLT", "GLD", "UUP", "HYG", "IBIT"]:
            if s not in df.columns:
                continue
            ser = _ser(s)
            last = f"{float(ser.iloc[-1]):,.2f}".replace(",", " ") if ser is not None else "—"
            xa += (f"<tr><td style='text-align:left;color:{AMB};font-weight:700'>{s}</td><td style='color:#D8DEE9'>{last}</td>"
                   f"<td>{_fp(_chg(s, 1))}</td><td>{_fp(_chg(s, 12))}</td>"
                   f"<td style='text-align:left;color:{GRY};font-size:10px'>{_lect.get(s, '')}</td></tr>")
        xa += "</table>"
        html.append(_mod("FX & CROSS-ASSET — EL TABLERO ALREDEDOR", xa))
        html.append("</div>")  # cierre bbgrid
        html.append("<div class='bbgp' style='grid-column:1/-1'><div class='bbgb' style='font-size:10px;color:#666'>"
                    "PeVR TERMINAL PRO · datos de cierre semanal (Stooq/Yahoo, posible retardo) · todos los módulos beben de los mismos cálculos "
                    "que Contexto y Operativa, aquí en formato denso de mesa · el detalle y el porqué, en sus pestañas · no es asesoramiento</div></div>")
    except Exception:
        # CRITICO: si algo falla a mitad, descartamos TODO el HTML parcial de esta vista.
        # Si no, quedarian divs sin cerrar y las pestanas siguientes (Vigilancia, Claude) quedarian anidadas e invisibles.
        del html[_bbg_mark:]
        html.append("<div class='panel full'><h2>🖥️ PRO</h2><div class='note'>Esta vista no se pudo generar esta semana "
                    "(error interno controlado). El resto del terminal funciona con normalidad.</div></div>")
    html.append("</div>")

    # ===== V-REDES — SUPER RESUMEN PARA PUBLICAR (tarjeta JPG + texto + PDF) =====
    html.append("<div id='vista-rds' style='display:none'>")
    _rds_mark = len(html)
    try:
        _wk2 = df.index[-1].strftime("%G-W%V")
        # --- tarjeta visual (formato vertical para redes) ---
        card = []
        card.append(f"<div style='border-bottom:3px solid {light};padding-bottom:10px;margin-bottom:14px'>"
                    f"<div style='font-size:24px;font-weight:800;letter-spacing:2px'>ROTACIÓN <span style='color:{light}'>SEMANAL</span></div>"
                    f"<div style='color:#8FA3C0;font-size:12px;margin-top:2px'>{_wk2} · cierre {last_lbl} · sistema PeVR de flujo y rotación sectorial</div></div>")
        _kv = lambda k, v: (f"<div style='display:flex;gap:12px;margin:9px 0;align-items:baseline'>"
                            f"<span style='min-width:120px;font-size:10.5px;color:#8FA3C0;text-transform:uppercase;letter-spacing:.8px'>{k}</span>"
                            f"<span style='font-size:14px;line-height:1.55'>{v}</span></div>")
        # ticker + nombre corto, para que nadie tenga que adivinar qué es cada activo
        def _tkn(sym):
            nm = NAMES.get(sym, (sym, sym, ""))[1]
            return f"<b>{esc(sym)}</b> <span style='color:#8FA3C0;font-size:11px'>{esc(nm)}</span>"
        def _lista(syms, col, n=6):
            return "<br>".join(f"<span style='color:{col}'>{_tkn(s)}</span>" for s in syms[:n])
        card.append(_kv("Semáforo", f"<b style='color:{light};font-size:17px'>{esc(sem_short)}</b> · {esc(reg_short)} · {esc(risk['label'])}"
                        + (f" · F&G <b>{fg_idx['score']}</b> ({esc(str(fg_idx.get('rating', '')))})" if fg_idx else "")))
        _cart_list = [s.strip() for s in cartera_txt.split(",")] if ("," in cartera_txt or cartera_txt in NAMES) else None
        if _cart_list and all(s in NAMES for s in _cart_list):
            card.append(_kv("📦 En cartera ahora", _lista(_cart_list, "#5B8CFF", 8)
                            + "<br><span style='color:#5E708A;font-size:10px'>lo que el sistema tiene abierto esta semana</span>"))
        else:
            card.append(_kv("📦 En cartera ahora", f"<b style='color:#5B8CFF'>{esc(cartera_txt)}</b>"))
        if entering:
            card.append(_kv("🟢 Reforzando", _lista(entering, "#4CC2E0", 5)
                            + "<br><span style='color:#5E708A;font-size:10px'>ganan fuerza — el dinero empieza a entrar</span>"))
        if leaving:
            card.append(_kv("🟡 Reduciendo", _lista(leaving, "#F4B740", 5)
                            + "<br><span style='color:#5E708A;font-size:10px'>pierden fuerza — se sale poco a poco</span>"))
        if excluded_di:
            card.append(_kv("🔴 Trampa", _lista(excluded_di, "#F4607A", 4)
                            + "<br><span style='color:#5E708A;font-size:10px'>el precio sube pero el dinero SALE — no fiarse</span>"))
        if candidato:
            _t = candidato["top"]
            card.append(_kv("Pick sistema", f"<b style='color:#5B8CFF'>{_t['stock']['sym']}</b> vía {_t['etf']}"))
        _su8 = [r for r in (suelo or []) if r["pts"] >= 8 and not r["sangra"]][:3]
        if _su8:
            card.append(_kv("Radar suelo", "<span style='color:#2FD08A'>" + esc(", ".join(f"{r['sym']} ({r['pts']}/10)" for r in _su8)) + "</span> — castigados, olvidados y dejando de sangrar"))
        if contra_sigs:
            card.append(_kv("Contraria 0/3", "<span style='color:#7BD88F'>" + esc(", ".join(s["sym"] for s in contra_sigs)) + "</span>"))
        if tperf:
            _c2 = tperf["cum"]
            _d2 = (_c2.get("sys", 0) - _c2.get("SPY", 0)) * 100
            card.append(_kv("Track record", f"sistema {_c2.get('sys', 0) * 100:+.1f}% vs SPY {_c2.get('SPY', 0) * 100:+.1f}% "
                            f"({tperf['n']} sem, verificable)"))
        # tabla: cada ETF de la cartera desde que el sistema le dio ENTRADA, vs SPY y QQQ en ese mismo periodo
        try:
            _dRows = ""
            import datetime as _dt
            import pandas as _pd
            def _precio_en_fecha(serie, fecha):
                try:
                    s = serie.dropna()
                    if not len(s):
                        return None
                    idx = s.index.searchsorted(_pd.Timestamp(fecha))
                    if idx >= len(s):
                        idx = len(s) - 1
                    return float(s.iloc[idx])
                except Exception:
                    return None
            def _fecha_entrada(sym):
                recs = sorted(_recs_e or [], key=lambda r: r.get("week", ""))
                wk_entrada = _cur_week
                for r in reversed(recs):
                    if r.get("week") == _cur_week:
                        continue
                    if sym in r.get("basket", []):
                        wk_entrada = r.get("week")
                    else:
                        break
                try:
                    yr, wk2 = str(wk_entrada).split("-W")
                    monday = _dt.date.fromisocalendar(int(yr), int(wk2), 1)
                    return monday + _dt.timedelta(days=4)
                except Exception:
                    return None
            try:
                _qqq_serie = nq_close if (nq_close is not None and len(nq_close.dropna())) else (df["QQQ"] if "QQQ" in df.columns else None)
            except Exception:
                _qqq_serie = df["QQQ"] if "QQQ" in df.columns else None
            for _s2 in CARTERA_FINAL:
                if _s2 not in df.columns:
                    continue
                _f = _fecha_entrada(_s2)
                if _f is None:
                    continue
                _px_ent = _precio_en_fecha(df[_s2], _f)
                _px_now = float(df[_s2].dropna().iloc[-1])
                if not _px_ent or _px_ent <= 0:
                    continue
                _p2 = (_px_now / _px_ent - 1) * 100
                _wk2b = max(1, round((df.index[-1].date() - _f).days / 7))
                def _bench_desde(serie):
                    if serie is None:
                        return None
                    pe = _precio_en_fecha(serie, _f)
                    ss = serie.dropna()
                    pn = float(ss.iloc[-1]) if len(ss) else None
                    return ((pn / pe - 1) * 100) if (pe and pe > 0 and pn) else None
                _spyp = _bench_desde(df["SPY"] if "SPY" in df.columns else None)
                _qqqp = _bench_desde(_qqq_serie)
                _f2 = lambda v: (f"<span style='color:{('#2FD08A' if v >= 0 else '#F4607A')}'>{v:+.1f}%</span>" if v is not None else "<span style='color:#5E708A'>—</span>")
                _win = _p2 - (_spyp if _spyp is not None else 0)
                _dRows += (f"<tr><td style='text-align:left;padding:3px 6px'><b style='color:#5B8CFF'>{_s2}</b> "
                           f"<span style='color:#8FA3C0;font-size:9px'>{_wk2b}s</span></td>"
                           f"<td style='text-align:right;padding:3px 6px'>{_f2(_p2)}</td>"
                           f"<td style='text-align:right;padding:3px 6px'>{_f2(_spyp)}</td>"
                           f"<td style='text-align:right;padding:3px 6px'>{_f2(_qqqp)}</td>"
                           f"<td style='text-align:right;padding:3px 6px;color:{('#2FD08A' if _win >= 0 else '#F4607A')};font-weight:700'>{_win:+.1f}</td></tr>")
            if _dRows:
                card.append("<div style='margin-top:12px'><div style='font-size:10.5px;color:#8FA3C0;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px'>"
                            "Desde que el sistema dio entrada (mismo periodo)</div>"
                            "<table style='width:100%;border-collapse:collapse;font-size:12px'>"
                            "<tr style='color:#8FA3C0;font-size:9.5px'><th style='text-align:left;padding:3px 6px'>ETF · semanas</th>"
                            "<th style='text-align:right;padding:3px 6px'>ETF</th><th style='text-align:right;padding:3px 6px'>SPY</th>"
                            "<th style='text-align:right;padding:3px 6px'>QQQ</th><th style='text-align:right;padding:3px 6px'>vs SPY</th></tr>"
                            + _dRows + "</table>"
                            "<div style='font-size:9px;color:#7A8CA8;margin-top:4px'>⚖ Esta tabla muestra las posiciones ACTUALES desde su entrada (los que siguen vivos). "
                            "El track record de arriba encadena la cesta completa semana a semana, incluidos los que salieron: por eso puede ser peor que la media de esta tabla. "
                            "Ambos son correctos; miden preguntas distintas.</div></div>")
        except Exception:
            pass
        card.append("<div style='margin-top:14px;padding:9px 11px;background:rgba(91,140,255,.06);border:1px solid #5B8CFF22;border-radius:8px;"
                    "font-size:10.5px;color:#9FB0C8;line-height:1.6'>💡 Cómo leerlo: <b style='color:#5B8CFF'>📦 En cartera</b> es lo que el sistema tiene abierto "
                    "ahora mismo. <b style='color:#4CC2E0'>🟢 Reforzando</b> y <b style='color:#F4B740'>🟡 Reduciendo</b> son los <b>movimientos</b> de esta semana "
                    "(hacia dónde va el dinero), no compras nuevas. Un activo puede estar en cartera y a la vez reduciéndose.</div>")
        card.append("<div style='margin-top:12px;padding:10px 12px;background:rgba(76,194,224,.07);border:1px solid #4CC2E033;border-radius:8px;"
                    "font-size:12px;color:#B9C9E2'>📬 Análisis completo cada sábado · señales de rotación, flujo institucional y radar de suelos"
                    "<br><span style='color:#4CC2E0;font-weight:700'>La Estela — próximamente en Substack y Telegram</span></div>")
        card.append("<div style='margin-top:12px;padding-top:8px;border-top:1px solid #2A3A55;font-size:8.5px;color:#7A8CA8;line-height:1.5'>"
                    "Contenido informativo y educativo de carácter general. NO es asesoramiento financiero personalizado ni recomendación de inversión "
                    "(MiFID II / criterios CNMV para divulgadores). El autor puede tener posiciones en los activos mencionados. "
                    "Rendimientos pasados no garantizan resultados futuros. Los productos apalancados conllevan alto riesgo. "
                    "Cada inversor es responsable de sus decisiones.</div>")
        # --- texto plano para copiar (X / Telegram): ticker + nombre y etiquetas que se explican solas ---
        def _tkn_txt(sym):
            return f"{sym} ({NAMES.get(sym, (sym, sym, ''))[1]})"
        _txt = [f"📊 ROTACIÓN SEMANAL {_wk2}",
                f"Semáforo: {sem_short} · {reg_short} · {risk['label']}" + (f" · F&G {fg_idx['score']}" if fg_idx else ""),
                "",
                "📦 EN CARTERA AHORA (lo que el sistema tiene abierto):",
                "  " + ", ".join(_tkn_txt(s.strip()) for s in cartera_txt.split(",")) if all(s.strip() in NAMES for s in cartera_txt.split(",")) else f"📦 En cartera: {cartera_txt}"]
        if entering:
            _txt.append("")
            _txt.append("🟢 REFORZANDO (ganan fuerza esta semana): " + ", ".join(_tkn_txt(s) for s in entering[:5]))
        if leaving:
            _txt.append("🟡 REDUCIENDO (pierden fuerza): " + ", ".join(_tkn_txt(s) for s in leaving[:5]))
        if excluded_di:
            _txt.append("🔴 TRAMPA (sube el precio pero sale el dinero): " + ", ".join(_tkn_txt(s) for s in excluded_di[:4]))
        if candidato:
            _txt.append(f"🏆 Pick del sistema: {candidato['top']['stock']['sym']} (vía {candidato['top']['etf']})")
        if _su8:
            _txt.append("🕳️ Radar suelo: " + ", ".join(f"{r['sym']} {r['pts']}/10" for r in _su8))
        _txt.append("")
        _txt.append("El flujo confirma, no predice. Análisis completo el sábado.")
        _txt.append("No es asesoramiento financiero. #inversión #ETF #rotaciónsectorial")
        _txt_js = json.dumps("\n".join(_txt), ensure_ascii=False)
        html.append("<script>var RDTXT=" + _txt_js + ";"
                    "function copiarRedes(){if(navigator.clipboard&&navigator.clipboard.writeText){"
                    "navigator.clipboard.writeText(RDTXT).then(function(){alert('Texto copiado. Pégalo en X o Telegram.');},"
                    "function(){alert('No se pudo copiar automáticamente. Abre \"Ver el texto plano\" y cópialo a mano.');});}"
                    "else{alert('Tu navegador bloquea el portapapeles aquí. Abre \"Ver el texto plano\" y cópialo a mano.');}}</script>")
        html.append("<div class='panel full'><h2>📣 Redes — el resumen que se publica</h2>"
                    "<div class='note'>Tu escaparate semanal: tarjeta vertical lista para X/Telegram/Instagram, texto plano para pegar y el PDF completo para Substack. "
                    "La tarjeta enseña <b>qué hace el sistema</b> sin regalar el terminal entero — el gancho para monetizar después. "
                    "El disclaimer CNMV/MiFID II va incorporado en la propia imagen: no lo quites.</div>"
                    "<div style='display:flex;gap:8px;flex-wrap:wrap;margin:10px 0'>"
                    f"<button class='viewtab' onclick=\"_h2c(document.getElementById('redes-card'),'rotacion_redes_{_wk2}.jpg')\" "
                    "style='border-color:#4CC2E055;color:#4CC2E0'>📸 Descargar tarjeta JPG</button>"
                    "<button class='viewtab' onclick='copiarRedes()' "
                    "style='border-color:#4CC2E055;color:#4CC2E0'>📋 Copiar texto para X/Telegram</button>"
                    "<button class='viewtab' onclick='descargarPDF()' style='border-color:#5B8CFF55;color:#5B8CFF'>📄 PDF completo (Substack)</button>"
                    "</div>"
                    "<div id='redes-card' style='max-width:560px;margin:0 auto;background:linear-gradient(160deg,#0A0E17 0%,#0D1524 100%);"
                    "border:1px solid #24344F;border-radius:14px;padding:26px 28px;color:#E8EEF9'>" + "".join(card) + "</div>"
                    "<details style='margin-top:12px'><summary style='cursor:pointer;color:#9FB0C8;font-size:12px'>Ver el texto plano (por si el botón de copiar no funciona)</summary>"
                    f"<pre style='background:#0E1626;border:1px solid #ffffff18;border-radius:8px;padding:12px;font-size:11.5px;white-space:pre-wrap;color:#CDE3FF'>{esc(chr(10).join(_txt))}</pre></details>"
                    "<div class='note' style='margin-top:8px;color:#5E708A'>Ritual de publicación del sábado: 1) genera el terminal con el cierre del viernes → "
                    "2) descarga tarjeta + PDF → 3) tarjeta a X/Telegram por la mañana, PDF a Substack → 4) mismo formato cada semana: la constancia ES el producto. "
                    "Recuerda el marco: análisis público NO personalizado, con posiciones propias declaradas.</div></div>")
    except Exception:
        del html[_rds_mark:]
        html.append("<div class='panel full'><h2>📣 Redes</h2><div class='note'>La tarjeta no se pudo generar esta semana.</div></div>")
    html.append("</div>")

    # ===== V3 — VISTA VIGILANCIA =====
    html.append("<div id='vista-vig' style='display:none'>")
    try:
        if watch:
            wrows = ""
            for r in watch:
                if not r.get("ok"):
                    wrows += (f"<tr><td class='se-l'><b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(r['name'])}</span></td>"
                              "<td class='r' colspan='6' style='color:#5E708A'>sin datos (¿ticker correcto?)</td></tr>")
                    continue
                pe, pl, pc = PHASE_INFO.get(r["phase"], ("", "—", "#9FB0C8"))
                cmf = r.get("cmf")
                cmf_s = (f"<span style='color:{'#2FD08A' if (cmf or 0) > 0 else '#F4607A'}'>{cmf:+.2f}</span>") if cmf is not None else "—"
                obv_s = ("<span style='color:#2FD08A'>OBV↑</span>" if r.get("obv_above") else "<span style='color:#F4607A'>OBV↓</span>")
                if r.get("obv_cross"):
                    obv_s += " <span style='color:#2FD08A'>⚡cruce</span>"
                hicol = "#F4607A" if r["hi52"] >= 90 else "#9FB0C8"
                momcol = "#2FD08A" if r["mom3"] > 0 else "#F4607A"
                wrows += (f"<tr><td class='se-l'><b>{r['sym']}</b> <span style='color:var(--txt3);font-size:11px'>{esc(r['name'])}</span></td>"
                          f"<td class='r'>{r['price']:,.2f}</td>"
                          f"<td class='r' style='color:{pc};white-space:nowrap'>{pe} {pl}</td>"
                          f"<td class='r' style='white-space:nowrap'>{cmf_s} · {obv_s}</td>"
                          f"<td class='r' style='color:{momcol}'>{r['mom3']:+.1f}%</td>"
                          f"<td class='r' style='color:{hicol};white-space:nowrap'>{r['hi52']}% máx · +{r['frm_lo']}% mín</td>"
                          f"<td class='r' style='color:{r['ecol']};white-space:nowrap;font-size:11px'>{esc(r['estado'])}</td></tr>")
            html.append("<div class='panel full'><h2>📋 Vigilancia — ¿cuándo empieza a acumular?</h2>"
                        "<div class='note'>Las acciones que vigilas o tienes y crees que a largo plazo lo harán bien. El objetivo: no estar solo "
                        "<b>esperando</b> a que recuperen, sino <b>ver</b> la señal de cuándo el dinero empieza a entrar — el primer chispazo del cambio de base a subida, "
                        "antes de que el precio lo confirme. <b>Estado:</b> 🔴 aún cayendo (cuchillo) → 🟦 en base sin flujo (espera) → "
                        "🟢 empezando a acumular (el dinero entra, ojo) → 🟢 subiendo (ya arrancó). Es un <b>mapa de probabilidad, no una predicción</b>: una hundida puede seguir cayendo, "
                        "y el semáforo te lo dirá igual de claro. Edita la lista en WATCHLIST. No es asesoramiento.</div>"
                        "<div class='scrollx'><table class='se'><tr><th class='se-l'>acción</th><th class='r'>precio</th><th class='r'>fase</th>"
                        "<th class='r'>flujo (CMF · OBV)</th><th class='r'>mom 3m</th><th class='r'>rango 52s</th><th class='r'>estado</th></tr>"
                        + wrows + "</table></div></div>")
        else:
            html.append("<div class='panel full'><h2>📋 Vigilancia</h2><div class='note'>Sin datos de la watchlist. Revisa la lista WATCHLIST y que haya conexión.</div></div>")
    except Exception:
        html.append("<div class='panel full'><h2>📋 Vigilancia</h2><div class='note'>No se pudo construir la vigilancia esta vez.</div></div>")
    html.append("</div>")
    # ---- PESTAÑA MODO CLAUDE: la decision limpia en una pantalla ----
    try:
        _cl = ["<div id='vista-cl' style='display:none'>",
               "<div class='panel full'><h2>🤖 Modo Claude — la decisión, limpia</h2>",
               "<div class='note'>Solo lo esencial para decidir el viernes y ejecutar el lunes: dónde estar (⭐ = en cartera), qué evitar, y los giros verticales de los dormidos. El detalle completo sigue en Contexto y Operativa. No es asesoramiento.</div></div>"]
        est = "".join(
            f"<tr><td class='se-l'>{'⭐ ' if e['in_cart'] else ''}<b>{e['sym']}</b> "
            f"<span style='color:var(--txt3);font-size:11px'>{esc(NAMES.get(e['sym'], (e['sym'], e['sym'], ''))[1])}</span></td>"
            f"<td class='r'>{e['sc']}/5</td>"
            f"<td class='r' style='font-size:11px'>{QUAD.get(e['quad'], (e['quad'],))[0]}</td>"
            f"<td class='r' style='font-size:11px'>CMF {(e['cmf'] if e['cmf'] is not None else 0):+.2f}</td></tr>"
            for e in (_estar or [])[:9])
        _cl.append("<div class='panel full'><h2>🧺 CARTERA FINAL de la semana</h2>"
                   "<div style='font-size:15px;padding:6px 0'><b style='color:#5B8CFF'>" + esc(", ".join(CARTERA_FINAL) if CARTERA_FINAL else "liquidez — sin señal suficiente") + "</b></div>"
                   "<div class='note'>La única lista que se opera (viernes confirma, lunes ejecuta). Los porcentajes, en Contexto → Cartera de la semana.</div></div>")
        _cl.append("<div class='panel full'><h2>✅ Candidatos por puntuación (⭐ = en cartera)</h2><div class='scrollx'><table class='se'>"
                   "<tr><th class='se-l'>sector</th><th class='r'>nota</th><th class='r'>tendencia</th><th class='r'>flujo</th></tr>"
                   + (est or "<tr><td colspan='4' style='color:#9FB0C8'>Nada cumple las tres condiciones — mejor esperar.</td></tr>")
                   + "</table></div></div>")
        ev = ", ".join(f"<b>{s}</b> <span style='font-size:11px'>({esc(w)})</span>" for s, w in (_evitar or [])[:14])
        if ev:
            _cl.append(f"<div class='panel full'><h2>⛔ Evitar / fuera</h2><div class='note' style='color:#F4607A'>{ev}</div></div>")
        try:
            vr2 = "".join(
                f"<tr><td class='se-l'>🚀 <b>{s}</b> <span style='color:var(--txt3);font-size:11px'>{esc(NAMES.get(s, (s, s, ''))[1])}</span></td>"
                f"<td class='r' style='color:#7BD88F;font-weight:700'>{vert:.1f}×</td>"
                f"<td class='r'>{(str(n3) + '/3') if n3 is not None else '—'}</td><td class='r'>{fl}</td></tr>"
                for vert, s, d, dmom, drat, n3, fl in (vrows or [])[:6])
            if vr2:
                _cl.append("<div class='panel full'><h2>🚀 Dormidos girando en vertical</h2>"
                           "<div class='note'>Abajo en Rezagado y despertando (0-1/3 señales = históricamente 65% a 4 semanas). Especulativo: tamaño pequeño.</div>"
                           "<div class='scrollx'><table class='se'><tr><th class='se-l'>sector</th><th class='r'>verticalidad</th><th class='r'>señales</th><th class='r'>flujo</th></tr>"
                           + vr2 + "</table></div></div>")
        except Exception:
            pass
        # --- PANEL DE IA AUTOMATICA: la respuesta del maestro, generada EN ESTE BUILD ---
        try:
            if ia_auto:
                for _k in (["gestor"] + [x for x in (IA_AUTO_EXTRA or []) if x != "gestor"]):
                    _r = ia_auto.get(_k)
                    if not _r:
                        continue
                    _col = "#FFB000" if _r["ok"] else "#F4607A"
                    _cuerpo = esc(_r["text"]).replace(chr(10) + chr(10), "</p><p>").replace(chr(10), "<br>")
                    _cl.append(f"<div class='panel full' style='border:1px solid {_col}55'>"
                               f"<h2 style='color:{_col}'>🤖 {esc(_r['title'])} — RESPUESTA AUTOMÁTICA DE ESTE BUILD</h2>"
                               "<div class='note'>Generada al ejecutar el terminal: el prompt se lanzó a la API con el snapshot de datos de este cierre inyectado"
                               + (" y permiso de búsqueda web" if IA_WEB_SEARCH else "") + ". Es una hipótesis de máquina, no asesoramiento — el veredicto lo dan tus viernes.</div>"
                               f"<div style='font-size:13px;line-height:1.75;color:#DCE6F5'><p>{_cuerpo}</p></div>"
                               f"<div class='note' style='margin-top:8px;color:#5E708A'>modelo {esc(_r['modelo'])} · para auto-ejecutar más prompts, añade sus claves en <code>IA_AUTO_EXTRA</code> (cada uno suma tiempo y coste)</div></div>")
            elif IA_AUTO:
                _cl.append("<div class='panel full'><h2>🤖 IA automática — SIN ACTIVAR</h2>"
                           "<div class='note'>El terminal está listo para <b>ejecutar el prompt maestro automáticamente en cada build</b> y pintar aquí la respuesta, "
                           "pero falta la API key. Activación SIN tocar código: <b>(1)</b> consigue una key (GRATIS en <b>aistudio.google.com/apikey</b> con IA_PROVIDER=openai_compat, o de pago en <b>console.anthropic.com</b>, "
                           "independiente de tu suscripción de claude.ai — el análisis maestro con búsqueda web cuesta del orden de céntimos por ejecución); "
                           "<b>(2)</b> crea un archivo de texto <code>ia_key.txt</code> (proveedor gratis) o <code>anthropic_key.txt</code> (Anthropic) en la MISMA carpeta que rotacion.py y pega dentro solo la key, en una sola línea; "
                           "<b>(3)</b> vuelve a ejecutar — el terminal la encuentra sola y, si la carpeta es un repositorio git, añade el archivo a .gitignore automáticamente para que la key nunca acabe subida a GitHub. "
                           "<b>Vía GRATIS</b>: pon <code>IA_PROVIDER = \"openai_compat\"</code> y una key gratuita de Google AI Studio (aistudio.google.com/apikey) en <code>IA_COMPAT_KEY</code> — automático a coste cero, con los límites del tier gratuito y sin búsqueda web. "
                           "Mientras tanto, los botones de abajo copian cada prompt con tus datos para pegarlo a mano en claude.ai.</div></div>")
        except Exception:
            pass
        # --- BIBLIOTECA DE PROMPTS: cada uno se copia CON los datos del terminal inyectados (cierra el circulo) ---
        try:
            _plib = IA_PROMPTS or [
                ("sectorial", "🕰 Rotación sectorial — 30 años de precursores",
                 "Analiza los últimos 30 años y encuentra qué indicadores (tipos de interés, inflación, ISM, PMI, curva de tipos, desempleo, beneficios empresariales, dólar y petróleo) han anticipado las rotaciones entre tecnología, financieras, industriales, energía, consumo, salud y utilities."),
                ("flujos", "💸 Flujos institucionales",
                 "Detecta qué sectores están recibiendo entradas de dinero institucional durante las últimas cuatro semanas comparándolo con los últimos cinco años."),
                ("liderazgo", "🏁 Liderazgo antes de que se vea",
                 "¿Qué industrias están mostrando fortaleza relativa frente al S&P 500 antes de que el mercado general las reconozca?"),
                ("ocultas", "🕵️ Rotaciones ocultas",
                 "Busca acciones que estén rompiendo máximos de 52 semanas mientras el sector todavía no aparece entre los mejores del S&P 500."),
                ("ciclo", "🕐 Ciclo económico",
                 "Según los datos macro actuales, ¿en qué fase del ciclo económico está Estados Unidos y qué sectores suelen liderar históricamente esa fase?"),
                ("insiders", "🐋 Insiders y grandes fondos",
                 "Cruza compras de insiders, posiciones de hedge funds y cambios en las carteras de Berkshire Hathaway, Bridgewater, Pershing Square y otros grandes gestores para detectar posibles rotaciones."),
                ("narrativas", "🗣 Narrativas emergentes",
                 "¿Qué temas empiezan a aparecer cada vez más en las conferencias de resultados (earnings calls) antes de que el mercado los descuente?"),
                ("multifactor", "🧮 Ranking multifactor",
                 "Construye un ranking semanal de sectores utilizando fortaleza relativa, beneficios revisados al alza, momentum, volumen institucional y valoración."),
                ("gestor", "🎖 GESTOR DE HEDGE FUND MACRO (el maestro)",
                 "Actúa como un gestor de un hedge fund macro. Analiza diariamente datos macroeconómicos de EE. UU., flujos institucionales, fortaleza relativa de sectores, revisiones de beneficios, mercado de bonos, dólar, VIX, materias primas y amplitud de mercado. Identifica qué sectores tienen mayor probabilidad de liderar durante las próximas 2 a 8 semanas y explica por qué. Asigna una probabilidad a cada escenario y señala qué datos invalidarían esa hipótesis."),
            ]
            _pdata = ia_data_block(snap, last_lbl)
            _clp = {k: p + _pdata for k, _, p in _plib}
            cards = ""
            for k, tit, p in _plib:
                _dest = (k == "gestor")
                _bg = "rgba(255,176,0,.07)" if _dest else "#0E1626"
                _bd = "#FFB00055" if _dest else "#24344F"
                _w = "grid-column:1/-1;" if _dest else ""
                cards += (f"<div style='{_w}background:{_bg};border:1px solid {_bd};border-radius:10px;padding:12px 14px'>"
                          f"<div style='font-size:12.5px;font-weight:700;color:{'#FFB000' if _dest else '#E8EEF9'};margin-bottom:6px'>{tit}</div>"
                          f"<div style='font-size:11px;color:#9FB0C8;line-height:1.5;margin-bottom:8px'>{esc(p[:170])}{'…' if len(p) > 170 else ''}</div>"
                          f"<button class='viewtab' onclick=\"copiarPromptCL('{k}',this)\" "
                          f"style='font-size:11px;padding:5px 10px;border-color:{_bd};color:{'#FFB000' if _dest else '#5B8CFF'}'>📋 Copiar CON mis datos</button></div>")
            _cl.append("<div class='panel full'><h2>📚 Biblioteca de prompts — pregunta como un hedge fund</h2>"
                       "<div class='note'>El círculo cerrado: cada botón copia el prompt <b>con el snapshot de datos de este cierre inyectado debajo</b> "
                       "(RRG, flujo, scoring, régimen, plan). Pégalo en Claude o en la IA que uses: no le preguntas al aire — le preguntas <b>sobre tu terminal</b>, "
                       "y le exiges fuentes para lo que tu terminal no ve (13F, insiders, earnings calls). El maestro en ámbar es el de diario; "
                       "los demás, munición del fin de semana.</div>"
                       "<div style='display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px'>" + cards + "</div>"
                       "<div style='margin-top:10px'><a class='ai-btn alt' href='https://claude.ai/new' target='_blank' rel='noopener'>Abrir Claude</a></div>"
                       "<div class='note' style='margin-top:8px;color:#5E708A'>Honestidad de ingeniero: la IA razona, no backtestea — las respuestas sobre \"30 años de historia\" "
                       "son conocimiento general, no un backtest tuyo; y los datos de 13F/insiders llegan con retraso regulatorio de semanas. "
                       "Úsalo como generador de hipótesis; el veredicto lo siguen dando tus cierres de viernes. No es asesoramiento.</div></div>")
            _cl.append("<script>var CLP=" + json.dumps(_clp, ensure_ascii=False) + ";"
                       "function copiarPromptCL(k,btn){if(navigator.clipboard&&navigator.clipboard.writeText){"
                       "navigator.clipboard.writeText(CLP[k]).then(function(){var t=btn.textContent;btn.textContent='✓ Copiado — pégalo en Claude';"
                       "setTimeout(function(){btn.textContent=t;},2500);},function(){alert('El navegador bloquea el portapapeles. Abre el terminal por https (GitHub Pages) y volverá a funcionar.');});}"
                       "else{alert('Portapapeles no disponible en este navegador.');}}</script>")
        except Exception:
            pass
        _cl.append("</div>")
        html.append("".join(_cl))
    except Exception:
        html.append("<div id='vista-cl' style='display:none'></div>")

    # ---- RESUMEN SEMANAL DESCARGABLE (PDF imprimible / JPG para redes) ----
    try:
        _wk_lbl = df.index[-1].strftime("%G-W%V")
    except Exception:
        _wk_lbl = "semana"
    _res_mark = len(html)
    try:
        _rline = lambda k, v, col="#E8EEF9": (f"<div style='display:flex;gap:10px;margin:7px 0;align-items:baseline'>"
                                              f"<span style='min-width:150px;font-size:11px;color:#8FA3C0;text-transform:uppercase;letter-spacing:.5px'>{k}</span>"
                                              f"<span style='font-size:13px;color:{col};line-height:1.5'>{v}</span></div>")
        rs_parts = []
        rs_parts.append(f"<div style='display:flex;justify-content:space-between;align-items:baseline;border-bottom:2px solid {light};padding-bottom:8px;margin-bottom:12px'>"
                        f"<div><span style='font-size:20px;font-weight:800;letter-spacing:1px'>ROTACIÓN</span> "
                        f"<span style='color:#8FA3C0;font-size:12px'>· Resumen semanal</span></div>"
                        f"<div style='color:#8FA3C0;font-size:12px'>{_wk_lbl} · cierre {last_lbl}</div></div>")
        rs_parts.append(_rline("¿Invierto?", f"<b style='color:{light}'>{esc(sem_short)}</b> · {esc(reg_short)} · {esc(risk['label'])} · mercado {mkt}"))
        if fg_idx:
            _fgc = "#F4607A" if fg_idx["score"] <= 25 else "#F4B740" if fg_idx["score"] <= 45 else "#2FD08A" if fg_idx["score"] < 75 else "#F4B740"
            rs_parts.append(_rline("Fear & Greed (CNN)", f"<b style='color:{_fgc}'>{fg_idx['score']}</b> · {esc(fg_idx['rating'])} "
                                                          f"<span style='color:#8FA3C0;font-size:11px'>(hace 1 sem: {fg_idx.get('week', '—')} · 1 mes: {fg_idx.get('month', '—')})</span>"))
        rs_parts.append(_rline("Cartera de la semana", f"<b>{esc(cartera_txt)}</b>"))
        _ent = ", ".join(entering[:5]) or "—"
        _sal = ", ".join(leaving[:5]) or "—"
        rs_parts.append(_rline("Entrando (Mejorando)", f"<span style='color:#4CC2E0'>{esc(_ent)}</span>"))
        rs_parts.append(_rline("Saliendo (Debilitándose)", f"<span style='color:#F4B740'>{esc(_sal)}</span>"))
        if candidato:
            _t = candidato["top"]
            rs_parts.append(_rline("Candidato del sistema", f"<b style='color:#5B8CFF'>{_t['stock']['sym']}</b> (vía {_t['etf']}) — "
                                                             f"<span style='font-size:11px;color:#B9C9E2'>{esc(_t['why'])}</span>"))
        if contra_sigs:
            _cs = ", ".join(f"{s['sym']} ({s['n3']}/3)" for s in contra_sigs)
            rs_parts.append(_rline("Señal contraria 0/3", f"<span style='color:#7BD88F'>{esc(_cs)}</span> <span style='color:#8FA3C0;font-size:11px'>· tamaño pequeño, manga aparte</span>"))
        if suelo:
            _su = [r for r in suelo if r["pts"] >= 8 and not r["sangra"]]
            if _su:
                _st = ", ".join(f"{r['sym']} ({r['pts']}/10)" for r in _su[:4])
                rs_parts.append(_rline("Suelos potenciales", f"<span style='color:#2FD08A'>{esc(_st)}</span> <span style='color:#8FA3C0;font-size:11px'>· castigados, olvidados y dejando de sangrar</span>"))
        if excluded_di:
            rs_parts.append(_rline("Distribución oculta", f"<span style='color:#F4607A'>{esc(', '.join(excluded_di))}</span> — sube el precio, sale el dinero: fuera", "#F4607A"))
        if liq:
            rs_parts.append(_rline("Plan de liquidez", esc(liq)))
        if tperf:
            _c = tperf["cum"]
            _bc = _c["sys"] - _c.get("SPY", 0.0)
            _bcol = "#2FD08A" if _bc >= 0 else "#F4607A"
            rs_parts.append(_rline("Track record", f"sistema <b style='color:{_bcol}'>{_c['sys']*100:+.1f}%</b> vs SPY {_c.get('SPY', 0)*100:+.1f}% "
                                                    f"en {tperf['n']} semanas (<b style='color:{_bcol}'>{_bc*100:+.1f}%</b> de diferencia)"))
        rs_parts.append(_rline("Ojo esta semana", ojo))
        rs_parts.append("<div style='margin-top:14px;padding-top:8px;border-top:1px solid #2A3A55;font-size:9.5px;color:#7A8CA8;line-height:1.5'>"
                        "Contenido informativo y educativo. No es asesoramiento financiero personalizado ni recomendación de inversión (MiFID II / criterios CNMV). "
                        "Datos de cierre semanal (Stooq/Yahoo) con posible retardo. Rendimientos pasados no garantizan rendimientos futuros. "
                        "Los productos apalancados y CFD conllevan alto riesgo de pérdida rápida. Cada uno es responsable de sus decisiones."
                        "</div>")
        html.append("<div id='resumen-semanal' style='display:none;max-width:720px;margin:20px auto;background:#0A0E17;border:1px solid #24344F;"
                    "border-radius:12px;padding:22px 26px;color:#E8EEF9;font-family:inherit'>" + "".join(rs_parts) + "</div>")
    except Exception:
        # rollback: si el contenido falla, descartamos lo parcial y dejamos un resumen minimo,
        # para que las funciones de descarga (que van FUERA de este try) existan siempre.
        del html[_res_mark:]
        html.append("<div id='resumen-semanal' style='display:none;max-width:720px;margin:20px auto;background:#0A0E17;"
                    "border:1px solid #24344F;border-radius:12px;padding:22px 26px;color:#E8EEF9'>"
                    "<b>ROTACIÓN — resumen semanal</b><div class='note'>El resumen completo no se pudo generar esta semana. "
                    "Los datos están en las pestañas del terminal.</div></div>")
    # CSS de impresion + funciones de descarga: SIEMPRE presentes.
    # Clave del arreglo: antes de imprimir/capturar movemos #resumen-semanal a hijo directo de <body>;
    # si no, el selector de impresion ocultaba <main> entero y el PDF salia EN BLANCO.
    html.append("<style>@page{size:A4;margin:12mm}"
                "@media print{body.print-resumen>*:not(#resumen-semanal){display:none!important}"
                "body.print-resumen #resumen-semanal{display:block!important;-webkit-print-color-adjust:exact;print-color-adjust:exact;border:none;margin:0 auto}"
                "body.print-resumen{background:#0A0E17!important}}</style>")
    html.append("<script>"
                "function _resEl(){var r=document.getElementById('resumen-semanal');"
                "if(!r){alert('No hay resumen esta semana.');return null;}"
                "if(r.parentNode!==document.body){document.body.appendChild(r);}return r;}"
                "function descargarPDF(){var r=_resEl();if(!r)return;r.style.display='block';"
                "document.body.classList.add('print-resumen');"
                "setTimeout(function(){window.print();setTimeout(function(){r.style.display='none';document.body.classList.remove('print-resumen');},400);},80);}"
                "function _h2c(el,nombre,bg){function go(){html2canvas(el,{backgroundColor:bg||'#0A0E17',scale:2,useCORS:true}).then(function(c){"
                "var a=document.createElement('a');a.download=nombre;a.href=c.toDataURL('image/jpeg',0.92);a.click();"
                "if(el.id==='resumen-semanal'){el.style.display='none';}"
                "}).catch(function(e){alert('No se pudo generar el JPG: '+e);});}"
                "if(window.html2canvas){go();}else{var s=document.createElement('script');"
                "s.src='https://cdnjs.cloudflare.com/ajax/libs/html2canvas/1.4.1/html2canvas.min.js';"
                "s.onload=go;s.onerror=function(){alert('El JPG necesita internet (html2canvas). El botón PDF funciona sin conexión.');};"
                "document.head.appendChild(s);}}"
                "function descargarJPG(){var r=_resEl();if(!r)return;r.style.display='block';"
                f"_h2c(r,'resumen_rotacion_{_wk_lbl}.jpg');}}"
                "</script>")

    # ---- TOOLTIP UNIVERSAL: nombre del activo en CUALQUIER aparicion de un ticker en la pagina ----
    try:
        _tknames = {}
        for k, v in NAMES.items():
            try:
                _corto = v[1] if len(v) > 1 and v[1] else ""
                _largo = v[0] if v and v[0] else k
                _tknames[k.upper()] = (_corto + " · " + _largo) if (_corto and _corto != _largo) else _largo
            except Exception:
                continue
        for k, v in CARTERA_NOMBRES.items():
            _tknames.setdefault(k.upper(), v)
        for k, v in ALIAS2ETF.items():
            if v and k.upper() not in _tknames:
                _tknames[k.upper()] = f"→ se evalúa vía {v}"
        html.append("<script>var TKN=" + json.dumps(_tknames, ensure_ascii=False) + ";"
                    "(function(){"
                    # tooltip flotante
                    "var tip=document.createElement('div');"
                    "tip.style.cssText='position:fixed;z-index:9999;background:#111A2B;border:1px solid #3A5078;border-radius:6px;"
                    "padding:5px 10px;font-size:11.5px;color:#E8EEF9;pointer-events:none;display:none;max-width:280px;"
                    "box-shadow:0 4px 14px rgba(0,0,0,.55);line-height:1.4';"
                    "document.body.appendChild(tip);var hideT=null;"
                    "function showTip(el,txt){var r=el.getBoundingClientRect();tip.textContent=txt;tip.style.display='block';"
                    "var x=Math.min(r.left,window.innerWidth-290);var y=r.bottom+6;"
                    "if(y>window.innerHeight-56){y=r.top-34;}tip.style.left=Math.max(4,x)+'px';tip.style.top=y+'px';}"
                    # caminante del DOM: envuelve CADA aparicion de un ticker en nodos de texto
                    "var RX=new RegExp('\\\\b('+Object.keys(TKN).sort(function(a,b){return b.length-a.length;})"
                    ".map(function(k){return k.replace(/[-\\/\\\\^$*+?.()|[\\]{}]/g,'\\\\$&');}).join('|')+')\\\\b','g');"
                    "function walk(node){"
                    "if(node.nodeType===1){"
                    "var tg=node.tagName;"
                    "if(tg==='SCRIPT'||tg==='STYLE'||tg==='TEXTAREA'||tg==='CANVAS'||node.namespaceURI==='http://www.w3.org/2000/svg'||node.classList.contains('tkw')||node.classList.contains('bbgtape'))return;"
                    "for(var i=node.childNodes.length-1;i>=0;i--){walk(node.childNodes[i]);}"
                    "}else if(node.nodeType===3){"
                    "var t=node.nodeValue;if(!t||t.length<2)return;RX.lastIndex=0;if(!RX.test(t))return;RX.lastIndex=0;"
                    "var frag=document.createDocumentFragment();var last=0;var m;"
                    "while((m=RX.exec(t))!==null){"
                    "if(m.index>last){frag.appendChild(document.createTextNode(t.slice(last,m.index)));}"
                    "var sp=document.createElement('span');sp.className='tkw';sp.setAttribute('data-tk',m[1]);"
                    "sp.textContent=m[1];sp.style.cssText='border-bottom:1px dotted rgba(150,170,205,.45);cursor:help';"
                    "frag.appendChild(sp);last=m.index+m[1].length;}"
                    "if(last<t.length){frag.appendChild(document.createTextNode(t.slice(last)));}"
                    "node.parentNode.replaceChild(frag,node);}}"
                    "function marcar(){try{walk(document.querySelector('main')||document.body);}catch(e){}}"
                    "if(document.readyState==='loading'){document.addEventListener('DOMContentLoaded',marcar);}else{marcar();}"
                    # delegacion: raton y toque sobre los spans marcados (y fallback a elementos hoja)
                    "function chk(e){var el=e.target;if(!el||!el.getAttribute)return null;"
                    "var t=el.getAttribute('data-tk');"
                    "if(!t&&el.children&&el.children.length===0&&el.textContent){"
                    "t=el.textContent.replace(/[\\u25B2\\u25BC\\u2191\\u2193]/g,'').trim().toUpperCase();"
                    "if(t.length<2||t.length>16||!TKN[t])t=null;}"
                    "return t?{el:el,txt:t+' \\u2014 '+TKN[t]}:null;}"
                    "document.addEventListener('pointerover',function(e){var m=chk(e);"
                    "if(m){clearTimeout(hideT);showTip(m.el,m.txt);}"
                    "else{clearTimeout(hideT);hideT=setTimeout(function(){tip.style.display='none';},140);}});"
                    "document.addEventListener('click',function(e){var m=chk(e);"
                    "if(m){showTip(m.el,m.txt);clearTimeout(hideT);hideT=setTimeout(function(){tip.style.display='none';},2600);}},true);"
                    "window.addEventListener('scroll',function(){tip.style.display='none';},true);})();</script>")
    except Exception:
        pass

    html.append("<script>function mainView(v,b){document.getElementById('vista-ctx').style.display=(v=='ctx')?'contents':'none';"
                "document.getElementById('vista-op').style.display=(v=='op')?'contents':'none';"
                "var vg=document.getElementById('vista-vig');if(vg)vg.style.display=(v=='vig')?'contents':'none';"
                "var bg=document.getElementById('vista-bbg');if(bg)bg.style.display=(v=='bbg')?'contents':'none';"
                "var rd=document.getElementById('vista-rds');if(rd)rd.style.display=(v=='rds')?'contents':'none';"
                "var cl=document.getElementById('vista-cl');if(cl)cl.style.display=(v=='cl')?'contents':'none';"
                "document.querySelectorAll('.mainview').forEach(function(x){x.classList.remove('active')});b.classList.add('active');window.scrollTo(0,0);}</script>")
    html.append("</main>")
    gen = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    html.append("<footer>Actualizado: " + gen + " &middot; Herramienta de apoyo a la decision basada en fuerza relativa (estilo RRG) con datos de cierre reales "
                "de Stooq/Yahoo. No es asesoramiento financiero; los datos de fin de dia van con retardo y no sustituyen tu "
                "gestion de riesgo (tamano de posicion y stops).</footer>")
    html.append("<script>if('serviceWorker' in navigator){window.addEventListener('load',function(){navigator.serviceWorker.register('sw.js').catch(function(){});});}</script>")
    html.append("</body></html>")
    page = "".join(html)
    # Reordenar: el RRG (+ grafico TradingView) sube a la posicion del Radar de atencion; el radar baja a donde estaba el RRG.
    try:
        _rs = page.find("<div class='panel full'><h2>Grafico de rotacion relativa (RRG)</h2>")
        _re = page.find("<div class='panel full'><h2>Zona de entrada temprana")
        _rad = page.find("<div class='panel full'><h2>📡 Radar de atención")
        if 0 <= _rad < _rs < _re:
            seg = page[_rs:_re]
            page = page[:_rs] + page[_re:]
            page = page[:_rad] + seg + page[_rad:]
    except Exception:
        pass
    return page

# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    print("=" * 56)
    print(" ROTACION - Smart-Money Flow Terminal (escritorio)")
    print("=" * 56)
    df, daily, sources = download_all()
    df = add_sinteticos(df)
    if BENCH not in df.columns or len(df) < 30:
        print("\nNo hay suficientes datos comunes para calcular. Reintenta mas tarde.")
        return
    print(f"\nMatriz alineada: {len(df)} semanas x {len(df.columns)} activos.")

    rrg = compute_rrg(df)
    alerts = build_alerts(rrg)
    breadth, risk = breadth_risk(rrg)
    flow = compute_volume_flow(daily)
    spy_flow = compute_volume_flow(daily, only=BENCH).get(BENCH)
    heatmap = compute_heatmap(daily)
    scores = compute_scores(df, rrg, daily, flow)
    early = compute_early(df, rrg)
    meanrev = compute_mean_reversion(SECTORS + THEMATIC + EXTRA)
    fg_idx = fetch_fear_greed()
    probs = compute_probabilities(df, rrg)
    fred, fred_sig = fetch_fred()
    regime = detect_regime(df, rrg, risk, fred_sig)
    buy, avoid = conviction(rrg, regime)
    bt = backtest(df, rrg, hold=("leading", "improving")) if BACKTEST else None
    bt2 = backtest(df, rrg, hold=("leading", "improving", "weakening")) if BACKTEST else None
    long_close, long_src, long_hl = fetch_long_close()
    dd, dd_meta = (drawdown_stats(long_close, DD_THRESHOLDS, hl=long_hl) if long_close is not None else (None, None))
    plan = cash_plan(long_close) if long_close is not None else None
    season = {}
    sp_se = compute_seasonality(long_close) if long_close is not None else None
    if sp_se:
        season["S&P 500"] = sp_se
    print("  Estacionalidad: descargando Nasdaq y Russell (historico largo)...")
    nq_close, _, _ = _fetch_long("^ndx", "QQQ", "^NDX")
    nq_se = compute_seasonality(nq_close) if nq_close is not None else None
    if nq_se:
        season["Nasdaq 100"] = nq_se
    rut_close, _, _ = _fetch_long("^rut", "IWM", "^RUT")
    rut_se = compute_seasonality(rut_close) if rut_close is not None else None
    if rut_se:
        season["Russell 2000"] = rut_se
    if not season:
        season = None
    fx = fetch_fx()
    leaders, leaders_n, sector_breadth = compute_rs_leaders(fetch_stock_universe()) if STOCK_LEADERS else (None, 0, {})
    print("  Vigilancia: descargando acciones de la watchlist...")
    watch = compute_watchlist(WATCHLIST)
    _snap_main = state_summary(rrg, risk, regime, breadth, plan, flow)
    ai_text = ai_commentary(_snap_main)
    ia_auto = run_ia_auto(_snap_main, str(df.index[-1].date()))
    if ai_text:
        print("\n  Comentario IA generado.")

    # resumen en consola
    print("\n--- ALERTAS DE ROTACION ---")
    if alerts:
        for s, k, t in alerts:
            print(f"  [{k.upper():4s}] {s:5s} {t}")
    else:
        print("  Sin giros relevantes; liderazgo estable.")
    print(f"\n  Apetito de riesgo: {risk['label']} ({risk['score']:+})")
    print(f"  Amplitud: {breadth['leaders']}% con fuerza>indice | {breadth['uptrend']}% en tendencia")
    print(f"  Regimen macro{' (con FRED)' if fred else ''}: {regime['label']}")
    if buy:   print(f"  Alta conviccion alcista: {', '.join(buy)}")
    if avoid: print(f"  Evitar/reducir: {', '.join(avoid)}")
    divs = [s for s, d in (flow or {}).items() if d.get("diverg")]
    if divs: print(f"  Divergencias de flujo: {', '.join(divs)}")
    if bt:   print(f"  Backtest: estrategia {bt['tot_s']:+}% vs {BENCH} {bt['tot_b']:+}% ({bt['weeks']} sem)")
    if plan: print(f"  Caida actual del {BENCH} desde maximos: {plan['dd']}%")

    # avisos automaticos (Telegram / webhook) si hay giros, divergencias o caidas alcanzadas
    lines = []
    for s, k, t in alerts:
        lines.append(f"• {s}: {t}")
    for s, d in (flow or {}).items():
        if d.get("diverg"):
            lines.append(f"• {s}: {d['diverg']} (flujo de volumen)")
    if plan:
        for r in plan["rungs"]:
            if r["hit"]:
                lines.append(f"• Caida −{r['thr']}% del {BENCH} ALCANZADA → plan: desplegar {r['pct']}%")
    if lines:
        msg = (f"ROTACION {dt.date.today()} — {risk['label']} — {regime['label']}\n"
               + "\n".join(lines))
        if notify(msg):
            print("\nAviso enviado.")

    _giro = compute_giro_intradia(daily, rrg)
    html = build_html(df, rrg, alerts, breadth, risk, regime, buy, avoid, sources, fred, flow=flow, bt=bt,
                      dd=dd, dd_meta=dd_meta, plan=plan, fx=fx, long_src=long_src, ai_text=ai_text, leaders=leaders, leaders_n=leaders_n, bt2=bt2, heatmap=heatmap, scores=scores, probs=probs, season=season, early=early, sector_breadth=sector_breadth, meanrev=meanrev, nq_close=nq_close, fg_idx=fg_idx, spy_flow=spy_flow, watch=watch, giro=_giro, semis=compute_semis_desk(df, daily, rrg, flow, scores, leaders, _giro), ia_auto=ia_auto)
    os.makedirs(SITE_DIR, exist_ok=True)
    # copiar archivos estaticos (iconos, manifest, service worker) al sitio
    if os.path.isdir(STATIC_DIR):
        import shutil
        for root, _, files in os.walk(STATIC_DIR):
            rel = os.path.relpath(root, STATIC_DIR)
            dest = os.path.join(SITE_DIR, rel) if rel != "." else SITE_DIR
            os.makedirs(dest, exist_ok=True)
            for fn in files:
                shutil.copy2(os.path.join(root, fn), os.path.join(dest, fn))
    out = os.path.abspath(OUTPUT_HTML)
    with open(out, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"\nPanel generado: {out}")
    if scores:
        print("\n  PUNTUACION (de mayor a menor) — entra en 4-5/5, vende <=2/5:")
        for r in scores[:12]:
            acc = " ⚡" if r["obv_cross"] else ""
            ticks = "".join("✓" if v else "·" for _, v in r["parts"])
            print(f"    {r['sym']:5s} {r['score']}/5  [{ticks}]  mom3m {r['abs_mom']:+5.1f}%{acc}")
    if not os.environ.get("CI"):     # en local abre el navegador; en GitHub no
        try:
            webbrowser.open("file://" + out)
            print("Abriendo en el navegador...")
        except Exception:
            print("Abre el archivo manualmente en tu navegador.")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
