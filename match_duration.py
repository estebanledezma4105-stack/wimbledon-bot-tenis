from typing import List, Optional

class MatchDuration:
    PLAYER_STYLE_FACTORS = {
        "Alcaraz": 0.95,
        "Djokovic": 1.15,
        "Nadal": 1.10,
        "Federer": 0.90,
        "Murray": 1.05,
    }

    def baseline_minutes(self) -> int:
        return 150

    def playing_style_factor(self, player_name: str) -> float:
        return self.PLAYER_STYLE_FACTORS.get(player_name, 1.0)

    def fatigue_penalty(self, recent_games: List[int]) -> float:
        if not recent_games:
            return 0.0
        avg_recent = sum(recent_games) / len(recent_games)
        excess = max(0, avg_recent - 150)
        return min(0.15, excess * 0.001)

    def estimate(self, player_a: str, player_b: str,
                recent_a: Optional[List[int]] = None,
                recent_b: Optional[List[int]] = None) -> int:
        base = self.baseline_minutes()
        style_a = self.playing_style_factor(player_a)
        style_b = self.playing_style_factor(player_b)
        avg_style = (style_a + style_b) / 2
        fatigue_a = self.fatigue_penalty(recent_a or [])
        fatigue_b = self.fatigue_penalty(recent_b or [])
        avg_fatigue = (fatigue_a + fatigue_b) / 2
        estimate = base * avg_style - (avg_fatigue * base)
        return int(round(estimate))
