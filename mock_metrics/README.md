# Mock Metrics

## Хороший тест для Prometheus

Генерация файла:

```powershell
python mock_metrics/generate_prometheus_good_test.py
```

Загрузка истории в контейнер `prometheus`:

```powershell
docker compose exec prometheus promtool tsdb create-blocks-from openmetrics /mock_metrics/output/prometheus_good_test.prom /prometheus
docker compose restart prometheus
```

## Неуспешный тест для Prometheus

Генерация файла:

```powershell
python mock_metrics/generate_prometheus_bad_test.py
```

Загрузка истории в контейнер `prometheus`:

```powershell
docker compose exec prometheus promtool tsdb create-blocks-from openmetrics /mock_metrics/output/prometheus_bad_test.prom /prometheus
docker compose restart prometheus
```

## Хороший тест для InfluxDB

Генерация часового набора бизнес-метрик:

```powershell
python mock_metrics/generate_influx_good_test.py
```

Загрузка в `InfluxDB`:

```powershell
docker exec lt-report-influxdb influx delete --bucket lt-metrics --org lt-report --token lt-report-token --start ${start_time} --stop ${stop_time} --predicate "_measurement=\"jmeter_samples\" AND test_name=\"good_test\""
docker cp mock_metrics/output/influx_good_test.lp lt-report-influxdb:/tmp/influx_good_test.lp
docker exec lt-report-influxdb influx write --bucket lt-metrics --org lt-report --token lt-report-token --file /tmp/influx_good_test.lp
```

## Неуспешный тест для InfluxDB

Генерация часового набора бизнес-метрик:

```powershell
python mock_metrics/generate_influx_bad_test.py
```

Загрузка в `InfluxDB`:

```powershell
docker exec lt-report-influxdb influx delete --bucket lt-metrics --org lt-report --token lt-report-token --start ${start_time} --stop ${stop_time} --predicate "_measurement=\"jmeter_samples\" AND test_name=\"bad_test\""
docker cp mock_metrics/output/influx_bad_test.lp lt-report-influxdb:/tmp/influx_bad_test.lp
docker exec lt-report-influxdb influx write --bucket lt-metrics --org lt-report --token lt-report-token --file /tmp/influx_bad_test.lp
```