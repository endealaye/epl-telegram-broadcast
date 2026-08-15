from live import FIFAWorldCupProvider, SkySportsProvider, BBCProvider
import json

def main():
    providers = {
        "FIFA": FIFAWorldCupProvider(),
        "Sky": SkySportsProvider(),
        "BBC": BBCProvider()
    }
    
    all_results = {}
    for name, provider in providers.items():
        scores = provider.get_scores() or []
        all_results[name] = scores
    
    print(json.dumps(all_results, indent=2))

if __name__ == "__main__":
    main()
