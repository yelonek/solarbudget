This FASTAPI server backed web app summarizes solar energy production forecast.

It uses Solcast API to get the solar energy production forecast.
The API gives information about solar energy production in kW in 30-minute intervals.

However energy price data is available in 15 minute intervals, 
so the forecast data is interpolated to 15-minute intervals.

It tells you the energy amount in kWh for each 15-minute interval.
It also sums up the energy for the whole day.

The data is visualized with a bar chart for the current day and the next day.
Solcast API can only be called less then 10 times a day, so the data is cached every 3 hours.

Another layer of information is the energy price.
It is fetched from the PSE (Polskie Sieci Elektroenergetyczne) API.
The data does not change, so it can be cached.
The data for the next day is available after 16:00 of the current day.

The visualization shows the value of the energy price in PLN for each 15-minute interval.

You can run this application as dockerized container.