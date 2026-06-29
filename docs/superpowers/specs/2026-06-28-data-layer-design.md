# Capa de Datos — Wimbledon Bot (Sub-proyecto 1 de 4)

## Contexto

El bot de predicción Wimbledon 2026 (`wimbledon_bot.py`) existe pero todos sus datos (`elo_ratings.json`, `grass_stats.json`, `form.json`, `h2h.json`, `draw.json`, `live_scores.json`) son placeholders vacíos. No hay forma de obtener datos reales. Este es el primer de cuatro sub-proyectos:

1. **Capa de datos** (este documento)
2. Motor de predicción (corrección de bugs, mejoras al modelo, backtesting real)
3. Bot de Telegram en producción (deploy en VPS, manejo de errores)
4. Monetización/distribución (a futuro)

Producto destinado a compartir/vender a otros usuarios. Hosting en VPS/cloud. Datos obtenidos por scraping de sitios públicos (no hay presupuesto de API de pago decidido).

## Objetivo

Reemplazar los JSON placeholder por un pipeline de scraping real que alimenta una base SQLite, de la cual el bot lee en producción.

## Fuentes de datos

- **wimbledon.com** (oficial): draw del torneo, resultados en vivo. Estructura más estable durante el torneo en curso.
- **tennisexplorer.com**: rankings ATP/WTA, historial H2H, estadísticas por superficie (win% hierba vs total). HTML más simple de scrapear que atptour.com/wtatennis.com.

## Arquitectura

Módulo `scrapers/` separado del bot. Escribe a `data/wimbledon.db` (SQLite), reemplazando los archivos JSON sueltos. El bot (`wimbledon_bot.py`) pasa de `load_json`/`save_json` a queries vía `db.py`.

### Componentes

- `scrapers/base.py` — sesión HTTP compartida, rate-limiting, retry con backoff exponencial (máx. 3 intentos), user-agent rotativo básico.
- `scrapers/rankings.py` — ATP/WTA rankings → tabla `players` (elo inicial, ranking).
- `scrapers/h2h.py` — historial cara a cara por par de jugadores → tabla `h2h`.
- `scrapers/surface_stats.py` — win% en hierba vs total → tabla `grass_stats`.
- `scrapers/draw.py` — cuadro de Wimbledon (rondas, partidos, ganadores) → tabla `draw_matches`.
- `scrapers/live.py` — marcador en vivo (sets, estado) → tabla `live_scores`, polling cada 2-3 min solo en días de partido.

**Nota sobre wimbledon.com**: sitios de torneos oficiales suelen ser SPA (React/Next.js) protegidos por Cloudflare — parsear el DOM con BeautifulSoup es frágil y propenso a bloqueos. `scrapers/draw.py` y `scrapers/live.py` deben primero inspeccionar las pestañas de red del sitio (XHR/Fetch) para localizar el endpoint JSON interno que alimenta el marcador en vivo, y consumir ese endpoint directamente en vez de parsear HTML. Si no se encuentra un endpoint JSON estable, usar Playwright (render JS) como fallback antes de recurrir a parseo de HTML estático.
- `db.py` — capa de acceso (esquema, queries, migraciones simples). Reemplaza `load_json`/`save_json`.
- `name_resolver.py` — normalización de nombres de jugadores (ver abajo).

### Estrategia anti-bloqueo

Backoff exponencial cubre fallos de red, pero no evita bloqueos por detección de patrón no-humano. Cada request iterativo (ej. recorrer páginas de rankings) debe introducir un retraso aleatorio (jitter) entre peticiones — p. ej. `time.sleep(random.uniform(1.5, 4.2))` — en vez de un intervalo fijo.

### Manejo de errores

- Cada scraper captura fallos de red/parseo, loguea, y NO rompe el resto del pipeline — un scraper caído no detiene a los demás.
- Reintentos con backoff exponencial (máx. 3 intentos) ante fallos de red.
- Si el HTML cambia y el parser falla en extraer datos esperados, debe loguearse explícitamente como warning (nunca devolver vacío en silencio).

### Programación (scheduler)

Ejecutado vía `cron` en el VPS (o `APScheduler` si se prefiere mantenerlo en proceso Python):

