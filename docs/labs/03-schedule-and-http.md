# Lab 3: Scheduled API check

**You'll build:** from scratch, a workflow that checks the temperature where you live every few
minutes and raises an alert when it's too hot.
**You'll learn:** creating a workflow from an empty canvas, Schedule triggers, HTTP Request,
Python Script, and connecting If outputs.
**Needs:** an internet connection. It uses [Open-Meteo](https://open-meteo.com), which is free
and needs no key. **Time:** 20 minutes.

The finished version is [`weather_alert.json`](../../examples/weather_alert.json). Try building
it yourself first.

## Steps

1. Choose **+ New** and give the workflow a name, such as *Weather alert*.
2. Click the empty canvas and set **Variables** to your location (look up your city's latitude
   and longitude):
   ```json
   { "latitude": 51.51, "longitude": -0.13, "max_temp": 25 }
   ```
3. Drag a **Schedule** node onto the canvas and set:
   - **Mode:** `interval`
   - **Every Seconds:** `60` (you'll slow it down later)
   - **Run On Start:** on
4. Drag an **HTTP Request** node, and connect the Schedule's output (right side) to its input
   (left side). Set:
   - **URL:** `https://api.open-meteo.com/v1/forecast`
   - **Query:**
     ```json
     { "latitude": "{{ vars.latitude }}", "longitude": "{{ vars.longitude }}", "current": "temperature_2m,wind_speed_10m" }
     ```
5. Press **Run** and open the HTTP node's **output**. Find `data.current.temperature_2m`.
6. Add a **Python Script** node after the HTTP node, with this code:
   ```python
   def main(input):
       current = input["data"]["current"]
       log(f"Temperature {current['temperature_2m']} C")
       return {"temp": current["temperature_2m"], "time": current["time"]}
   ```
   Note its **id** (shown under the node's name), for example `read_temp`. You can rename it.
7. Add an **If** node after the script:
   - **Left:** `{{ input.temp }}`
   - **Operator:** `greater_than`
   - **Right:** `{{ vars.max_temp }}`
8. Add two **Set Fields** nodes. Connect the If node's `true` output to one and its `false`
   output to the other:
   - `true`: `{"status": "alert", "message": "Hot: {{ nodes.read_temp.temp }} C"}`
   - `false`: `{"status": "ok", "message": "{{ nodes.read_temp.temp }} C"}`
9. **Save** and **Run**. Then switch it to **Active**. A new run appears in **All activity**
   every minute.
10. When you've seen a few runs, set **Every Seconds** to `300`, or switch to **Mode** `cron`
    with `0 * * * *` (on the hour, every hour), and save.

## Check your work

- The Python node's log line shows the current temperature.
- Lower `max_temp` below the current temperature and run again. The `alert` branch runs.

## Challenges

- Add wind: fetch `wind_speed_10m` too and alert when it's above 40 km/h, using a second If node.
- Use cron `0 7 * * *` to check only once a day at 7:00.
- Replace Open-Meteo with any other public JSON API you like, and pull out one field with Python.

## What you learned

- Schedules run in local time, by interval or cron. Runs missed while the PC was off aren't
  caught up.
- HTTP Request output is `{status, headers, data}`. JSON responses are parsed into `data`.
- Python Script nodes receive the previous output as `input` and return a JSON-serializable
  value. `log()` writes to the run log.

**Next:** [Lab 4: Folder sorter](04-folder-watcher.md)
