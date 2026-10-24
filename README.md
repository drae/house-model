# House model

A Home Assistant integration that learns how much gas the house uses for the weather, forecasts it, and keeps score of its own forecasts.

It reads the recorder's long-term statistics, so it can start from the history you already have. It only predicts: it never controls anything.

## What it does

Every hour it:

1. Reads hourly statistics for gas, outdoor temperature and (optionally) heating time, from 1 September (the start of the heating season).
2. Fits each candidate model on the days before today.
3. Forecasts today and every day to the end of the month (at least 10 days) from the weather entity's daily forecast. After the forecast runs out, it uses the last week's mean temperature.
4. Scores every model, keeps the one with the lowest error and exposes the result.

## Models

All three are degree-day regressions on the 2-day mean outdoor temperature (the house holds heat, so yesterday counts as much as today):

`gas per day = a + b × max(0, base − t2)`

| Name | Fit |
| --- | --- |
| `ols15` | Least squares, base 15 °C, last 30 days from the first day using 5 kWh or more |
| `change_point` | Least squares with the base temperature fitted (10–18 °C), last 30 days |
| `bayes` | Base fitted, the whole season with older days fading (half-life 21 days), and a loose prior of 1.5 kWh/day + 3 kWh per degree-day so it gives sensible answers from the first days of the season |

### Scoring

- Each model's forecast for today is saved the first time it is made each day. Once the day is over, it is compared with what the meter recorded.
- Until there are enough saved forecasts, days earlier in the season are scored by refitting on the days before each one and forecasting it with the temperature that was actually recorded.
- The model with the lowest mean absolute error over the last 28 scored days (at least 14 of them) becomes active. A new model takes over only if it is at least 5% better.

### Days that are left out

These days are neither fitted nor scored:

- the thermostat was off for 6 hours or more (you were away)
- no heating at all on a day with a 2-day mean below 12 °C (heating off, or missing data)

## Sensors

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.house_model_gas_forecast_today` | whole-day gas forecast for today, kWh | `forecast` (list of `date`, `kwh`, `weather`: `forecast` or `recent`), `hourly_share` (share of a day's gas in each hour over the last 14 days), `model`, `coefficients` |
| `sensor.house_model_gas_forecast_error` | the active model's mean absolute error over the last 28 days, kWh/day | `model`, `models` (each model's 14- and 28-day error and day counts) |

The large attributes are not written to the recorder.

## Installation

### HACS

Add this repository as a custom repository of type **Integration**, download it, and restart Home Assistant.

### Manual

Copy `custom_components/house_model` to `/config/custom_components/` and restart Home Assistant.

### Setup

Go to **Settings > Devices & services > Add integration > House model**, then pick:

| Field | Notes |
| --- | --- |
| Gas energy | A cumulative kWh sensor with long-term statistics (e.g. your smart meter's gas import) |
| Outdoor temperature | Any outdoor temperature sensor with statistics |
| Outdoor temperature fallback | Optional; fills days the main sensor is missing |
| Heating time today | Optional; hours, counting up and resetting at midnight (e.g. Hive heating time) |
| Thermostat | Optional; used to spot away days |
| Weather forecast | A weather entity with a daily forecast |

## Development

The model code in `custom_components/house_model/core` only needs numpy, so it can be tested without Home Assistant.

```sh
uv venv -p 3.14 .venv
uv pip install -p .venv pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
