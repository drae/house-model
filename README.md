# House model

A Home Assistant integration that learns how much gas the house uses for the weather, forecasts it, keeps score of its own forecasts, and splits the gas into heating, hot water and hob.

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
| `bayes_heating` | As `bayes`, but fitted on heating gas only (from the gas split), plus the last 14 days' average hot water and hob gas. Scored on total gas like the others |

### Scoring

- Each model's forecast for today is saved the first time it is made each day. Once the day is over, it is compared with what the meter recorded.
- Until there are enough saved forecasts, days earlier in the season are scored by refitting on the days before each one and forecasting it with the temperature that was actually recorded.
- The model with the lowest mean absolute error over the last 28 scored days (at least 14 of them) becomes active. A new model takes over only if it is at least 5% better.

### Days that are left out

These days are neither fitted nor scored:

- the thermostat was off for 6 hours or more (you were away)
- no heating at all on a day with a 2-day mean below 12 °C (heating off, or missing data)

## Gas split

Smart meters book gas in half-hour slots, a few seconds after each one ends. A combi boiler uses no gas when it is idle and no hot water is drawn, so each slot's gas can be shared between what was happening in it:

| Use | Seen as |
| --- | --- |
| Heating | the thermostat's `hvac_action` is `heating` (outside showers: a combi serves hot water first) |
| Hot water | a fast humidity rise in a shower room: 5 points within 5 minutes, until the peak |
| Hob | a fast humidity rise in the kitchen: 6 points within 15 minutes. Not counted within 30 minutes of a shower (steam drifting) or when the electricity load stays above 1.5 kW for most of it (an electric oven) |
| Hob, from the kettle | pans filled from the kettle: a short burst (5-minute max of 2.5 kW or more for up to 10 minutes, then the load drops) with the boiler idle, no shower in the last 30 minutes and no humidity-detected hob. It only claims gas booked by the half-hour slot's own reading (at least 0.1 kWh) with nothing else to explain it, so a kettle for tea claims nothing. No rates are learned from these, since the timing is a guess |
| Anything else | gas with nothing seen counts as hot water (hot taps) |

When a slot holds more than one use, its gas is shared in proportion to each one's time multiplied by its rate (kW).

- **Rates are learned** from clean evidence: slots with heating only, and showers or hob sessions with nothing else happening. They are pooled over 30 days and start from 17 kW (heating), 14 kW (hot water) and 1.3 kW (hob).
- **Late readings:** a reading that books several slots at once is shared by their expected gas. If the activity can't explain it, the day is flagged as lumped.
- **Reliable days** are the ones the heating-only model fits on. A day counts when it is complete, not lumped, and its slots add up to within 0.5 kWh of the meter's daily total.

The split is rebuilt from the recorder's state history on every refresh, for the last two days. The first run backfills the 10 days the recorder keeps.

## Sensors

| Entity | State | Attributes |
| --- | --- | --- |
| `sensor.house_model_gas_forecast_today` | whole-day gas forecast for today, kWh | `forecast` (list of `date`, `kwh`, `weather`: `forecast` or `recent`), `hourly_share` (share of a day's gas in each hour over the last 14 days), `model`, `coefficients` |
| `sensor.house_model_gas_forecast_error` | the active model's mean absolute error over the last 28 days, kWh/day | `model`, `models` (each model's 14- and 28-day error and day counts) |
| `sensor.house_model_gas_heating_today` | heating gas so far today, kWh | `boost` (heating gas while boost was on), `kw` (learned rates), `yesterday`, `yesterday_reliable` |
| `sensor.house_model_gas_hot_water_today` | hot water gas so far today, kWh | `events` (showers today), `yesterday`, `yesterday_reliable` |
| `sensor.house_model_gas_hob_today` | hob gas so far today, kWh | `events` (hob sessions today), `yesterday`, `yesterday_reliable` |
| `sensor.house_model_gas_boost_today` | the part of heating gas so far today used while boost was on, kWh | `yesterday`, `yesterday_reliable` |

The split sensors appear when a thermostat and at least one humidity sensor are set. The large attributes are not written to the recorder.

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
| Shower room humidity | Optional, several allowed; turns on the gas split |
| Kitchen humidity | Optional, several allowed |
| Electricity power | Optional; whole-house power, to tell an electric oven from the hob |

All of these can be changed later under **Configure**.

## Development

The model code in `custom_components/house_model/core` only needs numpy, so it can be tested without Home Assistant.

```sh
uv venv -p 3.14 .venv
uv pip install -p .venv pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

## Licence

BSD 3-Clause. See [LICENSE](LICENSE).