- Rankings / H2H / surface stats: 1x/día.
- Draw: cada 6h durante el torneo.
- Live scores: cada 2-3 min, solo durante horario de partidos.

## Esquema SQLite

```
players(id, name, elo, ranking, last_updated)
player_aliases(alias_name, player_id)
unresolved_names(raw_name, source, first_seen)
h2h(player_a_id, player_b_id, a_wins, b_wins)   -- normalizado: player_a_id < player_b_id
grass_stats(player_id, grass_winrate, total_winrate, matches_played)
form(player_id, points, last_updated)            -- alimentado por update_form() real
draw_matches(id, tournament_id, year, round, player1_id, player2_id, winner_id, completed_at)
live_scores(match_id REFERENCES draw_matches(id), sets, status, updated_at)
scraper_runs(id, source, status, rows_fetched, error_message, started_at, finished_at)
match_stats(match_id REFERENCES draw_matches(id), player_id, first_serve_pct, break_points_saved, aces, double_faults)  -- placeholder para futura profundidad analítica; no se llena en este sub-proyecto
```

`draw_matches` incluye `tournament_id`/`year` desde el inicio para poder distinguir ediciones (2025 vs 2026) y soportar backtesting histórico en el sub-proyecto 2 sin tener que migrar el esquema después.

`match_stats` queda definida pero fuera de alcance de implementación en este sub-proyecto — es la puerta abierta para estadísticas granulares (% primer servicio, puntos de quiebre salvados, etc.) que el motor de predicción podrá aprovechar más adelante, similar a métricas xG/xA en fútbol.

### Normalización de nombres

Los sitios de origen casi nunca escriben los nombres de jugadores de forma idéntica ("C. Alcaraz" vs "Carlos Alcaraz" vs "Alcaraz C."). Sin resolución, los joins entre tablas fallan en silencio o crean jugadores duplicados.

- `player_aliases(alias_name, player_id)` mapea variantes de nombre a un `player_id` canónico.
- **Seed manual obligatorio**: antes de activar fuzzy matching, se inserta un diccionario hardcodeado (JSON en el repo, cargado en la migración inicial) con los alias conocidos del Top 100 ATP/WTA actual. Esto evita que casos ambiguos de nombres similares pero distintos (ej. "A. Zverev" vs "M. Zverev", hermanos) se fusionen incorrectamente — el fuzzy match nunca debe ser la única fuente de verdad para jugadores de alto perfil.
- Librería: `rapidfuzz` (más rápida que `thefuzz`/`fuzzywuzzy`, misma API de scoring).
- Cada scraper, al encontrar un nombre nuevo: (1) busca en `player_aliases`; (2) si no existe, aplica `rapidfuzz` contra `players` con umbral estricto (similitud > 90%) y, solo si lo supera, registra el alias; (3) si no supera el umbral, lo inserta en `unresolved_names` para revisión manual en vez de crear un jugador duplicado o fusionar incorrectamente.

### Log de ejecuciones de scraper

- `scraper_runs` registra una fila por cada ejecución de cada scraper (éxito o fallo), incluyendo `rows_fetched`.
- Permite detectar de inmediato cuándo un scraper empezó a devolver 0 filas (señal típica de que el sitio cambió su HTML), sin tener que revisar logs de texto.
- Comando opcional `/healthcheck` en el bot, que muestra el estado de la última ejecución de cada scraper.

## Migración del código actual

Las funciones de predicción (`predict_match`, `calculate_rating`, `get_h2h_bonus`, etc.) no cambian su lógica — solo cambia de dónde vienen los diccionarios `elo`, `grass_stats`, `form`, `h2h` (ahora de `db.py` en vez de JSON). La tabla `h2h` normalizada (`player_a_id < player_b_id`) elimina de raíz el bug actual de lookup por clave string-tupla.

## Testing

- Tests unitarios por parser, usando fixtures HTML guardados localmente (sin requests reales en tests).
- Test de integración manual que corre el scraper real contra el sitio en vivo y valida que los datos devueltos tienen la forma esperada (no se automatiza en CI por dependencia de red externa).

## Fuera de alcance (sub-proyectos futuros)

- Mejoras al motor de predicción (modelo, backtesting).
- Deploy en VPS, proceso de despliegue, manejo de errores del bot en producción.
- Monetización y distribución del bot.
