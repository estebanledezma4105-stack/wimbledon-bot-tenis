#!/usr/bin/env python3
"""
Wimbledon 2026 Bot - Predicción de partidos ATP/WTA
Ejecutar: python wimbledon_bot.py
"""

import math
import os
import logging
from datetime import date

import db as data_db


def _load_dotenv(path=".env"):
    """Minimal .env loader (no external dependency): sets os.environ from
    KEY=VALUE lines, skipping blanks/comments, without overwriting variables
    already set in the real environment."""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

DB_PATH = os.path.join("data", "wimbledon.db")

# ===================== CONFIGURACIÓN =====================
# El token nunca se hardcodea: se lee de la variable de entorno TELEGRAM_TOKEN
# (definida en .env, que está en .gitignore). Evita que el secreto termine en git.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# Pesos del modelo (calibrables con backtesting)
K_ELO = 32          # Factor K para Grand Slam
W_GRASS = 1.5       # Peso del bonus por especialidad en hierba
W_FORM = 0.7        # Peso del factor de forma reciente
W_H2H = 25          # Peso del historial H2H
DAYS_FORM = 30      # Ventana de forma reciente

# ===================== MODELO PREDICTIVO =====================
def win_probability(rating_a, rating_b):
    """Probabilidad de que A gane a B (modelo logístico Elo)."""
    return 1.0 / (1 + 10 ** ((rating_b - rating_a) / 400.0))

def compute_elo_change(elo_winner, elo_loser, K=K_ELO):
    prob_winner = win_probability(elo_winner, elo_loser)
    return K * (1 - prob_winner)

def get_grass_bonus(player_id, grass_stats):
    """G(X) = w_grass * (Win%_grass - Win%_total) * 100"""
    stats = grass_stats.get(player_id, {})
    grass_wr = stats.get('grass_winrate', 0.5)
    total_wr = stats.get('total_winrate', 0.5)
    return W_GRASS * (grass_wr - total_wr) * 100

def get_form_bonus(player_id, form_data):
    """F(X) = w_form * puntos_forma"""
    return W_FORM * form_data.get(player_id, 0)

def get_h2h_bonus(player_a, player_b, h2h_data):
    """H(A,B) = w_h2h * (log(1 + victorias_A) - log(1 + victorias_B))"""
    # Buscar par en ambos sentidos
    pair = (player_a, player_b)
    record = h2h_data.get(str(pair)) or h2h_data.get(str((player_b, player_a)))
    if not record:
        return 0.0
    if str(pair) in h2h_data:
        a_wins = record.get('a_wins', 0)
        b_wins = record.get('b_wins', 0)
    else:
        a_wins = record.get('b_wins', 0)
        b_wins = record.get('a_wins', 0)
    return W_H2H * (math.log(1 + a_wins) - math.log(1 + b_wins))

def calculate_rating(player_id, opponent_id, elo_dict, grass_stats, form_data, h2h_data):
    elo = elo_dict.get(player_id, 1500)
    grass = get_grass_bonus(player_id, grass_stats)
    form = get_form_bonus(player_id, form_data)
    h2h = get_h2h_bonus(player_id, opponent_id, h2h_data)
    return elo + grass + form + h2h

def predict_match(player_a, player_b, data):
    elo = data['elo']
    grass = data['grass_stats']
    form = data['form']
    h2h = data['h2h']
    r_a = calculate_rating(player_a, player_b, elo, grass, form, h2h)
    r_b = calculate_rating(player_b, player_a, elo, grass, form, h2h)
    prob_a = win_probability(r_a, r_b)
    return {
        'player_a': player_a,
        'player_b': player_b,
        'prob_a': round(prob_a, 3),
        'prob_b': round(1 - prob_a, 3),
        'favorite': player_a if prob_a >= 0.5 else player_b
    }

def update_elo_ratings(winner_id, loser_id, elo_dict, K=K_ELO):
    delta = compute_elo_change(elo_dict.get(winner_id, 1500), elo_dict.get(loser_id, 1500), K)
    elo_dict[winner_id] = elo_dict.get(winner_id, 1500) + delta
    elo_dict[loser_id] = elo_dict.get(loser_id, 1500) - delta
    return elo_dict

