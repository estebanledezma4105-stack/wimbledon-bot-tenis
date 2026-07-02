# ATP Accuracy Improvement (58.8% → 70-75%) - Design Spec

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve Wimbledon ATP prediction accuracy from 58.8% to 70-75% by adding ranking + recent form data, calibrating model weights via backtesting, and validating against 17 completed matches.

**Architecture:** Three-phase approach — (1) Scraper: extract ranking + recent form from tennisexplorer.com → DB, (2) Model: extend rating calculation with ranking bonus + recent form bonus, (3) Backtesting: grid search over weight combinations to find optimal accuracy, (4) Apply: lock in best weights.

**Tech Stack:** Python (scrapers, model, backtesting), SQLite (DB storage), BeautifulSoup (HTML parsing), existing wimbledon_bot.py + db.py infrastructure.

---

## 1. Database Schema Updates

### New Tables

**`atp_rankings`** — Current ATP ranking snapshot
- `player_id` INTEGER PRIMARY KEY (foreign key to `players.id`)
- `ranking_position` INTEGER (1-2000, where 1 = world #1)
- `ranking_points` INTEGER (optional, for analysis)
- `scraped_at` TEXT (ISO datetime when extracted)

**`recent_form`** — Performance in tournaments 6 weeks before Wimbledon
- `player_id` INTEGER PRIMARY KEY (foreign key to `players.id`)
- `tournaments_played` INTEGER (count of tournaments entered)
- `wins` INTEGER (total match wins in window)
- `losses` INTEGER (total match losses in window)
- `titles` INTEGER (tournaments won)
- `finals_reached` INTEGER (tournaments where reached final)
- `last_tournament_date` TEXT (ISO date of most recent tournament)
- `updated_at` TEXT (ISO datetime when computed)

### Schema Changes to Existing Tables

No changes to `draw_matches`, `players`, `h2h`, `grass_stats`, `form`, or `live_scores`. New data is additive only.

---

## 2. Scraper: Extract Ranking + Recent Form

### Source: tennisexplorer.com

**Ranking extraction:**
- URL: `https://www.tennisexplorer.com/players/` (player profile page)
- Parse: Look for ranking position (typically in player stats section, format: "Ranking: #123")
- Fallback: If parsing fails, skip silently; backtesting will use default ranking (2000 = unranked)

**Recent form extraction:**
- URL: Same player profile, tournament history section
- Parse: Filter tournaments by date (within 6 weeks of 2026-07-01 Wimbledon start = 2026-05-17 to 2026-06-30)
- Count: wins, losses, titles, finals, last_tournament_date
- Fallback: If no recent tournaments found, set all to 0 (valid state)

**Implementation file:** `scrapers/ranking_form.py`
- Function: `extract_ranking_and_form(player_name: str, session: httpx.Session) -> dict`
- Returns: `{"ranking_position": int, "wins": int, "losses": int, "titles": int, "finals": int, "last_date": str}` or None on error
- Error handling: Retry up to 2x with jittered backoff; return None on final failure (don't block pipeline)

**Rate limiting:** 1 request per 2 seconds (120 req/min limit on tennisexplorer); use `base.jittered_sleep(1.5, 2.5)`

---

## 3. Model: New Rating Bonuses

### Ranking Bonus: R(X)

```
R(X) = w_ranking × (2000 - ranking_position) / 1000
```

- `ranking_position` = player's ATP ranking (1-2000; 2000 means unranked/unknown)
- Top 10 (pos 1-10): bonus +0.5 to +2.0 rating points
- Top 50 (pos 11-50): bonus +0.15 to +0.5
- Outside top 100 (pos 101+): small negative bonus (handled by formula)
- Default (unknown): `ranking_position = 2000`, bonus ≈ 0

**Rationale:** Ranking is a direct, real-time measure of player strength; it should influence predictions but not dominate (hence `w_ranking` will be calibrated small, ~0.1-0.3).

### Recent Form Bonus: F_recent(X)

```
F_recent(X) = w_recent_form × (recent_win_pct - 0.5) × 100
```

- `recent_win_pct` = wins / (wins + losses) over last 6 weeks, capped [0, 1]
- If no recent tournaments: `recent_win_pct = 0.5` (neutral)
- Baseline (50% win rate) = 0 bonus
- 60% win rate (strong form) = +1.0 × w_recent_form
- 40% win rate (poor form) = -1.0 × w_recent_form

**Rationale:** Separates "historical ELO" (long-term skill) from "current momentum" (week-to-week readiness); captures surprises like Djokovic losing to Wu (may indicate injury, fatigue, or poor recent form).

### Updated Rating Function

```python
def calculate_rating(player_id, opponent_id, elo_dict, grass_stats, form_data, h2h_data, 
                     ranking_dict, recent_form_dict, fatigue_data=None):
    elo = elo_dict.get(player_id, 1500)
    grass = get_grass_bonus(player_id, grass_stats)
    form = get_form_bonus(player_id, form_data)
    h2h = get_h2h_bonus(player_id, opponent_id, h2h_data)
    fatigue = get_fatigue_bonus(player_id, fatigue_data or {})
    ranking = get_ranking_bonus(player_id, ranking_dict)        # NEW
    recent = get_recent_form_bonus(player_id, recent_form_dict) # NEW
    return elo + grass + form + h2h + fatigue + ranking + recent
```

---

## 4. Backtesting: Grid Search

### Objective

Find the combination of weights `(K_ELO, W_GRASS, W_FORM, W_H2H, W_FATIGUE, W_RANKING, W_RECENT_FORM)` that maximizes accuracy on the 17 completed matches.

### Grid Definition

```python
param_grid = {
    "K_ELO": [20, 25, 32, 40, 50],           # Current: 32
    "W_GRASS": [0.8, 1.0, 1.5, 2.0, 2.5],    # Current: 1.5
    "W_FORM": [0.3, 0.5, 0.7, 1.0, 1.5],     # Current: 0.7
    "W_H2H": [15, 20, 25, 30, 35],           # Current: 25
    "W_FATIGUE": [0.05, 0.10, 0.15, 0.20],   # Current: 0.15
    "W_RANKING": [0.0, 0.05, 0.10, 0.15, 0.20],  # NEW (tune small)
    "W_RECENT_FORM": [0.0, 0.05, 0.10, 0.15, 0.20], # NEW (tune small)
}
```

Total combinations: 5 × 5 × 5 × 5 × 4 × 5 × 5 = **12,500 runs** (acceptable; each run ~10ms).

### Backtesting Logic

```python
def backtest_weights(completed_matches, initial_elo, grass_stats, h2h, form_data, 
                     ranking_dict, recent_form_dict, weight_combo):
    """Run predictions on all 17 matches with given weight combo; return accuracy."""
    elo = initial_elo.copy()
    correct = total = 0
    
    for match in completed_matches:
        p1, p2, real_winner = match['player1'], match['player2'], match['winner']
        
        # Calculate ratings with current weight combo
        r_a = calculate_rating(p1, p2, elo, grass_stats, form_data, h2h, 
                              ranking_dict, recent_form_dict, K=weight_combo['K_ELO'], 
                              w_grass=weight_combo['W_GRASS'], ...)
        r_b = calculate_rating(p2, p1, elo, grass_stats, form_data, h2h, 
                              ranking_dict, recent_form_dict, K=weight_combo['K_ELO'], ...)
        
        # Predict
        prob_a = win_probability(r_a, r_b)
        predicted = p1 if prob_a >= 0.5 else p2
        
        # Evaluate
        if predicted == real_winner:
            correct += 1
        total += 1
        
        # Update ELO
        elo = update_elo_ratings(real_winner, p2 if real_winner == p1 else p1, elo, 
                                K=weight_combo['K_ELO'])
    
    return correct / total
```

### Execution

Script: `backtesting.py` (new file)
- Load 17 completed matches from `load_all_data()`
- Load ranking_dict + recent_form_dict from DB
- Iterate over all weight combos
- Track best accuracy + best weight combo
- Save best weights to stdout + file `backtesting_results.json`
- Print top 10 combos for review

Expected output: "Best accuracy: 72.5% with K_ELO=25, W_GRASS=1.0, W_FORM=0.7, W_H2H=20, W_FATIGUE=0.10, W_RANKING=0.12, W_RECENT_FORM=0.08"

---

## 5. Integration & Deployment

### Changes to Existing Files

**`wimbledon_bot.py`**
- Replace weight constants with backtesting-optimized values
- Add imports: `get_ranking_bonus()`, `get_recent_form_bonus()`
- Pass `ranking_dict`, `recent_form_dict` to `predict_match()` → `calculate_rating()`

**`db.py`**
- Add `init_atp_rankings()` and `init_recent_form()` table creation in `init_db()`
- Add `upsert_ranking(db_path, player_id, ranking_position, ranking_points)`
- Add `upsert_recent_form(db_path, player_id, wins, losses, titles, finals, last_date)`
- Extend `load_all_data()` to return `ranking_dict` and `recent_form_dict`

**`daily_update.py` (or new `ranking_update.py`)**
- After loading draw, scrape ranking + recent form for all players in the draw
- Call `scrapers.ranking_form.extract_ranking_and_form()` for each player
- Upsert results into DB
- Log summary: "Scraped ranking for 128 players; 3 failed"

### Files to Create

- `scrapers/ranking_form.py` — Ranking + recent form scraper
- `backtesting.py` — Grid search backtester
- `test_ranking_form.py` — Unit tests for scraper
- `test_backtesting.py` — Unit tests for backtester

---

## 6. Success Criteria

1. ✅ All 17 completed matches re-predict correctly (no regression)
2. ✅ New scraper extracts ranking for ≥120/128 players (94%+ coverage)
3. ✅ Backtesting finds a weight combo with ≥70% accuracy on the 17 matches
4. ✅ New weights are locked into `wimbledon_bot.py` and pushed to git
5. ✅ All tests pass (including new scraper + backtesting tests)
6. ✅ Live Telegram bot continues working with new weights

---

## 7. Timeline & Effort

- **Scraper (ranking_form.py):** 1-2 hours (HTML parsing, error handling, rate limiting)
- **Model (new bonuses):** 30 min (straightforward math)
- **Backtesting (grid search):** 1 hour (iterative search, I/O)
- **Integration (db.py + wimbledon_bot.py + daily_update.py):** 1-2 hours (plumbing)
- **Testing + validation:** 1 hour
- **Total:** 5-6 hours

---

## 8. Risk & Mitigations

| Risk | Mitigation |
|------|-----------|
| Scraper fails to extract ranking for many players | Fallback to default ranking=2000; log warnings; manual review of failed cases |
| Backtesting finds no improvement (70% not reachable) | Widen grid ranges, add new variables (e.g., Wimbledon historical win%), or accept current best |
| New weights overfit to 17 matches | Use cross-validation (hold-out 2 matches, test on remaining 15); retrain; compare |
| Live bot crashes with new weights | Validate in staging before deploy; have rollback plan (git revert + redeploy) |

---

## 9. Out of Scope (for later)

- Adding WTA (femenino) — separate project after ATP is validated
- Advanced backtesting (e.g., Bayesian optimization) — stick to grid search
- New data sources beyond tennisexplorer — keep dependencies minimal
- Momentum within Wimbledon itself — too early; first validate pre-tournament form

