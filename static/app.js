async function fetchData() {
  const response = await fetch("/api/data");
  return response.json();
}

async function createChart() {
  try {
    const data = await fetchData();
    const solcastData = data.solcast;
    const pseData = data.pse;

    // ... (rest of the chart creation code, similar to the previous version)
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
