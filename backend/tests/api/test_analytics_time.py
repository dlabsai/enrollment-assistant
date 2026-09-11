from datetime import UTC, datetime

from app.api.routes.analytics_time import TimeGranularity, build_time_series_boundaries


def test_start_only_series_clips_first_boundary_and_fills_to_last_observation() -> None:
    first_day = datetime(2026, 8, 1, tzinfo=UTC)
    third_day = datetime(2026, 8, 3, tzinfo=UTC)
    start = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)

    boundaries = build_time_series_boundaries(
        [first_day, third_day], start, None, TimeGranularity.DAY
    )

    assert [boundary.start for boundary in boundaries] == [
        start,
        datetime(2026, 8, 2, tzinfo=UTC),
        third_day,
    ]
    assert boundaries[-1].end == datetime(2026, 8, 4, tzinfo=UTC)


def test_end_only_series_fills_from_first_observation_and_clips_last_boundary() -> None:
    first_day = datetime(2026, 8, 1, tzinfo=UTC)
    third_day = datetime(2026, 8, 3, tzinfo=UTC)
    end = datetime(2026, 8, 3, 12, 30, tzinfo=UTC)

    boundaries = build_time_series_boundaries(
        [first_day, third_day], None, end, TimeGranularity.DAY
    )

    assert boundaries[0].start == first_day
    assert [boundary.start for boundary in boundaries] == [
        first_day,
        datetime(2026, 8, 2, tzinfo=UTC),
        third_day,
    ]
    assert boundaries[-1].end == datetime(2026, 8, 3, 12, 30, 0, 1, tzinfo=UTC)


def test_one_sided_series_without_observations_is_empty() -> None:
    start = datetime(2026, 8, 1, 12, 30, tzinfo=UTC)

    assert build_time_series_boundaries([], start, None, TimeGranularity.DAY) == []
