"""Testes da conta EWMA (pura, sem Mongo) — a leitura/escrita de verdade
(read_baseline/update_baseline) fica de fora, igual o resto do projeto não
testa acesso cru a banco."""

from __future__ import annotations

from detection.baseline import MIN_SAMPLES_FOR_DEVIATION, ewma_update, hour_std


def test_first_sample_becomes_the_mean():
    mean, variance = ewma_update(mean=0.0, variance=0.0, count=0, value=5.0)
    assert mean == 5.0
    assert variance == 0.0


def test_second_sample_moves_the_mean_towards_the_new_value():
    mean, variance = ewma_update(mean=5.0, variance=0.0, count=1, value=15.0)
    assert 5.0 < mean < 15.0
    assert variance >= 0.0


def test_repeated_equal_values_keep_a_stable_mean_and_shrink_variance():
    mean, variance = 3.0, 1.0
    count = 10
    for _ in range(50):
        mean, variance = ewma_update(mean, variance, count, value=3.0)
        count += 1
    assert round(mean, 2) == 3.0
    assert variance < 1.0


def test_hour_std_is_zero_below_the_minimum_sample_count():
    assert hour_std(variance=4.0, sample_count=MIN_SAMPLES_FOR_DEVIATION - 1) == 0.0


def test_hour_std_is_the_square_root_of_variance_once_theres_enough_data():
    assert hour_std(variance=4.0, sample_count=MIN_SAMPLES_FOR_DEVIATION) == 2.0
