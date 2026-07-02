
async def cmd_sets(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show set-by-set match probabilities."""
    try:
        texto = update.message.text.split(' ', 1)[1]
        players = texto.split(' vs ')
        if len(players) != 2:
            raise ValueError
        typed_a, typed_b = players[0], players[1]
    except:
        await update.message.reply_text("Formato: /sets Alcaraz vs Djokovic")
        return

    data = data_db.load_all_data(DB_PATH)
    a = _resolve_player_name(typed_a, data['elo'])
    b = _resolve_player_name(typed_b, data['elo'])
    if a is None or b is None:
        await update.message.reply_text("Uno de los jugadores no está en la base de datos.")
        return

    pred = predict_match(a, b, data)
    sets = pred['set_probabilities']

    mensaje = (f"🎾 *Sets: {a.title()} vs {b.title()}*\n\n"
               f"*3-0:* {sets['3-0']*100:.1f}%\n"
               f"*3-1:* {sets['3-1']*100:.1f}%\n"
               f"*3-2:* {sets['3-2']*100:.1f}%\n"
               f"*2-3:* {sets['2-3']*100:.1f}%\n"
               f"*1-3:* {sets['1-3']*100:.1f}%\n"
               f"*0-3:* {sets['0-3']*100:.1f}%")
    await update.message.reply_text(mensaje, parse_mode='Markdown')
