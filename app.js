const SOLCAST_API_KEY = "your_solcast_api_key";

async function fetchSolcastData() {
  const response = await axios.get(
    `https://api.solcast.com.au/world_pv_power/forecasts?latitude=52.2297&longitude=21.0122&capacity=1000&api_key=${SOLCAST_API_KEY}&format=json`
  );
  return response.data.forecasts;
}

async function fetchPSEData(date) {
  const formattedDate = date.toISOString().split("T")[0]; // Format: YYYY-MM-DD
  const response = await axios.get(
    `https://api.pse.pl/api/v1/rce-pln?$filter=business_date eq '${formattedDate}'`
  );
  return response.data;
}

async function createChart() {
  const solcastData = await fetchSolcastData();
  const currentDate = new Date();
  const pseData = await fetchPSEData(currentDate);

  const labels = solcastData.map((d) =>
    new Date(d.period_end).toLocaleString()
  );
  const productionData = solcastData.map((d) => d.pv_estimate);
  const priceData = pseData.map((d) => d.price);

  const ctx = document.getElementById("energyChart").getContext("2d");
  new Chart(ctx, {
    type: "line",
    data: {
      labels: labels,
      datasets: [
        {
          label: "Energy Production (kWh)",
          data: productionData,
          borderColor: "rgb(75, 192, 192)",
          tension: 0.1,
        },
        {
          label: "Energy Price (PLN/MWh)",
          data: priceData,
          borderColor: "rgb(255, 99, 132)",
          tension: 0.1,
        },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: {
          type: "time",
          time: {
            unit: "hour",
          },
        },
      },
    },
  });
}

createChart();
