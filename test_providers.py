from live import FIFAWorldCupProvider, SkySportsProvider, BBCProvider
from bot_config import TEAM_MAPPING

def test():
    providers = [FIFAWorldCupProvider(), SkySportsProvider(), BBCProvider()]
    for p in providers:
        print(f"Provider: {p.__class__.__name__}")
        try:
            scores = p.get_scores()
            print(f"Scores found: {len(scores) if scores else 0}")
            if scores:
                for s in scores:
                    if "Argentina" in s['home'] or "Argentina" in s['away']:
                        print(f"  Match: {s['home']} {s['h_score']}-{s['a_score']} {s['away']} ({s.get('competition')})")
        except Exception as e:
            print(f"  Error: {e}")

if __name__ == "__main__":
    test()
