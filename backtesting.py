"""Grid search backtesting script for weight calibration.

This module performs a grid search over 12,500 weight combinations to find
the optimal weights for the ATP/WTA match prediction model. The goal is to
calibrate the model to achieve >= 70% accuracy on historical match data.
"""

import itertools
import json
import os

import db as data_db
import wimbledon_bot as bot


def backtest_weights(completed_matches, initial_elo, grass_stats, h2h_data, form_data,
                     ranking_dict, recent_form_dict, weight_combo):
    """Backtest a single weight combination against completed matches.

    Args:
        completed_matches: List of dicts with 'player1', 'player2', 'winner' keys
        initial_elo: Dict mapping player name to initial Elo rating
        grass_stats: Dict mapping player name to grass stats
        h2h_data: Dict mapping player pair to head-to-head record
        form_data: Dict mapping player name to form points
        ranking_dict: Dict mapping player name to ranking (optional)
        recent_form_dict: Dict mapping player name to recent form data (optional)
        weight_combo: Dict with K_ELO, W_GRASS, W_FORM, W_H2H, W_FATIGUE, W_RANKING, W_RECENT_FORM

    Returns:
        float: Accuracy (0-1) for this weight combination
    """
    # Temporarily set the weights in the bot module
    bot.K_ELO = weight_combo['K_ELO']
    bot.W_GRASS = weight_combo['W_GRASS']
    bot.W_FORM = weight_combo['W_FORM']
    bot.W_H2H = weight_combo['W_H2H']
    bot.W_FATIGUE = weight_combo['W_FATIGUE']
    # W_RANKING and W_RECENT_FORM are not yet used in calculate_rating,
    # but we accept them for future extensibility

    # Copy the Elo dict so we can update it match by match
    elo = initial_elo.copy()
    correct = 0
    total = 0

    for match in completed_matches:
        player1 = match['player1']
        player2 = match['player2']
        winner = match['winner']

        if winner is None:
            continue

        # Build data dict for prediction
        data = {
            'elo': elo,
            'grass_stats': grass_stats,
            'form': form_data,
            'h2h': h2h_data,
            'fatigue': {},  # Not tracked in completed_matches yet
        }

        # Make prediction
        prediction = bot.predict_match(player1, player2, data)
        predicted_winner = prediction['favorite']

        # Check if prediction was correct
        if predicted_winner == winner:
            correct += 1
        total += 1

        # Update Elo ratings after the match
        loser = player2 if winner == player1 else player1
        elo = bot.update_elo_ratings(winner, loser, elo, K=weight_combo['K_ELO'])

    # Return accuracy
    return correct / total if total > 0 else 0.0


