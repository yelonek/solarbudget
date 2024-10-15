const SOLCAST_API_KEY = "_JHf-pgwuLNn-5OeV74GcxQAnK70y9Ru";
const CORS_PROXY = "https://cors-anywhere.herokuapp.com/";

async function fetchSolcastData() {
  const response = await axios.get(
    `${CORS_PROXY}https://api.solcast.com.au/rooftop_sites/6803-0207-f7d6-3a1f/forecasts?format=json`,
    {
      headers: {
        Authorization: `Bearer ${SOLCAST_API_KEY}`,
      },
    }
  );
  return response.data.forecasts;
}

async function fetchPSEData(date) {
  const formattedDate = date.toISOString().split("T")[0]; // Format: YYYY-MM-DD
  const encodedFilter = encodeURIComponent(
    `business_date eq '${formattedDate}'`
  );
  const response = await axios.get(
    `https://api.raporty.pse.pl/api/rce-pln?$filter=${encodedFilter}`
  );
  return response.data.value;
}

async function createChart() {
  try {
    const solcastData = await fetchSolcastData();
    const currentDate = new Date();
    const pseData = await fetchPSEData(currentDate);

    const labels = solcastData.map((d) => moment(d.period_end));
    const productionData10 = solcastData.map((d) => ({
      x: moment(d.period_end),
      y: d.pv_estimate10,
    }));
    const productionData50 = solcastData.map((d) => ({
      x: moment(d.period_end),
      y: d.pv_estimate,
    }));
    const productionData90 = solcastData.map((d) => ({
      x: moment(d.period_end),
      y: d.pv_estimate90,
    }));
    const priceData = pseData.map((d) => ({
      x: moment(d.udtczas),
      y: d.rce_pln,
    }));

    const ctx = document.getElementById("energyChart").getContext("2d");
    new Chart(ctx, {
      type: "line",
      data: {
        labels: labels,
        datasets: [
          {
            label: "Energy Production 10th Percentile (kWh)",
            data: productionData10,
            borderColor: "rgba(75, 192, 192, 0.5)",
            fill: false,
            yAxisID: "y-production",
          },
          {
            label: "Energy Production 50th Percentile (kWh)",
            data: productionData50,
            borderColor: "rgb(75, 192, 192)",
            fill: false,
            yAxisID: "y-production",
          },
          {
            label: "Energy Production 90th Percentile (kWh)",
            data: productionData90,
            borderColor: "rgba(75, 192, 192, 0.8)",
            fill: false,
            yAxisID: "y-production",
          },
          {
            label: "Energy Price (PLN/MWh)",
            data: priceData,
            borderColor: "rgb(255, 99, 132)",
            fill: false,
            yAxisID: "y-price",
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
              displayFormats: {
                hour: "YYYY-MM-DD HH:mm",
              },
            },
            title: {
              display: true,
              text: "Time",
            },
          },
          "y-production": {
            type: "linear",
            display: true,
            position: "left",
            title: {
              display: true,
              text: "Energy Production (kWh)",
            },
          },
          "y-price": {
            type: "linear",
            display: true,
            position: "right",
            title: {
              display: true,
              text: "Energy Price (PLN/MWh)",
            },
            grid: {
              drawOnChartArea: false,
            },
          },
        },
        plugins: {
          tooltip: {
            mode: "index",
            intersect: false,
          },
          legend: {
            position: "top",
          },
        },
      },
    });
  } catch (error) {
    console.error("Error fetching data:", error);
    document.getElementById("error-message").textContent =
      "Error fetching data. Please try again.";
  }
}

function handleFetchData() {
  document.getElementById("fetch-data").disabled = true;
  document.getElementById("error-message").textContent = "";
  createChart().finally(() => {
    document.getElementById("fetch-data").disabled = false;
  });
}

document
  .getElementById("fetch-data")
  .addEventListener("click", handleFetchData);
