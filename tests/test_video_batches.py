import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from video_batches import (  # noqa: E402
    CHAMPIONS_LEAGUE,
    EUROPA_LEAGUE,
    GENERAL,
    MIN_MERGED_STORIES,
    PREMIER_LEAGUE,
    batch_id,
    group_by_category,
    split_by_size,
    story_category,
)


def story(item_id, source_key="bbc_football_rss", tags=None):
    return {"id": item_id, "source_key": source_key, "topic_tags": tags or []}


class StoryCategoryTests(unittest.TestCase):
    def test_competition_tag_wins(self):
        item = story(1, "bbc_football_rss", ["competition:champions_league", "topic:gossip"])
        self.assertEqual(story_category(item), CHAMPIONS_LEAGUE)

    def test_source_is_the_fallback_when_tag_is_missing(self):
        # Real case: Guardian Champions League reports with only a format tag.
        item = story(15908, "guardian_champions_league_rss", ["format:post_match"])
        self.assertEqual(story_category(item), CHAMPIONS_LEAGUE)
        self.assertEqual(story_category(story(2, "guardian_europa_league_rss")), EUROPA_LEAGUE)
        self.assertEqual(story_category(story(3, "sky_sports_premier_league_rss")), PREMIER_LEAGUE)

    def test_gossip_counts_as_premier_league(self):
        self.assertEqual(story_category(story(15913, "bbc_football_rss", ["topic:gossip"])), PREMIER_LEAGUE)

    def test_everything_else_is_general(self):
        self.assertEqual(story_category(story(4, "bbc_football_rss", ["format:post_match"])), GENERAL)
        self.assertEqual(story_category({"id": 5}), GENERAL)


class GroupingTests(unittest.TestCase):
    def test_groups_keep_item_order_and_category_order(self):
        items = [
            story(1, "guardian_champions_league_rss"),
            story(2, "sky_sports_premier_league_rss"),
            story(3, "guardian_champions_league_rss"),
        ]
        groups = group_by_category(items)
        self.assertEqual(list(groups), [PREMIER_LEAGUE, CHAMPIONS_LEAGUE])
        self.assertEqual([i["id"] for i in groups[CHAMPIONS_LEAGUE]], [1, 3])

    def test_minimum_is_three_and_has_no_upper_cap(self):
        self.assertEqual(MIN_MERGED_STORIES, 3)
        many = [story(i, "guardian_champions_league_rss") for i in range(40)]
        self.assertEqual(len(group_by_category(many)[CHAMPIONS_LEAGUE]), 40)


class SplitBySizeTests(unittest.TestCase):
    def test_fits_in_one_part_whatever_the_story_count(self):
        sizes = [1_000_000] * 12
        self.assertEqual(split_by_size(sizes, 49_000_000), [list(range(12))])

    def test_splits_by_size_balanced_in_order_and_loses_nothing(self):
        sizes = [10] * 25  # 250 bytes, budget 100 -> 3 parts
        parts = split_by_size(sizes, 100)
        self.assertEqual(len(parts), 3)
        self.assertEqual([i for part in parts for i in part], list(range(25)))
        for part in parts:
            self.assertLessEqual(sum(sizes[i] for i in part), 100)

    def test_empty(self):
        self.assertEqual(split_by_size([], 100), [])


class BatchIdTests(unittest.TestCase):
    def test_batch_id_uses_eat_clock(self):
        now = datetime(2026, 10, 22, 2, 40, tzinfo=timezone.utc)
        self.assertEqual(batch_id(now, CHAMPIONS_LEAGUE), "20261022-0540-champions_league")


if __name__ == "__main__":
    unittest.main()
