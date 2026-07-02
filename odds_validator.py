class OddsValidator:
    def american_to_probability(self, american_odds: float) -> float:
        if american_odds < 0:
            return abs(american_odds) / (abs(american_odds) + 100)
        else:
            return 100 / (american_odds + 100)

    def decimal_to_probability(self, decimal_odds: float) -> float:
        return 1.0 / decimal_odds

    def is_value(self, model_prob: float, implied_prob: float,
                 min_ev: float = 0.05) -> bool:
        return model_prob > (implied_prob + min_ev)