# ===================== BACKTESTING =====================
def run_backtest(tournament_data, initial_elo, grass_stats, h2h, form_data):
    """Devuelve precisión (aciertos/total) usando datos históricos."""
    elo = initial_elo.copy()
    correct = total = 0
    for m in tournament_data:
        p1, p2, real_winner = m['player1'], m['player2'], m['winner']
        data = {'elo': elo, 'grass_stats': grass_stats, 'form': form_data, 'h2h': h2h}
        pred = predict_match(p1, p2, data)
        if pred['favorite'] == real_winner:
            correct += 1
        total += 1
        elo = update_elo_ratings(real_winner, p2 if real_winner == p1 else p1, elo)
    return correct / total if total > 0 else 0.0

# ===================== ACTUALIZADOR DIARIO =====================
def update_elo_from_results():
    """Actualiza ratings Elo con los partidos completados en draw_matches."""
    data = data_db.load_all_data(DB_PATH)
    completed = data['draw'].get('completed_matches', [])
    if not completed:
        return
    elo = data['elo']
    for m in completed:
        if m['winner']:
            winner = m['winner']
            loser = m['player2'] if m['player1'] == winner else m['player1']
            elo = update_elo_ratings(winner, loser, elo)
    for name, new_elo in elo.items():
        data_db.upsert_player(DB_PATH, name=name, elo=new_elo)
    print("Elo actualizado con resultados recientes.")

def update_form():
    """Calcula puntos de forma reciente (placeholder)."""
    # Debes implementar según tu fuente de datos
    pass

# ===================== BOT DE TELEGRAM =====================
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🎾 *Bot Wimbledon 2026*\n\n"
        "/predict `JugadorA vs JugadorB`\n"
        "/partidos - Predicciones de los partidos pendientes\n"
        "/draw - Todos los partidos del cuadro\n"
        "/live - Resultados en vivo\n"
        "/stats `Jugador` - Estadísticas completas",
        parse_mode='Markdown'
    )

def _resolve_player_name(typed_name, elo_dict):
    """Case-insensitive lookup of a user-typed name against the canonical
    (scraped, mixed-case) names used as keys in load_all_data()'s dicts."""
    lower_to_canonical = {name.lower(): name for name in elo_dict}
    return lower_to_canonical.get(typed_name.strip().lower())


