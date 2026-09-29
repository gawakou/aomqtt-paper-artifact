from aomqtt.policy_auto.metrics import aggregate_observation_metrics


def test_aggregate_observation_metrics(tmp_path):
    pub = tmp_path / "publisher_metrics.csv"
    sub = tmp_path / "subscriber_metrics.csv"

    pub.write_text(
        "seq,avg_publish_complete_ms,payload_total_overhead_bytes,reconnect_count\n"
        "1,10,100,0\n"
        "2,20,200,1\n",
        encoding="utf-8",
    )

    sub.write_text(
        "seq,delivery_latency_ms,decrypt_success\n"
        "1,30,true\n"
        "2,40,true\n"
        "2,45,true\n",
        encoding="utf-8",
    )

    metrics = aggregate_observation_metrics(
        publisher_metrics_csv=pub,
        subscriber_metrics_csv=sub,
    )

    assert metrics.publisher_rows == 2
    assert metrics.subscriber_rows == 3
    assert metrics.avg_publish_complete_ms == 15
    assert metrics.avg_payload_total_overhead_bytes == 150
    assert metrics.reconnect_count == 1
    assert metrics.avg_delivery_latency_ms == 115 / 3
    assert metrics.duplicate_rate is not None
    assert metrics.decrypt_success_rate == 1.0
