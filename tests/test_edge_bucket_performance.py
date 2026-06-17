from tests.test_blocked_recommendation_analysis import record
from football_agents.edge_quality_optimizer import build_edge_bucket_performance


def test_bucket_performance_groups_edge_quality_and_odds():
    records = [record(True, -1, -.02), record(False, 1, .02)]
    buckets = build_edge_bucket_performance(records)
    keys = {(bucket.bucket_type, bucket.bucket_name) for bucket in buckets}
    assert ("edgeQualityLevel", "LOW") in keys
    assert ("oddsBucket", "2.00-3.00") in keys
    assert all(bucket.sample_count >= 1 for bucket in buckets)
