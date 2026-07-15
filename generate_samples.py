from broadcasts import _render_results_news_style
import os

# Sample data for Results Board
groups = [
    ("FIFA World Cup", [
        {"home": "Switzerland", "away": "Algeria", "home_score": 2, "away_score": 0, "result_note": "Round of 32"},
        {"home": "Portugal", "away": "Croatia", "home_score": 2, "away_score": 1, "result_note": "Round of 32"},
    ])
]

print("Generating results board sample...")
results_path = _render_results_news_style("🏁 የጨዋታዎች ውጤት", "2026-07-03", groups)
print(f"Results board saved to: {results_path}")
