from live import FIFAWorldCupProvider
import json

def test():
    provider = FIFAWorldCupProvider()
    scores = provider.get_scores()
    print(json.dumps(scores, indent=2))

if __name__ == "__main__":
    test()