def run_grid_search(completed_matches, initial_elo, grass_stats, h2h_data, form_data,
                    ranking_dict, recent_form_dict):
    """Run a grid search over weight combinations to find the best performer.

    Grid parameters:
    - K_ELO: [20, 25, 32, 40, 50]
    - W_GRASS: [0.8, 1.0, 1.5, 2.0, 2.5]
    - W_FORM: [0.3, 0.5, 0.7, 1.0, 1.5]
    - W_H2H: [15, 20, 25, 30, 35]
    - W_FATIGUE: [0.05, 0.10, 0.15, 0.20]
    - W_RANKING: [0.0, 0.05, 0.10, 0.15, 0.20]
    - W_RECENT_FORM: [0.0, 0.05, 0.10, 0.15, 0.20]

    Total combinations: 5 * 5 * 5 * 5 * 4 * 5 * 5 = 12,500

    Args:
        completed_matches: List of dicts with 'player1', 'player2', 'winner' keys
        initial_elo: Dict mapping player name to initial Elo rating
        grass_stats: Dict mapping player name to grass stats
        h2h_data: Dict mapping player pair to head-to-head record
        form_data: Dict mapping player name to form points
        ranking_dict: Dict mapping player name to ranking
        recent_form_dict: Dict mapping player name to recent form data

    Returns:
        dict: {'best_accuracy': float, 'best_weights': dict, 'top_10': list}
    """
    # Define grid parameters
    K_ELO_values = [20, 25, 32, 40, 50]
    W_GRASS_values = [0.8, 1.0, 1.5, 2.0, 2.5]
    W_FORM_values = [0.3, 0.5, 0.7, 1.0, 1.5]
    W_H2H_values = [15, 20, 25, 30, 35]
    W_FATIGUE_values = [0.05, 0.10, 0.15, 0.20]
    W_RANKING_values = [0.0, 0.05, 0.10, 0.15, 0.20]
    W_RECENT_FORM_values = [0.0, 0.05, 0.10, 0.15, 0.20]

    results = []  # List of (accuracy, weights) tuples
    combo_count = 0

    # Generate all combinations
    for k_elo, w_grass, w_form, w_h2h, w_fatigue, w_ranking, w_recent_form in itertools.product(
        K_ELO_values, W_GRASS_values, W_FORM_values, W_H2H_values,
        W_FATIGUE_values, W_RANKING_values, W_RECENT_FORM_values
    ):
        combo_count += 1

        # Create weight combination dict
        weight_combo = {
            'K_ELO': k_elo,
            'W_GRASS': w_grass,
            'W_FORM': w_form,
            'W_H2H': w_h2h,
            'W_FATIGUE': w_fatigue,
            'W_RANKING': w_ranking,
            'W_RECENT_FORM': w_recent_form,
        }

        # Run backtest for this combination
        accuracy = backtest_weights(
            completed_matches,
            initial_elo.copy(),
            grass_stats,
            h2h_data,
            form_data,
            ranking_dict,
            recent_form_dict,
            weight_combo
        )

        results.append((accuracy, weight_combo))

        # Print progress every 1000 combinations
        if combo_count % 1000 == 0:
            best_so_far = max(results, key=lambda x: x[0])[0]
            print(f"Progress: {combo_count} combinations evaluated, best accuracy so far: {best_so_far:.4f}")

    # Sort by accuracy descending
    results.sort(key=lambda x: x[0], reverse=True)

    # Extract best and top 10
    best_accuracy, best_weights = results[0]
    top_10 = [
        {'accuracy': acc, 'weights': weights}
        for acc, weights in results[:10]
    ]

    return {
        'best_accuracy': best_accuracy,
        'best_weights': best_weights,
        'top_10': top_10,
    }


if __name__ == "__main__":
    # Load data
    DB_PATH = os.path.join("data", "wimbledon.db")
    data_db.init_db(DB_PATH)
    data = data_db.load_all_data(DB_PATH)

    completed_matches = data['draw']['completed_matches']
    initial_elo = data['elo']
    grass_stats = data['grass_stats']
    h2h_data = data['h2h']
    form_data = data['form']

    print(f"Starting grid search on {len(completed_matches)} completed matches...")
    print(f"Baseline accuracy: {len([m for m in completed_matches if m.get('winner')])} matches")

    # Run grid search
    results = run_grid_search(
        completed_matches,
        initial_elo,
        grass_stats,
        h2h_data,
        form_data,
        {},  # ranking_dict
        {},  # recent_form_dict
    )

    # Save results
    output_file = "backtesting_results.json"
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\nGrid search complete!")
    print(f"Best accuracy: {results['best_accuracy']:.4f}")
    print(f"Best weights: {results['best_weights']}")
    print(f"\nTop 10 combinations:")
    for i, item in enumerate(results['top_10'], 1):
        print(f"{i}. Accuracy: {item['accuracy']:.4f}")
        print(f"   K_ELO: {item['weights']['K_ELO']}, W_GRASS: {item['weights']['W_GRASS']}, "
              f"W_FORM: {item['weights']['W_FORM']}, W_H2H: {item['weights']['W_H2H']}, "
              f"W_FATIGUE: {item['weights']['W_FATIGUE']}")

    print(f"\nResults saved to {output_file}")