async def cmd_predict(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        texto = update.message.text.split(' ', 1)[1]
        players = texto.split(' vs ')
        if len(players) != 2:
            raise ValueError
        typed_a, typed_b = players[0], players[1]
    except:
        await update.message.reply_text("Formato: /predict Nadal vs Djokovic")
        return

    data = data_db.load_all_data(DB_PATH)
    a = _resolve_player_name(typed_a, data['elo'])
    b = _resolve_player_name(typed_b, data['elo'])
    if a is None or b is None:
        await update.message.reply_text("Uno de los jugadores no está en la base de datos.")
        return

    pred = predict_match(a, b, data)
    pa, pb = pred['prob_a'] * 100, pred['prob_b'] * 100
    fav = pred['favorite'].title()
    mensaje = (f"📊 *{a.title()} vs {b.title()}*\n"
               f"🏆 Favorito: {fav}\n"
               f"🔹 {a.title()}: {pa:.1f}%\n"
               f"🔹 {b.title()}: {pb:.1f}%\n"
               f"_(Elo, hierba, forma y H2H)_")
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        typed_player = update.message.text.split(' ', 1)[1]
    except:
        await update.message.reply_text("Formato: /stats Alcaraz")
        return

    data = data_db.load_all_data(DB_PATH)
    player = _resolve_player_name(typed_player, data['elo'])
    if player is None:
        await update.message.reply_text("Jugador no encontrado.")
        return

    elo = data['elo'][player]
    gs = data['grass_stats'].get(player, {})
    grass_wr = gs.get('grass_winrate', 'N/A')
    total_wr = gs.get('total_winrate', 'N/A')
    form = data['form'].get(player, 0)
    rating = calculate_rating(player, "dummy", data['elo'], data['grass_stats'], data['form'], {})
    bonus = ((grass_wr - total_wr) * 100 * W_GRASS) if isinstance(grass_wr, float) else 'N/A'

    mensaje = (f"📈 *{player.title()}*\n"
               f"Elo: {elo:.1f}\n"
               f"Win% hierba: {grass_wr}\n"
               f"Win% total: {total_wr}\n"
               f"Bonus hierba: {bonus if isinstance(bonus,str) else f'{bonus:.1f}'}\n"
               f"Forma: {form:.1f} pts\n"
               f"Rating combinado: {rating:.1f}")
    await update.message.reply_text(mensaje, parse_mode='Markdown')

async def cmd_draw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = data_db.load_all_data(DB_PATH)
    matches = data['draw'].get('matches', [])
    if not matches:
        await update.message.reply_text("No hay partidos cargados para hoy.")
        return
    resp = "🗓 *Partidos del día:*\n\n"
    for m in matches:
        p1, p2 = m['player1'], m['player2']
        pred = predict_match(p1, p2, data)
        prob = max(pred['prob_a'], pred['prob_b']) * 100
        resp += f"{p1.title()} vs {p2.title()} ➜ {pred['favorite'].title()} ({prob:.0f}%)\n"
    await update.message.reply_text(resp, parse_mode='Markdown')

async def cmd_partidos(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Predicciones de los partidos programados para HOY (fecha real, no
    'todos los pendientes'). El scraper de draw marca cada partido con la
    fecha del día en que fue scrapeado como 'today' en tennisexplorer.com;
    cada nueva ronda que se scrapee en su propio día queda con su propia
    fecha, así que este comando muestra automáticamente solo la ronda
    vigente cada día del torneo, sin acumular rondas pasadas o futuras."""
    data = data_db.load_all_data(DB_PATH)
    matches = data['draw'].get('matches', [])
    today_str = date.today().isoformat()
    todays_matches = [m for m in matches if m.get('scheduled_date') == today_str and not m['winner']]
    if not todays_matches:
        await update.message.reply_text("No hay partidos programados para hoy todavía.")
        return
    resp = "🎾 *Predicciones de hoy:*\n\n"
    for m in todays_matches:
        p1, p2 = m['player1'], m['player2']
        pred = predict_match(p1, p2, data)
        prob = max(pred['prob_a'], pred['prob_b']) * 100
        resp += f"{p1.title()} vs {p2.title()} ➜ {pred['favorite'].title()} ({prob:.0f}%)\n"
    await update.message.reply_text(resp, parse_mode='Markdown')

_LIVE_STATUS_LABELS = {"in_progress": "en juego", "finished": "finalizado"}


async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    live = data_db.load_all_data(DB_PATH)['live_scores']
    if not live:
        await update.message.reply_text("No hay partidos en vivo.")
        return
    msg = "🔴 *En vivo:*\n"
    for match, info in live.items():
        status = info.get('status', '')
        status_label = _LIVE_STATUS_LABELS.get(status, status)
        msg += f"{match}: {info.get('sets','?')} ({status_label})\n"
    await update.message.reply_text(msg, parse_mode='Markdown')

# ===================== ENTRADA PRINCIPAL =====================
def run_bot():
    if not TELEGRAM_TOKEN:
        raise RuntimeError(
            "TELEGRAM_TOKEN no está configurado. Define la variable de entorno "
            "TELEGRAM_TOKEN con el token de @BotFather antes de ejecutar el bot."
        )
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("predict", cmd_predict))
    app.add_handler(CommandHandler("partidos", cmd_partidos))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("draw", cmd_draw))
    app.add_handler(CommandHandler("live", cmd_live))
    logger.info("Bot iniciado. Pulsa Ctrl+C para detener.")
    app.run_polling()

if __name__ == "__main__":
    import sys
    data_db.init_db(DB_PATH)
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        update_elo_from_results()
        update_form()
    elif len(sys.argv) > 1 and sys.argv[1] == "backtest":
        # Ejemplo: python wimbledon_bot.py backtest
        print("Carga tu archivo de partidos históricos y ejecuta run_backtest()")
    else:
        run_bot()
