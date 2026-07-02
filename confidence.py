from typing import Dict

class ConfidenceScorer:
    def score(self, data: Dict) -> Dict:
        h2h = data.get('h2h_matches', 0)
        form = data.get('form_window_size', 0)
        grass = data.get('grass_winrate') is not None
        total = data.get('total_matches', 0)

        reasons = []
        score = 0.0

        if h2h >= 10:
            score += 0.30
            reasons.append("Extensive H2H history")
        elif h2h >= 1:
            score += 0.15
            reasons.append("Moderate H2H history")
        else:
            reasons.append("Limited or no H2H data")

        if form >= 5:
            score += 0.20
            reasons.append("Recent tournament activity")
        elif form >= 2:
            score += 0.10
            reasons.append("Some recent form data")
        else:
            reasons.append("Sparse recent form data")

        if grass:
            score += 0.20
            reasons.append("Grass court history available")
        else:
            reasons.append("No grass court history")

        if total >= 150:
            score += 0.30
            reasons.append("Experienced player")
        elif total >= 50:
            score += 0.15
            reasons.append("Moderately experienced")
        else:
            reasons.append("Limited career matches")

        score = min(score, 1.0)

        if score >= 0.75:
            level = 'HIGH'
        elif score >= 0.50:
            level = 'MEDIUM'
        else:
            level = 'LOW'

        return {
            'score': round(score, 2),
            'level': level,
            'reasons': reasons
        }
